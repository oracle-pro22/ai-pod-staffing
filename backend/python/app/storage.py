"""Phase-2 read adapters. Call inside OracleDatabase.read() for one consistent snapshot.

These are not exposed as unauthenticated endpoints or arbitrary-SQL agent tools.
Callers must apply actor/record scope before loading staffing evidence.
"""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from pydantic import ValidationError

from app.capacity import CapacityLedger, DailyHours, dates_between, spread_hours
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
               r.custom_capability_name,r.skill_name,
               i.assessment_type,i.derived_role_code
          FROM requirements r LEFT JOIN interests i ON i.interest_id=r.interest_id
         WHERE r.request_id=:requestId ORDER BY r.requirement_id
    """, requestId=request_id)
    try:
        row = records[0]
        # Never convert a custom mandatory capability into a made-up catalogue skill ID.
        normalized = {}
        unresolved_mandatory = []
        for item in requirements:
            if item["mandatory_flag"] not in ("Y", "N"):
                raise ValueError("Unknown requirement flag")
            if not item["interest_id"] or item["capability_source"] == "CUSTOM":
                if item["mandatory_flag"] == "Y":
                    unresolved_mandatory.append(item.get('custom_capability_name') or item.get('skill_name') or 'Unnamed capability')
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
        if unresolved_mandatory:
            names = ', '.join(unresolved_mandatory[:5])
            raise ServiceError('NEEDS_INFORMATION',
                f'Map the required custom capability to the approved catalogue before staffing: {names}.', 422)
        deliverables = document(row["deliverables_json"])
        if not isinstance(deliverables, list) or any(not isinstance(item, dict) for item in deliverables):
            raise ValueError("Invalid deliverables")
        deliverable_ids = [item.get("id") or item.get("deliverableId") for item in deliverables]
        custom_deliverables = {deliverable_id: item.get("name", "") for item, deliverable_id in zip(deliverables, deliverable_ids, strict=True)
                               if item.get("custom") is True}
        return RequestSnapshot(
            request_id=row["request_id"], revision=row["request_revision"],
            responsible_captain_id=row["responsible_captain_id"], title=row["title"],
            starts_on=calendar_day(row["estimated_start_date"]), ends_on=calendar_day(row["estimated_completion_date"]),
            total_hours=Decimal(str(row["estimated_hours"])),
            lead_count=row["requested_lead_count"], member_count=row["requested_contributor_count"],
            deliverable_ids=deliverable_ids, custom_deliverables=custom_deliverables,
            requirements=list(normalized.values()),
        )
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ServiceError("NEEDS_INFORMATION", "Confirm the Captain, schedule, hours, POD counts and catalogue capabilities.", 422) from error


def load_capacity_ledgers(connection, person_ids, start: date, end: date):
    """Load many weekly ledgers with four set-based queries.

    The previous reports path issued four ledger queries per visible person.
    Results intentionally retain a per-person ServiceError so one stale profile
    remains visible as ``Needs refresh`` without hiding valid teammates.
    """
    list(dates_between(start, end))
    identifiers = tuple(dict.fromkeys(str(value) for value in person_ids if value))
    if not identifiers:
        return {}
    if len(identifiers) > 1000:
        raise ValueError("Capacity batch is too large")
    first = start - timedelta(days=start.weekday())
    last = end + timedelta(days=6 - end.weekday())
    id_binds = {f"person{index}": value for index, value in enumerate(identifiers)}
    placeholders = ",".join(f":person{index}" for index in range(len(identifiers)))
    date_binds = {**id_binds, "startDay": first, "endDay": last}
    people = rows(connection, f"""SELECT person_id,weekly_work_hours,workload_version,availability_version
        FROM people WHERE person_id IN ({placeholders}) AND active_flag='Y'""", **id_binds)
    days = rows(connection, f"""SELECT person_id,work_date,available_hours,external_committed_hours,availability_version
        FROM person_capacity_days WHERE person_id IN ({placeholders})
        AND work_date BETWEEN :startDay AND :endDay ORDER BY person_id,work_date""", **date_binds)
    def group(records):
        grouped = {person_id: [] for person_id in identifiers}
        for row in records:
            # A single-person call remains compatible with lightweight store
            # adapters that omit a constant person_id projection.
            person_id = row.get("person_id") if hasattr(row, "get") else None
            if person_id is None and len(identifiers) == 1:
                person_id = identifiers[0]
            if person_id in grouped:
                grouped[person_id].append(row)
        return grouped

    people_groups = group(people)
    people_by_id = {person_id: records[0] for person_id, records in people_groups.items() if len(records) == 1}
    days_by_id = {person_id: [] for person_id in identifiers}
    days_by_id.update(group(days))
    expected = set(dates_between(first, last))
    result = {}
    valid_ids = []
    for person_id in identifiers:
        person = people_by_id.get(person_id)
        if not person or person["weekly_work_hours"] is None:
            result[person_id] = ServiceError("CAPACITY_UNKNOWN", "Working hours have not been established for this person.", 409)
            continue
        try:
            person_days = days_by_id.get(person_id, [])
            actual = {calendar_day(row["work_date"]) for row in person_days}
            if len(person_days) != len(expected) or actual != expected:
                raise ValueError("Incomplete weekly ledger")
            if any(row["availability_version"] != person["availability_version"] for row in person_days):
                raise ValueError("Availability changed after ledger was built")
            valid_ids.append(person_id)
        except (KeyError, TypeError, ValueError, ValidationError):
            result[person_id] = ServiceError("CAPACITY_STALE", "Daily capacity is incomplete or needs refresh after availability changes.", 409)

    if not valid_ids:
        return result
    valid_binds = {f"person{index}": value for index, value in enumerate(valid_ids)}
    valid_placeholders = ",".join(f":person{index}" for index in range(len(valid_ids)))
    valid_date_binds = {**valid_binds, "startDay": first, "endDay": last}
    assigned = rows(connection, f"""SELECT d.person_id,d.work_date,SUM(d.assigned_hours) AS hours
        FROM assignment_days d JOIN pod_assignments a ON a.assignment_id=d.assignment_id
        WHERE d.person_id IN ({valid_placeholders}) AND {COUNTED_ASSIGNMENT_DAY_SQL}
        AND d.work_date BETWEEN :startDay AND :endDay
        GROUP BY d.person_id,d.work_date""", **valid_date_binds)
    reported = rows(connection, f"""SELECT person_id,starts_on,ends_on,total_hours FROM roster_pod_claims
        WHERE person_id IN ({valid_placeholders}) AND status='PENDING'
        AND starts_on<=:endDay AND ends_on>=:startDay""", **valid_date_binds)
    assigned_by_id = group(assigned)
    reported_by_id = group(reported)
    for person_id in valid_ids:
        person = people_by_id[person_id]
        try:
            person_days = days_by_id[person_id]
            weekly = Decimal(str(person["weekly_work_hours"]))
            absences, external = [], []
            for row in person_days:
                day = calendar_day(row["work_date"])
                base = weekly / 5 if day.weekday() < 5 else Decimal(0)
                available = Decimal(str(row["available_hours"]))
                if available < 0 or available > base:
                    raise ValueError("Availability exceeds working pattern")
                absences.append(DailyHours(day=day, hours=base - available))
                external.append(DailyHours(day=day, hours=Decimal(str(row["external_committed_hours"]))))
            reported_days = {}
            for claim in reported_by_id.get(person_id, []):
                for entry in spread_hours(Decimal(str(claim['total_hours'])), calendar_day(claim['starts_on']), calendar_day(claim['ends_on'])):
                    if first <= entry.day <= last:
                        reported_days[entry.day] = reported_days.get(entry.day, Decimal(0)) + entry.hours
            ledger = CapacityLedger(weekly_hours=weekly, absences=tuple(absences), external_work=tuple(external),
                reported_pod_work=tuple(DailyHours(day=day, hours=hours) for day, hours in sorted(reported_days.items())),
                confirmed_work=tuple(DailyHours(day=calendar_day(row["work_date"]), hours=Decimal(str(row["hours"])))
                                     for row in assigned_by_id.get(person_id, [])))
            result[person_id] = (ledger, person["workload_version"])
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            result[person_id] = ServiceError("CAPACITY_STALE", "Daily capacity is incomplete or needs refresh after availability changes.", 409)
    return result


def load_capacity_ledger(connection, person_id: str, start: date, end: date) -> tuple[CapacityLedger, int]:
    loaded = load_capacity_ledgers(connection, (person_id,), start, end).get(person_id)
    if isinstance(loaded, ServiceError):
        raise loaded
    if loaded is None:
        raise ServiceError("CAPACITY_UNKNOWN", "Working hours have not been established for this person.", 409)
    return loaded
