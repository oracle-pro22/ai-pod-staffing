"""Identity-scoped final PODs, weekly capacity and serialized project closure."""
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import Field

from app.capacity import calculate_capacity
from app.contracts import Contract
from app.errors import ServiceError
from app.execution_store import execute
from app.planning import json_text
from app.storage import COUNTED_ASSIGNMENT_DAY_SQL, load_capacity_ledger, load_policy, rows

# Fixed outer alias p. Identity authentication deliberately does not use this
# employee-directory predicate: standalone administrators must remain active.
ADMINISTRATOR_ONLY_SQL = """EXISTS (
    SELECT 1 FROM app_user_roles employee_admin_role
    JOIN app_roles employee_admin_profile ON employee_admin_profile.role_code=employee_admin_role.role_code
    WHERE employee_admin_role.person_id=p.person_id AND employee_admin_role.role_code='SYSTEM_ADMINISTRATOR'
    AND employee_admin_role.active_flag='Y' AND employee_admin_profile.active_flag='Y'
    AND employee_admin_role.effective_from<=TRUNC(SYSDATE)
    AND (employee_admin_role.effective_to IS NULL OR employee_admin_role.effective_to>=TRUNC(SYSDATE))
) AND NOT EXISTS (
    SELECT 1 FROM app_user_roles employee_staff_role
    JOIN app_roles employee_staff_profile ON employee_staff_profile.role_code=employee_staff_role.role_code
    WHERE employee_staff_role.person_id=p.person_id
    AND employee_staff_role.role_code IN ('POD_CAPTAIN','POD_LEAD','POD_MEMBER')
    AND employee_staff_role.active_flag='Y' AND employee_staff_profile.active_flag='Y'
    AND employee_staff_role.effective_from<=TRUNC(SYSDATE)
    AND (employee_staff_role.effective_to IS NULL OR employee_staff_role.effective_to>=TRUNC(SYSDATE))
)"""


class CloseProject(Contract):
    request_revision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=2000)


def scope_clause(actor, resource):
    permission = actor.require(resource, "view")
    if permission.role == "SYSTEM_ADMINISTRATOR" and permission.scope == "FULL":
        return "1=1", {}
    if permission.role == "POD_CAPTAIN":
        return "r.responsible_captain_id=:viewerId", {"viewerId": actor.person_id}
    # Team access comes only from final assignments, never request source/recommendations.
    role_filter = " AND mine.role_in_pod='POD_LEAD'" if permission.role == "POD_LEAD" else ""
    return ("EXISTS (SELECT 1 FROM pod_assignments mine WHERE mine.request_id=r.request_id "
            "AND mine.person_id=:viewerId AND mine.status IN ('CONFIRMED','CLOSED')" + role_filter + ")",
            {"viewerId": actor.person_id})


def team_people_scope(actor, permission):
    """Intersect the effective permission with each profile's maximum visibility."""
    if (permission.resource != "TEAM_SKILLS" or permission.role not in actor.roles
        or permission.role not in {"POD_MEMBER", "POD_LEAD", "POD_CAPTAIN", "SYSTEM_ADMINISTRATOR"}
        or permission.scope not in ("OWN", "SCOPED", "FULL") or "view" not in permission.actions):
        raise ServiceError("FORBIDDEN", "Team profile access is not permitted.", 403)
    own = "p.person_id=:profileViewerId"
    binds = {"profileViewerId": actor.person_id}
    if permission.scope == "OWN" or permission.role == "POD_MEMBER":
        return own, binds
    if permission.role in ("POD_CAPTAIN", "SYSTEM_ADMINISTRATOR"):
        if permission.scope == "FULL":
            return "1=1", {}
        return own, binds
    if permission.role != "POD_LEAD":
        raise ServiceError("FORBIDDEN", "Unknown staffing profile.", 403)
    return own + """ OR EXISTS (
        SELECT 1 FROM pod_assignments team_member
        JOIN requests team_request ON team_request.request_id=team_member.request_id
        JOIN pod_assignments team_lead ON team_lead.request_id=team_request.request_id
        WHERE team_member.person_id=p.person_id AND team_member.status='CONFIRMED'
        AND team_request.status='STAFFED'
        AND team_lead.person_id=:profileViewerId AND team_lead.role_in_pod='POD_LEAD'
        AND team_lead.status='CONFIRMED'
    )""", binds


