"""Oracle job/proposal command handlers. Never provided to the language model as tools."""
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from app.agent_budget import budget_counters, model_call_limits, reserve_call
from app.engine_version import (
    ENGINE_VERSION,
    PROMPT_VERSION,
    VALIDATOR_VERSION,
    new_checkpoint,
    validate_checkpoint_state,
    validate_execution_checkpoint,
)
from app.errors import ServiceError
from app.evidence import collect_evidence
from app.planning import EvidenceBundle, json_text
from app.rules import validate_pod
from app.storage import document, load_policy, rows
from app.policy_admin import active_policy_version, require_current_policy

TERMINAL = {"NEEDS_INFORMATION", "READY_FOR_REVIEW", "NO_FEASIBLE_POD", "FAILED", "SUPERSEDED", "CANCELLED"}


class LeaseLost(ServiceError):
    def __init__(self):
        super().__init__("LEASE_LOST", "Execution is no longer owned by this worker.", 409)


@dataclass
class Job:
    execution_id: str
    request_id: str
    request_revision: int
    policy_version: str
    created_by: str
    token: str
    checkpoint: dict
    evidence: EvidenceBundle | None = None


def execute(connection, sql, binds=None, clobs=()):
    with connection.cursor() as cursor:
        if clobs:
            import oracledb
            cursor.setinputsizes(**{key: oracledb.DB_TYPE_CLOB for key in clobs})
        cursor.execute(sql, binds or {})
        return cursor.rowcount


def runtime_enabled(connection):
    result = rows(connection, "SELECT agents_enabled FROM staffing_runtime WHERE runtime_id=1")
    return len(result) == 1 and result[0]["agents_enabled"] == "Y"


def assert_captain(connection, subject, person_id):
    permitted = rows(connection, """SELECT p.person_id FROM app_user_roles ur
        JOIN people p ON p.person_id=ur.person_id AND p.active_flag='Y'
        JOIN app_roles ar ON ar.role_code=ur.role_code AND ar.active_flag='Y'
        JOIN role_permissions rp ON rp.role_code=ar.role_code AND rp.resource_code='AGENT_EXECUTION'
        WHERE ur.identity_subject=:identitySubject AND ur.person_id=:captainId
        AND ur.role_code='POD_CAPTAIN' AND ur.active_flag='Y'
        AND ur.effective_from<=TRUNC(SYSDATE) AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))
        AND rp.can_view='Y' AND rp.can_create='Y' AND rp.access_scope IN ('FULL','OWN','SCOPED')
    """, identitySubject=subject, captainId=person_id)
    if len(permitted) != 1:
        raise ServiceError("FORBIDDEN", "An active responsible Captain with agent-run permission is required.", 403)


