"""Captain-owned manual previews and atomic decisions, independent of OCI."""
import hashlib
from typing import Literal
from uuid import uuid4

from pydantic import Field
from app.contracts import CaptainDecision, Contract, EntityId
from app.decisions import DecisionStore, commit_final_decision
from app.errors import ServiceError
from app.evidence import collect_evidence
from app.execution_store import execute
from app.manual_planning import ManualSlot, manual_plan
from app.planning import EvidenceBundle, PlanOption, json_text
from app.policy_admin import active_policy_version
from app.proposal_writer import write_proposal
from app.selections import evidence_hash, load_review
from app.storage import document, rows


class ManualPreviewInput(Contract):
    request_revision: int = Field(ge=1, strict=True)
    previous_draft_id: EntityId | None = None
    source_proposal_id: EntityId | None = None
    slots: tuple[ManualSlot, ...] = Field(min_length=1, max_length=25)
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')


class ManualDecisionInput(Contract):
    draft_id: EntityId
    action: Literal['APPROVED', 'REJECTED', 'DISCARDED']
    reason: str = Field(default='', max_length=2000)
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')


class ManualSnapshot(Contract):
    format_version: Literal[1] = 1
    option: PlanOption
    evidence: EvidenceBundle
    slots: tuple[ManualSlot, ...]
    evidence_hash: str
    names: dict[str, str]
    sources: dict[str, str]
    original_members: tuple[dict, ...] = ()
    source_proposal_id: EntityId | None = None
    source_selection_id: EntityId | None = None
    starts_on: str
    ends_on: str
    lead_count: int
    member_count: int


def latest_draft(connection, request_id):
    found = rows(connection, 'SELECT * FROM mvp_p3_drafts WHERE request_id=:requestId ORDER BY revision DESC FETCH FIRST 1 ROW ONLY', requestId=request_id)
    return found[0] if found else None


def pending_manual(connection, request_id, request_revision):
    latest = latest_draft(connection, request_id)
    if latest and latest['request_revision'] == request_revision:
        resolved = rows(connection, 'SELECT action_type FROM mvp_p3_resolutions WHERE draft_id=:draftId', draftId=latest['draft_id'])
        return latest if not resolved else None
    return None


def draft_view(record):
    state = ManualSnapshot.model_validate(document(record['preview_json']))
    members = [{"person_id": m.person_id, "full_name": state.names.get(m.person_id, m.person_id),
        "role_in_pod": m.role.value, "planned_hours": m.hours, "score": state.option.scores[m.person_id]['score'],
        "responsibilities": m.responsibilities, "factors": state.option.scores[m.person_id],
        "source": state.sources[m.person_id]} for m in state.option.proposal.members]
    return {'draft_id': record['draft_id'], 'revision': record['revision'], 'request_id': record['request_id'],
        'request_revision': record['request_revision'], 'policy_version': record['policy_version'],
        'source_proposal_id': state.source_proposal_id, 'slots': [s.model_dump(mode='json') for s in state.slots],
        'starts_on': state.starts_on, 'ends_on': state.ends_on, 'lead_count': state.lead_count, 'member_count': state.member_count,
        'total_hours': state.option.proposal.members and sum(m.hours for m in state.option.proposal.members),
        'members': members, 'original_members': state.original_members, 'reserves_capacity': False,
        'rationale': 'Captain-selected POD. Only explicitly marked people bypass skills, the normal ceiling, leave and external commitments. '
                     'Their existing POD assignments plus this request must fit within 100% of contracted working hours. '
                     'Unmarked people retain normal staffing rules. Leave and external work remain recorded; overall reported workload may be higher.'}


