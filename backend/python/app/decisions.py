"""Captain decisions and final assignments in one serialized Oracle transaction."""
import hashlib
from app.policy_admin import active_policy_version, require_current_policy
from uuid import uuid4

from app.capacity import calculate_capacity
from app.contracts import Proposal, ProposedMember
from app.errors import ServiceError
from app.evidence import collect_evidence
from app.execution_store import execute
from app.planning import EvidenceBundle, json_text
from app.rules import member_schedule, validate_pod
from app.storage import document, rows
from app.notifications import prepare_assignment_notice


def published_member(record, policy):
    """Rehydrate frozen proposal effort; a v2 schedule never falls back to spreading."""
    try:
        factors = document(record["factors_json"]) if record.get("factors_json") is not None else {}
        if not isinstance(factors, dict):
            raise ValueError("Invalid member factors")
        if policy.scheduling is not None:
            if factors.get("scheduling_algorithm") != policy.scheduling.algorithm:
                raise ValueError("Missing or inconsistent published scheduling algorithm")
            schedule = factors.get("daily_schedule")
            if not isinstance(schedule, list) or not schedule:
                raise ValueError("Missing published daily schedule")
        else:
            # Old policies retain their original equal-weekday semantics.
            schedule = ()
        return ProposedMember(person_id=record["person_id"], role=record["role_in_pod"],
            hours=record["planned_hours"], responsibilities=record["responsibilities"],
            deliverable_ids=document(record["deliverable_ids_json"]), daily_schedule=schedule)
    except (KeyError, TypeError, ValueError) as error:
        raise ServiceError("INVALID_PUBLISHED_SCHEDULE", "The saved POD schedule is incomplete or invalid. Run fitment again.", 409) from error