class ExecutionStore:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def require_enabled(self, connection):
        if not self.settings.staffing_worker_enabled or not runtime_enabled(connection):
            raise ServiceError("AGENTS_DISABLED", "Staffing execution is not enabled on the server and database.", 503)

    def enqueue(self, request_id, subject, person_id, idempotency_key, automatic=False):
        with self.database.write() as connection:
            self.require_enabled(connection)
            current_policy = active_policy_version(connection, lock=True)
            request_rows = rows(connection, """SELECT request_revision,responsible_captain_id,status,agent_enabled
                FROM requests WHERE request_id=:requestId FOR UPDATE WAIT 5""", requestId=request_id)
            if len(request_rows) != 1:
                raise ServiceError("REQUEST_NOT_FOUND", "Staffing request not found.", 404)
            request = request_rows[0]
            if person_id != request["responsible_captain_id"]:
                raise ServiceError("FORBIDDEN", "This request belongs to another Captain.", 403)
            assert_captain(connection, subject, person_id)
            if automatic and request["agent_enabled"] != "Y":
                return None
            key = hashlib.sha256(f"{subject}|{idempotency_key}".encode()).hexdigest()
            prior = rows(connection, "SELECT execution_id,request_id,request_revision,status FROM agent_executions WHERE idempotency_key=:idemKey", idemKey=key)
            if prior:
                if prior[0]["request_id"] != request_id:
                    raise ServiceError("IDEMPOTENCY_CONFLICT", "This key belongs to another request.", 409)
                return prior[0]
            if request["status"] not in ("NEEDS_RECOMMENDATION", "IN_REVIEW"):
                raise ServiceError("REQUEST_NOT_RUNNABLE", "Only open unstaffed requests can be evaluated.", 409)
            from app.manual_store import pending_manual
            if pending_manual(connection, request_id, request['request_revision']):
                raise ServiceError('MANUAL_DRAFT_ACTIVE', 'Review or discard the manual draft before running fitment.', 409)
            active = rows(connection, """SELECT execution_id,request_id,request_revision,status FROM agent_executions
                WHERE request_id=:requestId AND request_revision=:requestRevision AND status IN ('QUEUED','RUNNING')""",
                requestId=request_id, requestRevision=request["request_revision"])
            if active:
                return active[0]
            policy = load_policy(connection, current_policy)
            model_call_limits(policy.maximum_agent_steps)
            if self.settings.backend_env == "production":
                policy.require_published()
            execution_id = "RUN-" + uuid4().hex
            envelope = {"format_version": 1, "request_id": request_id, "revision": request["request_revision"],
                        "responsible_captain_id": person_id, "policy": policy.model_dump(mode="json")}
            # An incomplete request still gets a durable information-needed outcome from the worker.
            execute(connection, """INSERT INTO agent_executions(execution_id,request_id,request_revision,policy_version,
                idempotency_key,request_snapshot_json,created_by,model_id,prompt_version)
                VALUES(:executionId,:requestId,:requestRevision,:policyVersion,:idemKey,:requestJson,:actorSubject,:modelId,:promptVersion)""",
                {"executionId": execution_id, "requestId": request_id, "requestRevision": request["request_revision"],
                 "policyVersion": policy.version, "idemKey": key, "requestJson": json_text(envelope),
                 "actorSubject": subject, "modelId": self.settings.oci_genai_model_id,
                 "promptVersion": PROMPT_VERSION}, ("requestJson",))
            self.event(connection, execution_id, "queue", "QUEUED", "Staffing execution queued.")
            return {"execution_id": execution_id, "request_id": request_id,
                    "request_revision": request["request_revision"], "status": "QUEUED"}

    def discover(self):
        """Durable polling intake for opted-in requests, including new revisions after edits."""
        with self.database.read() as connection:
            self.require_enabled(connection)
            pending = rows(connection, """SELECT r.request_id,r.request_revision,r.responsible_captain_id,r.created_by
                FROM requests r WHERE r.agent_enabled='Y' AND r.responsible_captain_id IS NOT NULL
                AND r.status IN ('NEEDS_RECOMMENDATION','IN_REVIEW')
                AND NOT EXISTS (SELECT 1 FROM agent_executions e WHERE e.request_id=r.request_id
                    AND e.request_revision=r.request_revision)
                ORDER BY r.created_at,r.request_id FETCH FIRST 20 ROWS ONLY""")
        for request in pending:
            with self.database.read() as connection:
                subjects = rows(connection, """SELECT DISTINCT identity_subject FROM app_user_roles
                    WHERE person_id=:personId AND role_code='POD_CAPTAIN' AND active_flag='Y'
                    AND effective_from<=TRUNC(SYSDATE) AND (effective_to IS NULL OR effective_to>=TRUNC(SYSDATE))""",
                    personId=request["responsible_captain_id"])
            valid_subjects = {row["identity_subject"] for row in subjects}
            subject = request.get("created_by") if request.get("created_by") in valid_subjects else (
                next(iter(valid_subjects)) if len(valid_subjects) == 1 else None)
            if subject is None:
                continue  # Never infer identities from a name or the demo dropdown.
            try:
                self.enqueue(request["request_id"], subject, request["responsible_captain_id"],
                             f"automatic:{request['request_id']}:{request['request_revision']}", automatic=True)
            except ServiceError as error:
                if error.code not in ("FORBIDDEN", "REQUEST_NOT_RUNNABLE", "MANUAL_DRAFT_ACTIVE"):
                    raise

    def claim(self, owner):
        with self.database.write() as connection:
            self.require_enabled(connection)
            with connection.cursor() as cursor:
                # Oracle forbids combining FETCH FIRST with FOR UPDATE. Fetch one locked row instead.
                cursor.arraysize = 1
                cursor.prefetchrows = 0
                cursor.execute("""SELECT execution_id FROM agent_executions
                    WHERE (status='QUEUED' AND available_at<=SYSTIMESTAMP)
                       OR (status='RUNNING' AND lease_expires_at<SYSTIMESTAMP)
                    ORDER BY available_at,created_at,execution_id FOR UPDATE SKIP LOCKED""")
                chosen = cursor.fetchone()
            if not chosen:
                return None
            record = rows(connection, "SELECT * FROM agent_executions WHERE execution_id=:executionId", executionId=chosen[0])[0]
            if record["attempt_count"] >= record["max_attempts"]:
                self.terminal(connection, chosen[0], "FAILED", "RETRY_EXHAUSTED", "Execution retry limit reached.")
                return None
            token = uuid4().hex
            execute(connection, """UPDATE agent_executions SET status='RUNNING',attempt_count=attempt_count+1,
                lease_owner=:ownerName,lease_token=:leaseToken,lease_expires_at=SYSTIMESTAMP+NUMTODSINTERVAL(:leaseSeconds,'SECOND'),
                heartbeat_at=SYSTIMESTAMP WHERE execution_id=:executionId""",
                {"ownerName": owner, "leaseToken": token, "leaseSeconds": self.settings.staffing_lease_seconds, "executionId": chosen[0]})
            try:
                checkpoint = document(record["checkpoint_json"]) if record["checkpoint_json"] else new_checkpoint()
                validate_execution_checkpoint(checkpoint, record["prompt_version"], record["model_id"],
                                              self.settings.oci_genai_model_id)
                bundle = EvidenceBundle.model_validate(document(record["evidence_snapshot_json"])) if record["evidence_snapshot_json"] else None
                if ("analysis" in checkpoint or "search" in checkpoint or "selection" in checkpoint) and bundle is None:
                    raise ValueError("Missing evidence snapshot")
            except (ValueError, TypeError, KeyError):
                self.terminal(connection, chosen[0], "FAILED", "CHECKPOINT_VERSION", "Checkpoint or execution configuration is incompatible; create a new run.")
                return None
            self.event(connection, chosen[0], "worker", "RUNNING", "Worker acquired execution lease.")
            return Job(chosen[0], record["request_id"], record["request_revision"], record["policy_version"],
                       record["created_by"], token, checkpoint, bundle)

    def lock_job(self, connection, job):
        record = rows(connection, """SELECT lease_token,status,attempt_count,max_attempts,
            CASE WHEN lease_expires_at>SYSTIMESTAMP THEN 1 ELSE 0 END AS lease_valid,
            checkpoint_json,request_snapshot_json FROM agent_executions WHERE execution_id=:executionId FOR UPDATE WAIT 5""",
            executionId=job.execution_id)
        if not record or record[0]["status"] != "RUNNING" or record[0]["lease_token"] != job.token or record[0]["lease_valid"] != 1:
            raise LeaseLost()
        self.require_enabled(connection)
        return record[0]

    def save(self, job, stage, summary, bundle=None, reserve=None):
        with self.database.write() as connection:
            record = self.lock_job(connection, job)
            try:
                previous = document(record["checkpoint_json"]) if record["checkpoint_json"] else new_checkpoint()
                validate_checkpoint_state(previous)
                # Every save restores all counters from committed state, not resume/caller data.
                checkpoint = {**job.checkpoint, **budget_counters(previous)}
                validate_checkpoint_state(checkpoint)
                if reserve is not None:
                    if job.evidence is None:
                        raise ServiceError("INVALID_AGENT_BUDGET", "Agent evidence is required before a reservation.", 409)
                    checkpoint.update(reserve_call(previous, stage, reserve, job.evidence.policy.maximum_agent_steps))
            except (ValueError, TypeError, KeyError) as error:
                raise ServiceError("CHECKPOINT_VERSION",
                                   "Checkpoint budget or engine is incompatible; create a new run.", 409) from error
            binds = {"checkpointJson": json_text(checkpoint), "executionId": job.execution_id,
                     "leaseSeconds": self.settings.staffing_lease_seconds}
            execute(connection, """UPDATE agent_executions SET checkpoint_json=:checkpointJson,
                checkpoint_version=checkpoint_version+1,heartbeat_at=SYSTIMESTAMP,
                lease_expires_at=SYSTIMESTAMP+NUMTODSINTERVAL(:leaseSeconds,'SECOND') WHERE execution_id=:executionId""",
                binds, ("checkpointJson",))
            if bundle is not None:
                execute(connection, "UPDATE agent_executions SET evidence_snapshot_json=:evidenceJson WHERE execution_id=:executionId",
                    {"evidenceJson": json_text(bundle), "executionId": job.execution_id}, ("evidenceJson",))
            self.event(connection, job.execution_id, stage, "RUNNING", summary)
        # A failed write/commit must not grant an uncommitted reservation in memory.
        job.checkpoint = checkpoint

    def load_evidence(self, job):
        with self.database.read() as connection:
            self.require_enabled(connection)
            require_current_policy(connection, job.policy_version)
            request = rows(connection, "SELECT request_revision,responsible_captain_id,status FROM requests WHERE request_id=:requestId", requestId=job.request_id)[0]
            if request["request_revision"] != job.request_revision or request["status"] not in ("NEEDS_RECOMMENDATION", "IN_REVIEW"):
                raise ServiceError("STALE_INPUTS", "Request changed after execution was queued.", 409)
            assert_captain(connection, job.created_by, request["responsible_captain_id"])
            job_row = rows(connection, "SELECT request_snapshot_json FROM agent_executions WHERE execution_id=:executionId", executionId=job.execution_id)[0]
            envelope = document(job_row["request_snapshot_json"])
            bundle = collect_evidence(connection, job.request_id, job.policy_version, self.settings.staffing_max_candidates)
            if bundle.policy.model_dump(mode="json") != envelope["policy"]:
                raise ServiceError("STALE_INPUTS", "Policy changed after execution was queued; start a new run.", 409)
            if self.settings.backend_env == "production":
                bundle.policy.require_published()
            return bundle

    def event(self, connection, execution_id, stage, status, summary):
        execute(connection, """INSERT INTO agent_execution_events(execution_id,event_sequence,stage,status,summary)
            SELECT :executionId,NVL(MAX(event_sequence),0)+1,:stageName,:eventStatus,:eventSummary
            FROM agent_execution_events WHERE execution_id=:executionId""",
            {"executionId": execution_id, "stageName": stage, "eventStatus": status, "eventSummary": summary[:2000]})

    def terminal(self, connection, execution_id, status, code, summary):
        if status not in TERMINAL:
            raise ValueError("Invalid terminal execution state")
        execute(connection, """UPDATE agent_executions SET status=:newStatus,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
            finished_at=SYSTIMESTAMP,last_error_code=:errorCode,last_error_summary=:errorSummary WHERE execution_id=:executionId""",
            {"newStatus": status, "errorCode": code, "errorSummary": summary, "executionId": execution_id})
        self.event(connection, execution_id, "result", status, summary)

    def finish(self, job, status, code, summary):
        with self.database.write() as connection:
            self.lock_job(connection, job)
            self.terminal(connection, job.execution_id, status, code, summary)

    def retry(self, job):
        with self.database.write() as connection:
            row = self.lock_job(connection, job)
            if row["attempt_count"] >= row["max_attempts"]:
                self.terminal(connection, job.execution_id, "FAILED", "RETRY_EXHAUSTED", "Dependency retries exhausted; review execution.")
            else:
                execute(connection, """UPDATE agent_executions SET status='QUEUED',lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                    available_at=SYSTIMESTAMP+NUMTODSINTERVAL(:delaySeconds,'SECOND'),last_error_code='DEPENDENCY_UNAVAILABLE',
                    last_error_summary='Dependency call could not be completed; retry scheduled.' WHERE execution_id=:executionId""",
                    {"delaySeconds": min(60, 5 * 2 ** row["attempt_count"]), "executionId": job.execution_id})
                self.event(connection, job.execution_id, "retry", "QUEUED", "Dependency unavailable; bounded retry scheduled.")

    def publish(self, job, option, selection):
        from app.agents.grounding import checked_plan_scores, grounded_plan_rationale
        from app.agents.staffing import required_plan_references
        if (selection.plan_id != option.plan_id
            or not set(selection.evidence_refs) <= job.evidence.reference_ids()
            or not required_plan_references(job.evidence, option.proposal) <= set(selection.evidence_refs)):
            raise ServiceError("INVALID_CHECKPOINT", "The selected plan is missing its required evidence references.", 409)
        proposal = option.proposal.model_copy(update={
            "evidence_refs": tuple(sorted(set(option.proposal.evidence_refs) | set(selection.evidence_refs)))})
        with self.database.write() as connection:
            require_current_policy(connection, job.policy_version, lock=True)
            # Shared lock order: control -> request -> policy -> people -> execution -> proposal.
            request_row = rows(connection, "SELECT request_revision,responsible_captain_id,status FROM requests WHERE request_id=:requestId FOR UPDATE WAIT 5", requestId=job.request_id)[0]
            rows(connection, "SELECT policy_version FROM staffing_policies WHERE policy_version=:policyVersion FOR UPDATE WAIT 5", policyVersion=job.policy_version)
            for member in sorted(proposal.members, key=lambda m: m.person_id):
                rows(connection, "SELECT person_id FROM people WHERE person_id=:personId FOR UPDATE WAIT 5", personId=member.person_id)
            self.lock_job(connection, job)
            assert_captain(connection, job.created_by, request_row["responsible_captain_id"])
            if request_row["status"] not in ("NEEDS_RECOMMENDATION", "IN_REVIEW") or request_row["request_revision"] != job.request_revision:
                raise ServiceError("STALE_INPUTS", "Request changed before proposal publication.", 409)
            fresh = collect_evidence(connection, job.request_id, job.policy_version, self.settings.staffing_max_candidates)
            if fresh.request != job.evidence.request or fresh.policy != job.evidence.policy or fresh.catalogue != job.evidence.catalogue:
                raise ServiceError("STALE_INPUTS", "Request, catalogue or policy changed during execution.", 409)
            for member in proposal.members:
                pid = member.person_id
                before = next(p for p in job.evidence.candidates if p.person_id == pid)
                after = next((p for p in fresh.candidates if p.person_id == pid), None)
                if before != after or fresh.versions.get(pid) != job.evidence.versions.get(pid) or fresh.ledgers.get(pid) != job.evidence.ledgers.get(pid):
                    raise ServiceError("STALE_INPUTS", "Selected candidate evidence or workload changed; rerun fitment.", 409)
            if validate_pod(fresh.request, proposal, fresh.candidates, fresh.ledgers, fresh.policy, catalogue=fresh.catalogue):
                raise ServiceError("INVALID_PROPOSAL", "The final deterministic validation rejected the proposal.", 409)
            # The model selects an existing plan, but never supplies authoritative
            # arithmetic. Also fence tampered/old checkpoint metrics before writes.
            scores = checked_plan_scores(fresh, option)
            proposal = proposal.model_copy(update={"rationale": grounded_plan_rationale(fresh, proposal, scores)})
            algorithms = {facts["scheduling_algorithm"] for facts in scores.values()}
            if len(algorithms) != 1:
                raise ServiceError("INVALID_CHECKPOINT", "Selected schedules use incompatible algorithms.", 409)
            scheduling_algorithm = next(iter(algorithms))
            if self.settings.backend_env == "production":
                fresh.policy.require_published()
            version = rows(connection, "SELECT NVL(MAX(proposal_version),0)+1 AS next_version FROM pod_proposals WHERE request_id=:requestId", requestId=job.request_id)[0]["next_version"]
            proposal_id = "PP" + uuid4().hex[:28]
            execute(connection, "UPDATE pod_proposals SET status='SUPERSEDED' WHERE request_id=:requestId AND status='READY_FOR_REVIEW'", {"requestId": job.request_id})
            execute(connection, """INSERT INTO pod_proposals(proposal_id,request_id,proposal_version,request_revision,execution_id,policy_version,
                responsible_captain_id,starts_on,ends_on,total_hours,lead_count,member_count,rationale,evidence_refs_json,validation_json)
                VALUES(:proposalId,:requestId,:proposalVersion,:requestRevision,:executionId,:policyVersion,:captainId,
                :startDay,:endDay,:totalHours,:leadCount,:memberCount,:rationaleText,:referencesJson,:validationJson)""",
                {"proposalId": proposal_id, "requestId": job.request_id, "proposalVersion": version, "requestRevision": job.request_revision,
                 "executionId": job.execution_id, "policyVersion": job.policy_version, "captainId": fresh.request.responsible_captain_id,
                 "startDay": fresh.request.starts_on, "endDay": fresh.request.ends_on, "totalHours": fresh.request.total_hours,
                 "leadCount": fresh.request.lead_count, "memberCount": fresh.request.member_count, "rationaleText": proposal.rationale,
                 "referencesJson": json_text(list(proposal.evidence_refs)),
                 "validationJson": json_text({"issues": [], "policy_version": job.policy_version,
                    "validator": VALIDATOR_VERSION, "engine_version": ENGINE_VERSION,
                    "prompt_version": PROMPT_VERSION, "scheduling_algorithm": scheduling_algorithm,
                    "plan_id": option.plan_id})},
                ("rationaleText", "referencesJson", "validationJson"))
            for rank, member in enumerate(proposal.members, 1):
                person = next(p for p in fresh.candidates if p.person_id == member.person_id)
                execute(connection, """INSERT INTO pod_proposal_members(proposal_id,person_id,role_in_pod,selected_flag,planned_hours,score,
                    rank_position,responsibilities,deliverable_ids_json,evidence_json,factors_json,person_skills_version,person_workload_version)
                    VALUES(:proposalId,:personId,:podRole,'Y',:plannedHours,:scoreValue,:rankPosition,:responsibilities,
                    :deliverablesJson,:evidenceJson,:factorsJson,:skillsVersion,:workloadVersion)""",
                    {"proposalId": proposal_id, "personId": member.person_id, "podRole": member.role.value, "plannedHours": member.hours,
                     "scoreValue": Decimal(str(scores[member.person_id]["score"])), "rankPosition": rank, "responsibilities": member.responsibilities,
                     "deliverablesJson": json_text(list(member.deliverable_ids)), "evidenceJson": json_text(person),
                     "factorsJson": json_text(scores[member.person_id]), "skillsVersion": fresh.versions[member.person_id]["skills_version"],
                     "workloadVersion": fresh.versions[member.person_id]["workload_version"]}, ("deliverablesJson", "evidenceJson", "factorsJson"))
            execute(connection, "UPDATE pod_proposals SET status='READY_FOR_REVIEW' WHERE proposal_id=:proposalId", {"proposalId": proposal_id})
            from app.selections import save_initial_review
            save_initial_review(connection, proposal_id, fresh, option, self.settings.staffing_search_limit)
            execute(connection, """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,
                correlation_id,after_state_json) VALUES(:auditId,'POD_PROPOSAL',:proposalId,'PROPOSED',:actorSubject,:executionId,:afterJson)""",
                {"auditId": uuid4().hex, "proposalId": proposal_id, "actorSubject": job.created_by,
                 "executionId": job.execution_id, "afterJson": json_text({"proposal_id": proposal_id, "version": version, "status": "READY_FOR_REVIEW"})}, ("afterJson",))
            # Do not update REQUESTS.status here: its revision trigger would immediately stale this proposal.
            self.terminal(connection, job.execution_id, "READY_FOR_REVIEW", None, "POD proposal is ready for Captain review.")
            return proposal_id

    @staticmethod
    def authorize_read(actor, captain_id):
        # Administrator FULL access is explicit. A Captain can read only their own requests.
        if "SYSTEM_ADMINISTRATOR" in actor.roles:
            permission = actor.require("AGENT_EXECUTION", "view", "SYSTEM_ADMINISTRATOR")
            if permission.scope == "FULL":
                return
        actor.require("AGENT_EXECUTION", "view", "POD_CAPTAIN")
        if actor.person_id != captain_id:
            raise ServiceError("FORBIDDEN", "This staffing record belongs to another Captain.", 403)

    def get_execution(self, execution_id, actor, after=0):
        with self.database.read() as connection:
            records = rows(connection, """SELECT e.execution_id,e.request_id,e.request_revision,e.policy_version,e.status,
                e.attempt_count,e.last_error_code,e.last_error_summary,e.created_at,e.finished_at,e.checkpoint_json,
                r.responsible_captain_id FROM agent_executions e JOIN requests r ON r.request_id=e.request_id
                WHERE e.execution_id=:executionId""", executionId=execution_id)
            if not records:
                raise ServiceError("EXECUTION_NOT_FOUND", "Staffing execution not found.", 404)
            record = records[0]
            self.authorize_read(actor, record.pop("responsible_captain_id"))
            stored_checkpoint = record.pop("checkpoint_json")
            checkpoint = document(stored_checkpoint) if stored_checkpoint else {}
            record["clarification_questions"] = checkpoint.get("analysis", {}).get("clarification_questions", [])
            record["events"] = rows(connection, """SELECT event_sequence,stage,status,summary,created_at
                FROM agent_execution_events WHERE execution_id=:executionId AND event_sequence>:afterSequence
                ORDER BY event_sequence FETCH FIRST 100 ROWS ONLY""", executionId=execution_id, afterSequence=after)
            record["next_after"] = record["events"][-1]["event_sequence"] if record["events"] else after
            record["proposals"] = rows(connection, """SELECT proposal_id,proposal_version,status FROM pod_proposals
                WHERE execution_id=:executionId ORDER BY proposal_version""", executionId=execution_id)
            return record

    def visible_requests(self, actor):
        actor.require("AGENT_EXECUTION", "view")
        full_admin = any(p.role == "SYSTEM_ADMINISTRATOR" and p.role in actor.roles and p.resource == "AGENT_EXECUTION"
                         and p.scope == "FULL" and "view" in p.actions for p in actor.permissions)
        if not full_admin:
            actor.require("AGENT_EXECUTION", "view", "POD_CAPTAIN")
        with self.database.read() as connection:
            return rows(connection, """SELECT request_id,title,status,responsible_captain_id,request_revision FROM requests
                WHERE (:fullAdmin=1 OR responsible_captain_id=:personId) ORDER BY created_at DESC,request_id""",
                fullAdmin=1 if full_admin else 0, personId=actor.person_id)

    def latest(self, request_id, actor):
        with self.database.read() as connection:
            requests = rows(connection, "SELECT responsible_captain_id FROM requests WHERE request_id=:requestId", requestId=request_id)
            if not requests:
                raise ServiceError("REQUEST_NOT_FOUND", "Request not found.", 404)
            self.authorize_read(actor, requests[0]["responsible_captain_id"])
            found = rows(connection, "SELECT execution_id FROM agent_executions WHERE request_id=:requestId ORDER BY created_at DESC,execution_id DESC FETCH FIRST 1 ROW ONLY", requestId=request_id)
        return self.get_execution(found[0]["execution_id"], actor) if found else None

    def get_proposal(self, proposal_id, actor):
        with self.database.read() as connection:
            records = rows(connection, """SELECT p.proposal_id,p.request_id,p.proposal_version,p.request_revision,p.execution_id,
                p.policy_version,p.status,p.starts_on,p.ends_on,p.total_hours,p.lead_count,p.member_count,p.rationale,p.origin_type AS origin,
                p.evidence_refs_json,p.validation_json,r.responsible_captain_id,
                CASE WHEN p.status IN ('APPROVED','REJECTED') OR p.request_revision=r.request_revision THEN 'N' ELSE 'Y' END AS stale
                FROM pod_proposals p JOIN requests r ON r.request_id=p.request_id WHERE p.proposal_id=:proposalId""", proposalId=proposal_id)
            if not records:
                raise ServiceError("PROPOSAL_NOT_FOUND", "Staffing proposal not found.", 404)
            record = records[0]
            self.authorize_read(actor, record.pop("responsible_captain_id"))
            if record['status'] == 'READY_FOR_REVIEW' and record['policy_version'] != active_policy_version(connection):
                record['stale'] = 'Y'
                record['stale_reason'] = 'Utilization policy changed. Re-run fitment before approval.'
            if hasattr(record["rationale"], "read"):
                record["rationale"] = record["rationale"].read()
            for key in ("evidence_refs_json", "validation_json"):
                record[key.removesuffix("_json")] = document(record.pop(key))
            members = rows(connection, """SELECT m.person_id,p.full_name,m.role_in_pod,m.planned_hours,m.score,m.rank_position,
                m.responsibilities,m.deliverable_ids_json,m.factors_json FROM pod_proposal_members m
                JOIN people p ON p.person_id=m.person_id WHERE m.proposal_id=:proposalId AND m.selected_flag='Y'
                ORDER BY m.rank_position""", proposalId=proposal_id)
            for member in members:
                for key in ("deliverable_ids_json", "factors_json"):
                    member[key.removesuffix("_json")] = document(member.pop(key))
                member['source'] = record['validation'].get('selection_sources', {}).get(member['person_id'])
            record["members"] = members
            from app.selections import attach_review
            attach_review(connection, record)
            return record

    def latest_proposal(self, request_id, actor):
        with self.database.read() as connection:
            found = rows(connection, 'SELECT responsible_captain_id FROM requests WHERE request_id=:requestId', requestId=request_id)
            if not found:
                raise ServiceError('REQUEST_NOT_FOUND', 'Request not found.', 404)
            self.authorize_read(actor, found[0]['responsible_captain_id'])
            proposals = rows(connection, 'SELECT proposal_id FROM pod_proposals WHERE request_id=:requestId ORDER BY proposal_version DESC FETCH FIRST 1 ROW ONLY', requestId=request_id)
        return self.get_proposal(proposals[0]['proposal_id'], actor) if proposals else None