class ManualStore:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def request(self, c, actor, request_id, lock=False):
        actor.require('AI_FITMENT', 'approve', 'POD_CAPTAIN')
        found = rows(c, "SELECT request_revision,responsible_captain_id,status,estimated_start_date,estimated_completion_date,requested_lead_count,requested_contributor_count FROM requests WHERE request_id=:requestId" + (' FOR UPDATE WAIT 5' if lock else ''), requestId=request_id)
        if not found:
            raise ServiceError('REQUEST_NOT_FOUND', 'Request not found.', 404)
        DecisionStore.authorize(c, actor, found[0]['responsible_captain_id'])
        return found[0]

    def pool(self, c, request):
        return rows(c, """SELECT DISTINCT p.person_id,p.full_name,ur.role_code FROM people p
            JOIN app_accounts a ON a.person_id=p.person_id AND a.active_flag='Y'
            JOIN app_user_roles ur ON ur.person_id=p.person_id AND ur.identity_subject=a.identity_subject AND ur.active_flag='Y'
            JOIN app_roles ar ON ar.role_code=ur.role_code AND ar.active_flag='Y'
            WHERE p.active_flag='Y' AND ur.role_code IN ('POD_LEAD','POD_MEMBER')
            AND ur.effective_from<=:startDay AND (ur.effective_to IS NULL OR ur.effective_to>=:endDay)
            ORDER BY p.full_name,p.person_id,ur.role_code""", startDay=request['estimated_start_date'], endDay=request['estimated_completion_date'])

    def get(self, actor, request_id):
        with self.database.read() as c:
            request = self.request(c, actor, request_id)
            latest = latest_draft(c, request_id)
            pending = pending_manual(c, request_id, request['request_revision'])
            return {'people': self.pool(c, request), 'request_revision': request['request_revision'],
                    'lead_count': request['requested_lead_count'], 'member_count': request['requested_contributor_count'],
                    'latest_draft_id': latest['draft_id'] if latest else None,
                    'draft': draft_view(pending) if pending and request['status'] in ('IN_REVIEW', 'NEEDS_RECOMMENDATION') else None}

    @staticmethod
    def open_request(c, request_id, request):
        if request['status'] not in ('NEEDS_RECOMMENDATION', 'IN_REVIEW'):
            raise ServiceError('REQUEST_NOT_RUNNABLE', 'Only an open unstaffed request can have a manual draft.', 409)
        if rows(c, "SELECT execution_id FROM agent_executions WHERE request_id=:requestId AND status IN ('QUEUED','RUNNING')", requestId=request_id):
            raise ServiceError('EXECUTION_ACTIVE', 'Wait for the current execution to finish before manual drafting or approval.', 409)

    @staticmethod
    def keys(actor, body):
        return (hashlib.sha256(f'manual:{actor.subject}|{body.idempotency_key}'.encode()).hexdigest(),
                hashlib.sha256(json_text(body).encode()).hexdigest())

    def preview(self, actor, request_id, body):
        key, body_hash = self.keys(actor, body)
        with self.database.write() as c:
            version = active_policy_version(c, lock=True)
            request = self.request(c, actor, request_id, lock=True)
            prior = rows(c, 'SELECT * FROM mvp_p3_drafts WHERE idempotency_key=:idemKey', idemKey=key)
            if prior:
                if prior[0]['body_hash'] != body_hash or prior[0]['request_id'] != request_id:
                    raise ServiceError('IDEMPOTENCY_CONFLICT', 'This key was used for another preview.', 409)
                return draft_view(prior[0])
            self.open_request(c, request_id, request)
            if request['request_revision'] != body.request_revision:
                raise ServiceError('STALE_REQUEST', 'The request changed. Refresh before manual selection.', 409)
            latest = latest_draft(c, request_id)
            if body.previous_draft_id != (latest['draft_id'] if latest else None):
                raise ServiceError('STALE_SELECTION', 'Another manual draft was saved. Refresh before changing it.', 409)
            pending = pending_manual(c, request_id, request['request_revision'])
            previous = ManualSnapshot.model_validate(document(pending['preview_json'])) if pending else None
            original_members, normal_slots, sources, source_selection = (), set(), {}, None
            if previous:
                if body.source_proposal_id != previous.source_proposal_id:
                    raise ServiceError('INVALID_SELECTION', 'Discard the current draft before changing its source.', 409)
                original_members = previous.original_members
                normal_slots = {(s.person_id, s.role) for s in previous.slots if not s.manual}
                sources, source_selection = previous.sources, previous.source_selection_id
            elif body.source_proposal_id:
                source = rows(c, 'SELECT request_id,request_revision,status,policy_version FROM pod_proposals WHERE proposal_id=:proposalId', proposalId=body.source_proposal_id)
                if (not source or source[0]['request_id'] != request_id or source[0]['request_revision'] != request['request_revision']
                    or source[0]['status'] != 'READY_FOR_REVIEW' or source[0]['policy_version'] != version):
                    raise ServiceError('STALE_PROPOSAL', 'Refresh the recommendation or start a fully manual POD.', 409)
                loaded = load_review(c, body.source_proposal_id)
                if not loaded:
                    raise ServiceError('SELECTION_UNAVAILABLE', 'Re-run fitment or select a fully manual POD.', 409)
                original, selected, last_selection = loaded
                normal_slots = {(m.person_id, m.role) for m in selected.selected.proposal.members}
                original_members = tuple({'person_id': m.person_id, 'full_name': original.names.get(m.person_id, m.person_id), 'role_in_pod': m.role.value}
                                         for m in original.selected.proposal.members)
                sources = selected.sources
                source_selection = last_selection['selection_id'] if last_selection else None
            if any(not s.manual and (s.person_id, s.role) not in normal_slots for s in body.slots):
                raise ServiceError('INVALID_SELECTION', 'Newly chosen people must be explicitly marked as manual overrides.', 409)
            pool_ids = {p['person_id'] for p in self.pool(c, request)}
            if not {s.person_id for s in body.slots} <= pool_ids:
                raise ServiceError('ROLE_INELIGIBLE', 'All selected people need active accounts and staffing roles.', 409)
            for pid in sorted({s.person_id for s in body.slots}):
                rows(c, 'SELECT person_id FROM people WHERE person_id=:personId FOR UPDATE WAIT 5', personId=pid)
            fresh = collect_evidence(c, request_id, version, self.settings.staffing_max_candidates)
            option = manual_plan(fresh, body.slots)
            state = ManualSnapshot(option=option, evidence=fresh, slots=body.slots, evidence_hash=evidence_hash(fresh), names=fresh.names,
                sources={s.person_id: 'MANUAL' if s.manual else sources[s.person_id] for s in body.slots},
                original_members=original_members, source_proposal_id=body.source_proposal_id, source_selection_id=source_selection,
                starts_on=fresh.request.starts_on.isoformat(), ends_on=fresh.request.ends_on.isoformat(),
                lead_count=fresh.request.lead_count, member_count=fresh.request.member_count)
            draft_id, revision = 'MD' + uuid4().hex[:28], (latest['revision'] + 1 if latest else 1)
            execute(c, """INSERT INTO mvp_p3_drafts(draft_id,request_id,request_revision,revision,policy_version,actor_subject,idempotency_key,body_hash,preview_json)
                VALUES(:draftId,:requestId,:requestRevision,:revision,:policyVersion,:actorSubject,:idemKey,:bodyHash,:previewJson)""",
                {'draftId': draft_id, 'requestId': request_id, 'requestRevision': body.request_revision, 'revision': revision,
                 'policyVersion': version, 'actorSubject': actor.subject, 'idemKey': key, 'bodyHash': body_hash, 'previewJson': json_text(state)}, ('previewJson',))
            self.audit(c, actor, draft_id, 'PREVIEWED', {'sources': state.sources, 'reserves_capacity': False})
            return draft_view({'draft_id': draft_id, 'request_id': request_id, 'request_revision': body.request_revision,
                               'revision': revision, 'policy_version': version, 'preview_json': json_text(state)})

    @staticmethod
    def audit(c, actor, draft_id, action, values):
        audit_id = uuid4().hex
        execute(c, """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,
            correlation_id,after_state_json)
            VALUES(:auditId,'MANUAL_DRAFT',:draftId,:actionType,:actorSubject,:auditId,:afterJson)""",
            {'auditId': audit_id, 'draftId': draft_id, 'actionType': action, 'actorSubject': actor.subject,
             'afterJson': json_text(values)}, ('afterJson',))

    def decide(self, actor, request_id, body):
        if body.action != 'DISCARDED' and not self.settings.staffing_decisions_enabled:
            raise ServiceError('DECISIONS_DISABLED', 'Captain decisions are disabled.', 503)
        if body.action == 'REJECTED' and not body.reason:
            raise ServiceError('REASON_REQUIRED', 'Rejection requires a nonblank reason.', 422)
        key, body_hash = self.keys(actor, body)
        with self.database.write() as c:
            version = active_policy_version(c, lock=True)
            request = self.request(c, actor, request_id, lock=True)
            prior = rows(c, 'SELECT * FROM mvp_p3_resolutions WHERE idempotency_key=:idemKey', idemKey=key)
            if prior:
                if prior[0]['request_id'] != request_id or prior[0]['body_hash'] != body_hash:
                    raise ServiceError('IDEMPOTENCY_CONFLICT', 'This key was used for another decision.', 409)
                return {'status': prior[0]['action_type'], 'proposal_id': prior[0]['proposal_id'], 'replayed': True}
            latest = latest_draft(c, request_id)
            if not latest or latest['draft_id'] != body.draft_id or rows(c, 'SELECT action_type FROM mvp_p3_resolutions WHERE draft_id=:draftId', draftId=body.draft_id):
                raise ServiceError('STALE_SELECTION', 'Review the latest unresolved manual draft.', 409)
            result = {'status': 'DISCARDED', 'proposal_id': None, 'decision_id': None, 'replayed': False}
            if body.action != 'DISCARDED':
                self.open_request(c, request_id, request)
                if latest['request_revision'] != request['request_revision'] or latest['policy_version'] != version:
                    raise ServiceError('STALE_REQUEST', 'Request or policy changed. Discard this draft and prepare a new preview.', 409)
                state = ManualSnapshot.model_validate(document(latest['preview_json']))
                for pid in sorted(s.person_id for s in state.slots):
                    rows(c, 'SELECT person_id FROM people WHERE person_id=:personId FOR UPDATE WAIT 5', personId=pid)
                fresh = collect_evidence(c, request_id, version, self.settings.staffing_max_candidates)
                fresh.policy.require_published()
                if body.action == 'APPROVED':
                    pool_ids = {p['person_id'] for p in self.pool(c, request)}
                    if not {s.person_id for s in state.slots} <= pool_ids:
                        raise ServiceError('ROLE_INELIGIBLE', 'A selected account or role is no longer active.', 409)
                    if state.evidence_hash != evidence_hash(fresh):
                        raise ServiceError('SELECTION_REFRESH_REQUIRED', 'Workload or evidence changed. Recalculate, review the statistics and approve again.', 409)
                    checked = manual_plan(fresh, state.slots)
                    if checked.model_dump(mode='json') != state.option.model_dump(mode='json'):
                        raise ServiceError('SELECTION_REFRESH_REQUIRED', 'The selected schedule changed. Recalculate and review again.', 409)
                    if rows(c, "SELECT assignment_id FROM pod_assignments WHERE request_id=:requestId AND status='CONFIRMED'", requestId=request_id):
                        raise ServiceError('ALREADY_ASSIGNED', 'This request already has assignments.', 409)
                validation = {'origin': 'CAPTAIN_MANUAL', 'manual_draft_id': body.draft_id,
                    'manual_ids': [s.person_id for s in state.slots if s.manual], 'selection_sources': state.sources,
                    'source_proposal_id': state.source_proposal_id, 'source_selection_id': state.source_selection_id,
                    'manual_capacity_basis': 'POD_ONLY_CONTRACTED', 'manual_maximum_pct': 100,
                    'ignored_checks': ['SKILL_AND_EXPERIENCE', 'NORMAL_UTILIZATION_CEILING', 'LEAVE', 'EXTERNAL_COMMITMENTS']}
                pid, pversion = write_proposal(c, fresh if body.action == 'APPROVED' else state.evidence, state.option, None, validation,
                                              draft_view(latest)['rationale'], manual=True)
                decision = CaptainDecision(proposal_id=pid, proposal_version=int(pversion), action=body.action,
                                           reason=body.reason, idempotency_key=body.idempotency_key)
                result = commit_final_decision(c, actor, decision, {'proposal_id': pid, 'proposal_version': pversion},
                    request_id, version, state.option.proposal if body.action == 'APPROVED' else None,
                    fresh, validation, idempotency_key=key)
            execute(c, """INSERT INTO mvp_p3_resolutions(draft_id,request_id,action_type,proposal_id,decision_id,actor_subject,idempotency_key,body_hash,reason)
                VALUES(:draftId,:requestId,:actionType,:proposalId,:decisionId,:actorSubject,:idemKey,:bodyHash,:reasonText)""",
                {'draftId': body.draft_id, 'requestId': request_id, 'actionType': body.action, 'proposalId': result.get('proposal_id'),
                 'decisionId': result.get('decision_id'), 'actorSubject': actor.subject, 'idemKey': key,
                 'bodyHash': body_hash, 'reasonText': body.reason or None})
            self.audit(c, actor, body.draft_id, body.action, result)
            return result