class DecisionStore:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    @staticmethod
    def authorize(connection, actor, captain_id):
        # Re-resolve current permissions inside the write transaction; neither dropdown nor body grants access.
        if actor.person_id != captain_id:
            raise ServiceError("FORBIDDEN", "Only this request's responsible Captain can decide.", 403)
        allowed = rows(connection, """SELECT ur.person_id FROM app_user_roles ur
            JOIN people p ON p.person_id=ur.person_id AND p.active_flag='Y'
            JOIN app_roles ar ON ar.role_code=ur.role_code AND ar.active_flag='Y'
            JOIN role_permissions rp ON rp.role_code=ar.role_code AND rp.resource_code='AI_FITMENT'
            WHERE ur.identity_subject=:actorSubject AND ur.person_id=:captainId AND ur.role_code='POD_CAPTAIN'
            AND ur.active_flag='Y' AND ur.effective_from<=TRUNC(SYSDATE)
            AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))
            AND rp.can_view='Y' AND rp.can_approve='Y' AND rp.access_scope IN ('FULL','OWN','SCOPED')""",
            actorSubject=actor.subject, captainId=captain_id)
        if len(allowed) != 1:
            raise ServiceError("FORBIDDEN", "Current Captain approval permission is required.", 403)

    def decide(self, actor, decision):
        if not self.settings.staffing_decisions_enabled:
            raise ServiceError("DECISIONS_DISABLED", "Captain decisions are not enabled on this backend.", 503)
        actor.require("AI_FITMENT", "approve", "POD_CAPTAIN")
        key = hashlib.sha256(f"{actor.subject}|{decision.idempotency_key}".encode()).hexdigest()
        with self.database.write() as connection:
            # Serialize activation with approval: either approval commits under
            # the old active policy first, or the new policy fences this proposal.
            active_policy_version(connection, lock=True)
            initial = rows(connection, "SELECT request_id,policy_version FROM pod_proposals WHERE proposal_id=:proposalId", proposalId=decision.proposal_id)
            if not initial:
                raise ServiceError("PROPOSAL_NOT_FOUND", "Proposal not found.", 404)
            request_id, policy_version = initial[0]["request_id"], initial[0]["policy_version"]
            # Same ordering as publication. Lock all selected people before reading any current capacity.
            request = rows(connection, "SELECT request_revision,responsible_captain_id,status FROM requests WHERE request_id=:requestId FOR UPDATE WAIT 5", requestId=request_id)[0]
            self.authorize(connection, actor, request["responsible_captain_id"])
            rows(connection, "SELECT policy_version FROM staffing_policies WHERE policy_version=:policyVersion FOR UPDATE WAIT 5", policyVersion=policy_version)
            members = rows(connection, "SELECT * FROM pod_proposal_members WHERE proposal_id=:proposalId AND selected_flag='Y' ORDER BY person_id", proposalId=decision.proposal_id)
            for member in members:
                rows(connection, "SELECT person_id FROM people WHERE person_id=:personId FOR UPDATE WAIT 5", personId=member["person_id"])
            proposal = rows(connection, "SELECT * FROM pod_proposals WHERE proposal_id=:proposalId FOR UPDATE WAIT 5", proposalId=decision.proposal_id)[0]
            prior = rows(connection, "SELECT d.*,p.proposal_version FROM approval_decisions d JOIN pod_proposals p ON p.proposal_id=d.proposal_id WHERE d.idempotency_key=:idemKey", idemKey=key)
            if prior:
                old = prior[0]
                if (old["proposal_id"] != decision.proposal_id or old["action_type"] != decision.action
                    or old["proposal_version"] != decision.proposal_version or (old["reason"] or "") != (decision.reason or "")):
                    raise ServiceError("IDEMPOTENCY_CONFLICT", "This decision key was already used for a different decision.", 409)
                return {"decision_id": old["decision_id"], "proposal_id": decision.proposal_id, "status": old["action_type"], "replayed": True}
            if proposal["status"] != "READY_FOR_REVIEW":
                raise ServiceError("ALREADY_DECIDED", "This proposal is no longer awaiting a decision. Refresh the review.", 409)
            if (proposal["proposal_version"] != decision.proposal_version or proposal["request_revision"] != request["request_revision"]
                or proposal["responsible_captain_id"] != request["responsible_captain_id"]
                or request["status"] not in ("NEEDS_RECOMMENDATION", "IN_REVIEW")):
                raise ServiceError("STALE_PROPOSAL", "The request or proposal changed. Refresh and run fitment again.", 409)
            pod = None
            validation = {}
            if decision.action == "APPROVED":
                require_current_policy(connection, policy_version)
                fresh = collect_evidence(connection, request_id, policy_version, self.settings.staffing_max_candidates)
                fresh.policy.require_published()
                snapshot = rows(connection, "SELECT evidence_snapshot_json FROM agent_executions WHERE execution_id=:executionId", executionId=proposal["execution_id"])[0]
                saved = EvidenceBundle.model_validate(document(snapshot["evidence_snapshot_json"]))
                if fresh.request != saved.request or fresh.policy != saved.policy or fresh.catalogue != saved.catalogue:
                    raise ServiceError("STALE_PROPOSAL", "Request, catalogue or approved policy evidence changed; rerun fitment.", 409)
                for member in members:
                    pid = member["person_id"]
                    before = next((p for p in saved.candidates if p.person_id == pid), None)
                    after = next((p for p in fresh.candidates if p.person_id == pid), None)
                    if before is None or before != after or fresh.versions.get(pid, {}).get("skills_version") != member["person_skills_version"]:
                        raise ServiceError("STALE_PROPOSAL", "Selected role or skill evidence changed; rerun fitment.", 409)
                rationale = proposal["rationale"].read() if hasattr(proposal["rationale"], "read") else proposal["rationale"]
                pod = Proposal(request_id=request_id, request_revision=request["request_revision"], policy_version=policy_version,
                    members=tuple(published_member(m, fresh.policy) for m in members),
                    rationale=rationale, evidence_refs=document(proposal["evidence_refs_json"]))
                if validate_pod(fresh.request, pod, fresh.candidates, fresh.ledgers, fresh.policy, catalogue=fresh.catalogue):
                    raise ServiceError("CAPACITY_OR_ELIGIBILITY_CHANGED", "The POD no longer meets current capacity or eligibility rules. Run fitment again.", 409)
                validation = {"policy_version": policy_version, "request_revision": request["request_revision"],
                    "person_versions": {m.person_id: fresh.versions[m.person_id] for m in pod.members},
                    "capacity": {m.person_id: calculate_capacity(fresh.ledgers[m.person_id], fresh.request.starts_on, fresh.request.ends_on,
                        member_schedule(m, fresh.request, fresh.policy), fresh.policy.maximum_allocation_pct,
                        allow_empty_weeks=fresh.policy.scheduling is not None).model_dump(mode="json")
                        for m in pod.members}}
                existing = rows(connection, "SELECT assignment_id FROM pod_assignments WHERE request_id=:requestId AND status='CONFIRMED'", requestId=request_id)
                if existing:
                    raise ServiceError("ALREADY_ASSIGNED", "This request already has a confirmed assignment.", 409)
            decision_id = "DC" + uuid4().hex[:28]
            execute(connection, """INSERT INTO approval_decisions(decision_id,proposal_id,request_id,captain_person_id,actor_subject,
                action_type,reason,idempotency_key) VALUES(:decisionId,:proposalId,:requestId,:captainId,:actorSubject,:actionType,:reasonText,:idemKey)""",
                {"decisionId": decision_id, "proposalId": decision.proposal_id, "requestId": request_id, "captainId": actor.person_id,
                 "actorSubject": actor.subject, "actionType": decision.action, "reasonText": decision.reason or None, "idemKey": key})
            execute(connection, "UPDATE pod_proposals SET status=:newStatus WHERE proposal_id=:proposalId",
                {"newStatus": decision.action, "proposalId": decision.proposal_id})
            assignments = []
            if pod:
                for member in pod.members:
                    assignment_id = "AS" + uuid4().hex[:28]
                    execute(connection, """INSERT INTO pod_assignments(assignment_id,request_id,proposal_id,person_id,role_in_pod,
                        decision_id,policy_version,starts_on,ends_on,assigned_hours)
                        VALUES(:assignmentId,:requestId,:proposalId,:personId,:podRole,:decisionId,:policyVersion,:startDay,:endDay,:assignedHours)""",
                        {"assignmentId": assignment_id, "requestId": request_id, "proposalId": decision.proposal_id, "personId": member.person_id,
                         "podRole": member.role.value, "decisionId": decision_id, "policyVersion": policy_version,
                         "startDay": fresh.request.starts_on, "endDay": fresh.request.ends_on, "assignedHours": member.hours})
                    for day in member_schedule(member, fresh.request, fresh.policy):
                        if day.hours:
                            execute(connection, "INSERT INTO assignment_days(assignment_id,person_id,work_date,assigned_hours) VALUES(:assignmentId,:personId,:workDay,:assignedHours)",
                                {"assignmentId": assignment_id, "personId": member.person_id, "workDay": day.day, "assignedHours": day.hours})
                    assignments.append(assignment_id)
                    prepare_assignment_notice(connection, decision_id, decision.proposal_id, request_id, member, assignment_id)
            # Do this last: the request trigger increments revision. History retains the decided input revision.
            execute(connection, "UPDATE requests SET status=:newStatus,updated_by=:actorSubject,updated_at=SYSTIMESTAMP WHERE request_id=:requestId",
                {"newStatus": "STAFFED" if pod else "NEEDS_RECOMMENDATION", "actorSubject": actor.subject, "requestId": request_id})
            execute(connection, """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,correlation_id,after_state_json,reason)
                VALUES(:auditId,'POD_PROPOSAL',:proposalId,:actionType,:actorSubject,:decisionId,:afterJson,:reasonText)""",
                {"auditId": uuid4().hex, "proposalId": decision.proposal_id, "actionType": decision.action, "actorSubject": actor.subject,
                 "decisionId": decision_id, "afterJson": json_text({"decision_id": decision_id, "assignments": assignments, "status": decision.action, "validation": validation}),
                 "reasonText": decision.reason or None}, ("afterJson",))
            return {"decision_id": decision_id, "proposal_id": decision.proposal_id, "status": decision.action, "assignment_ids": assignments, "replayed": False}
