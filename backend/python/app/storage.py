"""Phase-2 read adapters. Call inside OracleDatabase.read() for one consistent snapshot.

These are not exposed as unauthenticated endpoints or arbitrary-SQL agent tools.
Callers must apply actor/record scope before loading staffing evidence.
"""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from pydantic import ValidationError

from app.capacity import CapacityLedger, DailyHours, dates_between
from app.contracts import RequestSnapshot
from app.errors import ServiceError
from app.policy import StaffingPolicy

# Fixed aliases: assignment a and dated schedule d. Keep this predicate shared
# by ledger calculations and calendar responses. The original APPROVED policy
# is immutable, so a later runtime-policy/timezone change cannot move the cutoff.
# Closing-day hours remain planned history; only subsequent dates are released.
# CANCELLED (including demo-import recovery) deliberately retains its old meaning.
CLOSURE_DAY_SQL = "TRUNC(CAST((a.closed_at AT TIME ZONE closure_policy.scheduling_timezone) AS TIMESTAMP))"
COUNTED_ASSIGNMENT_DAY_SQL = f"""(a.status='CONFIRMED' OR (
    a.status='CLOSED' AND EXISTS (
        SELECT 1 FROM load_guardrails closure_policy
        WHERE closure_policy.policy_version=a.policy_version
        AND d.work_date<={CLOSURE_DAY_SQL}
    )
))"""


def rows(connection, sql, **binds):
    with connection.cursor() as cursor:
        cursor.execute(sql, binds)
        names = [column[0].lower() for column in cursor.description]
        return [dict(zip(names, record, strict=True)) for record in cursor.fetchall()]


def document(value):
    if hasattr(value, "read"):
        value = value.read()
    # Oracle may return JSON as decoded objects/arrays instead of CLOB text.
    # The caller still validates the document's shape and business rules.
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, (str, bytes, bytearray)):
        raise ValueError("Expected stored JSON text, object or array")
    return json.loads(value)


def calendar_day(value):
    if isinstance(value, datetime):
        if value.time().isoformat() != "00:00:00":
            raise ValueError("Stored business date contains time")
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError("Missing business date")


def load_policy(connection, version: str) -> StaffingPolicy:
    records = rows(connection, """
        SELECT p.policy_version, p.status, p.approved_by, p.approved_at,
               l.default_weekly_hours, l.maximum_allocation_pct, l.scheduling_timezone,
               w.skill_weight, w.deliverable_weight, w.capacity_weight, w.interest_weight
          FROM staffing_policies p JOIN load_guardrails l ON l.policy_version=p.policy_version
          JOIN scoring_weights w ON w.policy_version=p.policy_version
         WHERE p.policy_version=:policyVersion
    """, policyVersion=version)
    if len(records) != 1:
        raise ServiceError("POLICY_NOT_FOUND", "The requested policy version is missing or incomplete.", 409)
    rule_rows = rows(connection, "SELECT rule_code,rule_value_json FROM eligibility_rules WHERE policy_version=:policyVersion",
                     policyVersion=version)
    try:
        rule_documents = {row["rule_code"]: document(row["rule_value_json"]) for row in rule_rows}
        values = {code: value["value"] for code, value in rule_documents.items()}
        if len(rule_rows) != 4 or set(values) != {"MINIMUM_STRENGTH", "LEAD_ROLE", "MEMBER_ROLES", "MAX_AGENT_STEPS"}:
            raise ValueError("Unexpected policy rules")
        for code, value in rule_documents.items():
            allowed = {"value", "scheduling"} if code == "MAX_AGENT_STEPS" else {"value"}
            if not isinstance(value, dict) or not set(value) <= allowed:
                raise ValueError("Unexpected policy rule fields")
        scheduling = rule_documents["MAX_AGENT_STEPS"].get("scheduling")
        if "scheduling" in rule_documents["MAX_AGENT_STEPS"]:
            if not isinstance(scheduling, dict) or set(scheduling) != {
                "algorithm", "minimum_member_hours", "minimum_equal_share_pct"
            }:
                raise ValueError("Incomplete or unknown scheduling configuration")
        if version == "staffing-demo-v2" and scheduling is None:
            raise ValueError("The v2 demonstration policy requires explicit scheduling rules")
        row = records[0]
        return StaffingPolicy(
            version=row["policy_version"], status=row["status"], approved_by=row["approved_by"],
            approved_at=row["approved_at"].isoformat() if row["approved_at"] else None,
            default_weekly_hours=Decimal(str(row["default_weekly_hours"])),
            maximum_allocation_pct=Decimal(str(row["maximum_allocation_pct"])),
            scheduling_timezone=row["scheduling_timezone"], minimum_strength=values["MINIMUM_STRENGTH"],
            lead_role_code=values["LEAD_ROLE"], member_role_codes=values["MEMBER_ROLES"],
            maximum_agent_steps=values["MAX_AGENT_STEPS"],
            scheduling=scheduling,
            weights={name: row[f"{name}_weight"] for name in ("skill", "deliverable", "capacity", "interest")},
        )
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ServiceError("INVALID_POLICY", "Stored staffing policy needs review.", 409) from error