class AssignmentStore:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def team_workspace(self, actor, week: date | None = None):
        """Independent profile allowlist; project membership is not profile access."""
        permission = actor.require("TEAM_SKILLS", "view")
        predicate, binds = team_people_scope(actor, permission)
        with self.database.read() as connection:
            policy = load_policy(connection, self.settings.staffing_policy_version)
            today = datetime.now(ZoneInfo(policy.scheduling_timezone)).date()
            selected = week or today
            monday = selected - timedelta(days=selected.weekday())
            sunday = monday + timedelta(days=6)
            visible = rows(connection, f"""SELECT p.person_id FROM people p
                WHERE p.active_flag='Y' AND NOT ({ADMINISTRATOR_ONLY_SQL})
                AND ({predicate}) ORDER BY p.person_id""", **binds)
            people = []
            for person in visible:
                pid = person["person_id"]
                value = {"person_id": pid, "allocation_pct": None, "capacity_status": "UNKNOWN"}
                try:
                    ledger, _ = load_capacity_ledger(connection, pid, monday, sunday)
                    capacity = calculate_capacity(ledger, monday, sunday, (), policy.maximum_allocation_pct)
                    value.update(capacity_status="CURRENT", allocation_pct=capacity.weeks[0].allocation_pct,
                                 weeks=[w.model_dump(mode="json") for w in capacity.weeks])
                except ServiceError as error:
                    if error.code not in ("CAPACITY_UNKNOWN", "CAPACITY_STALE"):
                        raise
                    value["capacity_status"] = error.code
                value["active_pods"] = rows(connection, """SELECT COUNT(DISTINCT request_id) AS total
                    FROM pod_assignments WHERE person_id=:personId AND status='CONFIRMED'
                    AND starts_on<=:todayDay AND ends_on>=:todayDay""", personId=pid, todayDay=today)[0]["total"]
                people.append(value)
            # Keep the workspace envelope, without borrowing request rosters,
            # assignment schedules or proposal statistics for a profile response.
            return {"requests": [], "assignments": [], "days": [], "people": people,
                    "summary": {"pending_review": 0, "approved": 0, "rejected": 0},
                    "week_start": monday, "week_end": sunday, "timezone": policy.scheduling_timezone,
                    "can_export": "export" in permission.actions}

    def workspace(self, actor, week: date | None = None, resource="REQUESTS"):
        if resource == "TEAM_SKILLS":
            return self.team_workspace(actor, week)
        clause, binds = scope_clause(actor, resource)
        permission = actor.require(resource, 'view')
        own_only = permission.scope == 'OWN' and resource != 'REQUESTS'
        assignment_filter = " AND a.person_id=:ownId" if own_only else ""
        assignment_binds = {**binds, **({'ownId': actor.person_id} if own_only else {})}
        with self.database.read() as connection:
            if resource == 'REPORTS':
                from app.policy_admin import active_policy_version
                policy = load_policy(connection, active_policy_version(connection))
            else:
                policy = load_policy(connection, self.settings.staffing_policy_version)
            today = datetime.now(ZoneInfo(policy.scheduling_timezone)).date()
            selected = week or today
            monday = selected - timedelta(days=selected.weekday())
            sunday = monday + timedelta(days=6)
            requests = rows(connection, f"""SELECT r.request_id,r.title,r.status,r.request_revision,
                r.responsible_captain_id,r.estimated_completion_date AS planned_end_on,
                CASE WHEN r.status='STAFFED' AND r.estimated_completion_date<:businessToday
                    THEN 1 ELSE 0 END AS past_planned_end
                FROM requests r WHERE {clause} ORDER BY r.created_at DESC,r.request_id""", **binds, businessToday=today)
            for request in requests:
                request['past_planned_end'] = bool(request['past_planned_end'])
            policy_filter = ' AND p.policy_version=:activePolicy' if resource == 'REPORTS' else ''
            summary_binds = {**binds, **({'activePolicy': policy.version} if resource == 'REPORTS' else {})}
            summary = rows(connection, f"""SELECT
                COUNT(CASE WHEN p.status='READY_FOR_REVIEW' AND p.request_revision=r.request_revision
                    {policy_filter} THEN 1 END) AS pending_review,
                COUNT(CASE WHEN p.status='APPROVED' THEN 1 END) AS approved,
                COUNT(CASE WHEN p.status='REJECTED' THEN 1 END) AS rejected
                FROM pod_proposals p JOIN requests r ON r.request_id=p.request_id WHERE {clause}""", **summary_binds)[0]
            assignments = rows(connection, f"""SELECT a.assignment_id,a.request_id,a.person_id,p.full_name,
                a.role_in_pod,a.status,a.starts_on,a.ends_on,a.assigned_hours,a.closed_at,a.close_reason,
                m.responsibilities FROM pod_assignments a JOIN requests r ON r.request_id=a.request_id
                JOIN people p ON p.person_id=a.person_id
                JOIN pod_proposal_members m ON m.proposal_id=a.proposal_id AND m.person_id=a.person_id
                WHERE a.status IN ('CONFIRMED','CLOSED') AND {clause}{assignment_filter} ORDER BY a.request_id,a.role_in_pod,a.person_id""", **assignment_binds)
            days = rows(connection, f"""SELECT d.assignment_id,d.person_id,d.work_date,d.assigned_hours,a.request_id
                FROM assignment_days d JOIN pod_assignments a ON a.assignment_id=d.assignment_id
                JOIN requests r ON r.request_id=a.request_id WHERE {COUNTED_ASSIGNMENT_DAY_SQL}
                AND d.work_date BETWEEN :weekStart AND :weekEnd AND {clause}{assignment_filter}
                ORDER BY d.work_date,d.person_id""", **assignment_binds, weekStart=monday, weekEnd=sunday)
            # A request roster is NOT a profile/capacity permission. Apply the
            # same profile boundary on every workspace resource, including
            # direct calendar/report requests and historical project rosters.
            profile_permissions = [p for p in actor.permissions if p.role == permission.role
                                   and p.resource == "TEAM_SKILLS" and p.scope != "LOCKED"
                                   and "view" in p.actions]
            predicate, profile_binds = "p.person_id=:profileViewerId", {"profileViewerId": actor.person_id}
            if profile_permissions and not own_only:
                profile_permission = max(profile_permissions, key=lambda p: {"OWN": 1, "SCOPED": 2, "FULL": 3}.get(p.scope, 0))
                predicate, profile_binds = team_people_scope(actor, profile_permission)
            profile_rows = rows(connection, f"""SELECT p.person_id,p.full_name FROM people p
                WHERE p.active_flag='Y' AND NOT ({ADMINISTRATOR_ONLY_SQL})
                AND ({predicate}) ORDER BY p.person_id""", **profile_binds)
            person_ids = {p['person_id'] for p in profile_rows}
            profile_names = {p['person_id']: p.get('full_name', p['person_id']) for p in profile_rows}
            # Basic project teammates remain visible without their personal
            # schedule, closure notes or workload. Never send hidden fields.
            roster_fields = {"assignment_id", "request_id", "person_id", "full_name", "role_in_pod", "status", "responsibilities"}
            public_assignments = []
            for assignment in assignments:
                if assignment["person_id"] in person_ids:
                    public_assignments.append(assignment)
                    continue
                public = {key: value for key, value in assignment.items() if key in roster_fields}
                # Model-authored responsibilities can contain skill/evidence
                # summaries and planned hours. Do not attempt text redaction:
                # use only the authorized project role for this basic roster.
                public["responsibilities"] = (
                    "Coordinate the POD and guide delivery of the request's deliverables."
                    if assignment["role_in_pod"] == "POD_LEAD" else
                    "Contribute to the request's deliverables with the POD lead."
                )
                public_assignments.append(public)
            assignments = public_assignments
            days = [d for d in days if d["person_id"] in person_ids]
            people = []
            for pid in sorted(person_ids):
                value = {"person_id": pid, "full_name": profile_names[pid], "allocation_pct": None, "capacity_status": "UNKNOWN"}
                try:
                    ledger, _ = load_capacity_ledger(connection, pid, monday, sunday)
                    capacity = calculate_capacity(ledger, monday, sunday, (), policy.maximum_allocation_pct)
                    value.update(capacity_status="CURRENT", allocation_pct=capacity.weeks[0].allocation_pct,
                                 weeks=[w.model_dump(mode="json") for w in capacity.weeks])
                except ServiceError as error:
                    if error.code not in ("CAPACITY_UNKNOWN", "CAPACITY_STALE"):
                        raise
                    value["capacity_status"] = error.code
                # Count current confirmed PODs, not historical/preview fields or pending proposals.
                value["active_pods"] = rows(connection, """SELECT COUNT(DISTINCT request_id) AS total
                    FROM pod_assignments WHERE person_id=:personId AND status='CONFIRMED'
                    AND starts_on<=:todayDay AND ends_on>=:todayDay""", personId=pid, todayDay=today)[0]["total"]
                people.append(value)
            return {"requests": requests, "assignments": assignments, "days": days, "people": people,
                    "summary": summary,
                    "week_start": monday, "week_end": sunday, "timezone": policy.scheduling_timezone,
                    "as_of": today, "maximum_allocation_pct": policy.maximum_allocation_pct,
                    "policy_version": policy.version,
                    "request_scope": 'All requests' if clause == '1=1' else 'Your requests' if permission.role == 'POD_CAPTAIN' else 'Assigned requests',
                    "can_export": any(p.resource == resource and p.role in actor.roles and p.scope != "LOCKED"
                                      and {"view", "export"} <= p.actions for p in actor.permissions)}

    def close(self, actor, request_id, body):
        if not self.settings.staffing_decisions_enabled:
            raise ServiceError("DECISIONS_DISABLED", "Project changes are not enabled.", 503)
        actor.require("REQUESTS", "update", "POD_LEAD")
        with self.database.write() as connection:
            request = rows(connection, "SELECT status,request_revision FROM requests WHERE request_id=:requestId FOR UPDATE WAIT 5", requestId=request_id)
            if not request:
                raise ServiceError("REQUEST_NOT_FOUND", "Project not found.", 404)
            # Recheck actual effective Lead identity and permission in the transaction.
            linked = rows(connection, """SELECT ur.person_id FROM app_user_roles ur
                JOIN app_roles ar ON ar.role_code=ur.role_code AND ar.active_flag='Y'
                JOIN people p ON p.person_id=ur.person_id AND p.active_flag='Y'
                JOIN role_permissions rp ON rp.role_code=ar.role_code AND rp.resource_code='REQUESTS'
                WHERE ur.identity_subject=:actorSubject AND ur.person_id=:personId AND ur.role_code='POD_LEAD'
                AND ur.active_flag='Y' AND ur.effective_from<=TRUNC(SYSDATE)
                AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))
                AND rp.can_view='Y' AND rp.can_update='Y' AND rp.access_scope IN ('FULL','SCOPED','OWN')""",
                actorSubject=actor.subject, personId=actor.person_id)
            members = rows(connection, "SELECT assignment_id,person_id,role_in_pod,status,close_reason FROM pod_assignments WHERE request_id=:requestId ORDER BY person_id", requestId=request_id)
            if not linked or not any(m["person_id"] == actor.person_id and m["role_in_pod"] == "POD_LEAD"
                                     and m["status"] in ("CONFIRMED", "CLOSED") for m in members):
                raise ServiceError("FORBIDDEN", "Only the assigned POD Lead can close this project.", 403)
            if request[0]["status"] == "CLOSED":
                if all(m["status"] == "CLOSED" and m["close_reason"] == body.reason for m in members):
                    return {"request_id": request_id, "status": "CLOSED", "replayed": True}
                raise ServiceError("ALREADY_CLOSED", "Project is already closed. Refresh its history.", 409)
            if request[0]["status"] != "STAFFED" or request[0]["request_revision"] != body.request_revision:
                raise ServiceError("STALE_PROJECT", "Project changed. Refresh before closing.", 409)
            for pid in sorted({m["person_id"] for m in members}):
                rows(connection, "SELECT person_id FROM people WHERE person_id=:personId FOR UPDATE WAIT 5", personId=pid)
            execute(connection, """UPDATE pod_assignments SET status='CLOSED',closed_at=SYSTIMESTAMP,close_reason=:reasonText
                WHERE request_id=:requestId AND status='CONFIRMED'""", {"requestId": request_id, "reasonText": body.reason})
            # Keep the full original schedule. Shared capacity/calendar queries
            # retain dates through closed_at in each assignment's policy timezone,
            # releasing only later dates. The assignment update trigger bumps
            # each person's workload_version while the sorted person locks hold.
            execute(connection, "UPDATE requests SET status='CLOSED',agent_enabled='N',updated_by=:actorSubject,updated_at=SYSTIMESTAMP WHERE request_id=:requestId",
                    {"requestId": request_id, "actorSubject": actor.subject})
            execute(connection, """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,correlation_id,after_state_json,reason)
                VALUES(:auditId,'REQUEST',:requestId,'PROJECT_CLOSED',:actorSubject,:correlationId,:afterJson,:reasonText)""",
                {"auditId": uuid4().hex, "requestId": request_id, "actorSubject": actor.subject, "correlationId": uuid4().hex,
                 "afterJson": json_text({"status": "CLOSED", "assignment_ids": [m["assignment_id"] for m in members],
                     "capacity_rule": "PRESERVE_THROUGH_CLOSURE_DAY_RELEASE_LATER",
                     "closure_date_basis": "ASSIGNMENT_POLICY_TIMEZONE",
                     "workload_basis": "PLANNED_HOURS"}), "reasonText": body.reason}, ("afterJson",))
            return {"request_id": request_id, "status": "CLOSED", "replayed": False}