def load_request_snapshot(connection, request_id: str) -> RequestSnapshot:
    records = rows(connection, """
        SELECT request_id,request_revision,responsible_captain_id,title,estimated_start_date,
               estimated_completion_date,estimated_hours,requested_lead_count,requested_contributor_count,deliverables_json
          FROM requests WHERE request_id=:requestId
    """, requestId=request_id)
    if len(records) != 1:
        raise ServiceError("REQUEST_NOT_FOUND", "The staffing request was not found.", 404)
    requirements = rows(connection, """
        SELECT r.interest_id,r.mandatory_flag,r.required_strength,r.capability_source,
               i.assessment_type,i.derived_role_code
          FROM requirements r LEFT JOIN interests i ON i.interest_id=r.interest_id
         WHERE r.request_id=:requestId ORDER BY r.requirement_id
    """, requestId=request_id)
    try:
        row = records[0]
        # Never convert a custom mandatory capability into a made-up catalogue skill ID.
        normalized = {}
        for item in requirements:
            if item["mandatory_flag"] not in ("Y", "N"):
                raise ValueError("Unknown requirement flag")
            if not item["interest_id"] or item["capability_source"] == "CUSTOM":
                if item["mandatory_flag"] == "Y":
                    raise ValueError("Unresolved mandatory capability")
                continue
            skill = {"skill_id": item["interest_id"], "mandatory": item["mandatory_flag"] == "Y",
                     "assessment_type": item["assessment_type"], "derived_role_code": item["derived_role_code"],
                     "minimum_strength": None if item["assessment_type"] == "ROLE_DERIVED" else item["required_strength"]}
            previous = normalized.get(item["interest_id"])
            if previous:
                skill["mandatory"] |= previous["mandatory"]
                strengths = [value for value in (skill["minimum_strength"], previous["minimum_strength"]) if value is not None]
                skill["minimum_strength"] = max(strengths) if strengths else None
            normalized[item["interest_id"]] = skill
        deliverables = document(row["deliverables_json"])
        if not isinstance(deliverables, list) or any(not isinstance(item, dict) or item.get("custom") for item in deliverables):
            raise ValueError("Resolve custom deliverables before staffing")
        return RequestSnapshot(
            request_id=row["request_id"], revision=row["request_revision"],
            responsible_captain_id=row["responsible_captain_id"], title=row["title"],
            starts_on=calendar_day(row["estimated_start_date"]), ends_on=calendar_day(row["estimated_completion_date"]),
            total_hours=Decimal(str(row["estimated_hours"])),
            lead_count=row["requested_lead_count"], member_count=row["requested_contributor_count"],
            deliverable_ids=[item.get("id") or item.get("deliverableId") for item in deliverables],
            requirements=list(normalized.values()),
        )
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ServiceError("NEEDS_INFORMATION", "Confirm the Captain, schedule, hours, POD counts and catalogue capabilities.", 422) from error


def load_capacity_ledger(connection, person_id: str, start: date, end: date) -> tuple[CapacityLedger, int]:
    list(dates_between(start, end))
    first = start - timedelta(days=start.weekday())
    last = end + timedelta(days=6 - end.weekday())
    people = rows(connection, """SELECT weekly_work_hours,workload_version,availability_version
        FROM people WHERE person_id=:personId AND active_flag='Y'""", personId=person_id)
    if len(people) != 1 or people[0]["weekly_work_hours"] is None:
        raise ServiceError("CAPACITY_UNKNOWN", "Working hours have not been established for this person.", 409)
    days = rows(connection, """SELECT work_date,available_hours,external_committed_hours,availability_version
        FROM person_capacity_days WHERE person_id=:personId AND work_date BETWEEN :startDay AND :endDay
        ORDER BY work_date""", personId=person_id, startDay=first, endDay=last)
    assigned = rows(connection, f"""SELECT d.work_date,SUM(d.assigned_hours) AS hours
        FROM assignment_days d JOIN pod_assignments a ON a.assignment_id=d.assignment_id
        WHERE d.person_id=:personId AND {COUNTED_ASSIGNMENT_DAY_SQL}
        AND d.work_date BETWEEN :startDay AND :endDay
        GROUP BY d.work_date""", personId=person_id, startDay=first, endDay=last)
    try:
        expected = set(dates_between(first, last))
        actual = {calendar_day(row["work_date"]) for row in days}
        if len(days) != len(expected) or actual != expected:
            raise ValueError("Incomplete weekly ledger")
        weekly = Decimal(str(people[0]["weekly_work_hours"]))
        absences, external = [], []
        for row in days:
            day = calendar_day(row["work_date"])
            if row["availability_version"] != people[0]["availability_version"]:
                raise ValueError("Availability changed after ledger was built")
            base = weekly / 5 if day.weekday() < 5 else Decimal(0)
            available = Decimal(str(row["available_hours"]))
            if available < 0 or available > base:
                raise ValueError("Availability exceeds working pattern")
            absences.append(DailyHours(day=day, hours=base - available))
            external.append(DailyHours(day=day, hours=Decimal(str(row["external_committed_hours"]))))
        return CapacityLedger(weekly_hours=weekly, absences=tuple(absences), external_work=tuple(external),
            confirmed_work=tuple(DailyHours(day=calendar_day(row["work_date"]), hours=Decimal(str(row["hours"])))
                                 for row in assigned)), people[0]["workload_version"]
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ServiceError("CAPACITY_STALE", "Daily capacity is incomplete or needs refresh after availability changes.", 409) from error
