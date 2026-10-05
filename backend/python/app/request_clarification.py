"""Answer only server-defined business questions; revision-fenced, atomic rerun."""
from pydantic import Field, field_validator

from app.agents.staffing import BUSINESS_QUESTIONS
from app.capacity_admin import SameConnection
from app.contracts import Contract
from app.decisions import DecisionStore
from app.errors import ServiceError
from app.execution_store import ExecutionStore, assert_captain, execute, runtime_enabled
from app.policy_admin import active_policy_version
from app.roster_lifecycle import audit, current_account
from app.schedule_dates import require_future_schedule
from app.storage import document, load_policy, load_request_snapshot, rows


class ClarificationInput(Contract):
    revision: int = Field(ge=1, strict=True)
    execution_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    business_objectives: str = Field(min_length=1, max_length=32000)
    expected_outcomes: str = Field(max_length=32000)
    project_description: str = Field(min_length=1, max_length=4000)

    @field_validator('business_objectives', 'expected_outcomes', 'project_description')
    @classmethod
    def trimmed(cls, value, info):
        value = value.strip()
        if info.field_name == 'project_description' and len(value.encode('utf-8')) > 4000:
            raise ValueError('Project scope must fit within 4,000 UTF-8 bytes')
        return value


def clarification_record(c, actor, request_id, lock=False):
    actor.require('AI_FITMENT', 'approve', 'POD_CAPTAIN')
    records = rows(c, """SELECT request_revision,responsible_captain_id,status,
        business_objectives,expected_outcomes,project_description FROM requests WHERE request_id=:rid"""
        + (' FOR UPDATE WAIT 5' if lock else ''), rid=request_id)
    if not records:
        raise ServiceError('REQUEST_NOT_FOUND', 'Request not found.', 404)
    row = records[0]
    current_account(c, actor)
    DecisionStore.authorize(c, actor, row['responsible_captain_id'])
    assert_captain(c, actor.subject, actor.person_id, row['responsible_captain_id'])
    if row['status'] not in ('NEEDS_RECOMMENDATION', 'IN_REVIEW'):
        raise ServiceError('REQUEST_NOT_EDITABLE', 'Only unstaffed requests can be clarified.', 409)
    latest = rows(c, """SELECT execution_id,request_revision,status,checkpoint_json FROM agent_executions
        WHERE request_id=:rid ORDER BY created_at DESC,execution_id DESC FETCH FIRST 1 ROW ONLY""", rid=request_id)
    if not latest or latest[0]['status'] != 'NEEDS_INFORMATION' or latest[0]['request_revision'] != row['request_revision']:
        raise ServiceError('CLARIFICATION_CHANGED', 'There is no current business clarification. Refresh the request.', 409)
    run = latest[0]
    checkpoint = document(run['checkpoint_json']) if run['checkpoint_json'] else {}
    analysis = checkpoint.get('analysis', {})
    fields = analysis.get('clarification_fields', [])
    if not isinstance(fields, list) or not fields or any(not isinstance(field, str) or field not in BUSINESS_QUESTIONS for field in fields):
        raise ServiceError('CLARIFICATION_UNAVAILABLE', 'This execution needs a data correction, not a business answer. Review its message and rerun after correcting the data.', 409)
    values = {}
    for field in BUSINESS_QUESTIONS:
        value = row.get(field)
        values[field] = value.read() if hasattr(value, 'read') else value or ''
    return dict(revision=row['request_revision'], execution_id=run['execution_id'], fields=fields,
                questions=[BUSINESS_QUESTIONS[field] for field in fields], **values)


def get_clarification(database, actor, request_id):
    with database.read() as c:
        return clarification_record(c, actor, request_id)


def answer_clarification(database, settings, actor, request_id, body):
    actor.require('AI_FITMENT', 'approve', 'POD_CAPTAIN')
    actor.require('AGENT_EXECUTION', 'create', 'POD_CAPTAIN')
    with database.write() as c:
        # Same lock order as queue/approval: policy, then request. No nested commit.
        version = active_policy_version(c, lock=True)
        current = clarification_record(c, actor, request_id, lock=True)
        if (current['revision'], current['execution_id']) != (body.revision, body.execution_id):
            raise ServiceError('STALE_REQUEST', 'The request or its question changed. Refresh before answering.', 409)
        if rows(c, "SELECT assignment_id FROM pod_assignments WHERE request_id=:rid AND status='CONFIRMED'", rid=request_id):
            raise ServiceError('ALREADY_ASSIGNED', 'An assigned request cannot be edited here.', 409)
        if rows(c, "SELECT execution_id FROM agent_executions WHERE request_id=:rid AND status IN ('QUEUED','RUNNING')", rid=request_id):
            raise ServiceError('EXECUTION_ACTIVE', 'Wait for the active run before answering.', 409)
        values = body.model_dump(exclude={'revision', 'execution_id'})
        if any(not values[field] for field in current['fields']) or not body.business_objectives:
            raise ServiceError('ANSWER_REQUIRED', 'Fill in the requested business fields and business objectives.', 422)
        if all(values[field] == current[field] for field in BUSINESS_QUESTIONS):
            raise ServiceError('ANSWER_UNCHANGED', 'Update the requested details before rerunning.', 422)
        snapshot = load_request_snapshot(c, request_id)
        require_future_schedule(snapshot, load_policy(c, version))
        # Existing trigger increments revision exactly once. Old proposals and
        # manual drafts remain history and cannot approve against this revision.
        execute(c, """UPDATE requests SET business_objectives=:objectives,business_context=:context,
            expected_outcomes=:outcomes,project_description=:description,status='NEEDS_RECOMMENDATION',
            agent_enabled='Y',updated_by=:actor WHERE request_id=:rid""",
            dict(objectives=body.business_objectives, context=body.business_objectives.encode('utf-8')[:2000].decode('utf-8', errors='ignore'), outcomes=body.expected_outcomes,
                 description=body.project_description, actor=actor.subject, rid=request_id),
            ('objectives', 'outcomes'))
        audit(c, actor, request_id, 'REQUEST_CLARIFIED',
              f"Answered {', '.join(current['fields'])}; previous revision {body.revision}; execution {body.execution_id} retained.")
        revision = rows(c, 'SELECT request_revision FROM requests WHERE request_id=:rid', rid=request_id)[0]['request_revision']
        if revision <= body.revision:
            raise ServiceError('REQUEST_REVISION_REQUIRED', 'Request revision tracking is not installed. No answers were saved.', 503)
        run = None
        if settings.staffing_worker_enabled and runtime_enabled(c):
            run = ExecutionStore(SameConnection(c), settings).enqueue(request_id, actor.subject, actor.person_id,
                f'clarification:{request_id}:{revision}')
        # Disabled runtime still commits durable discovery intent (agent_enabled).
        return dict(request_id=request_id, revision=revision, answers_saved=True,
                    status='QUEUED' if run else 'PENDING_AGENT', execution_id=run['execution_id'] if run else None)
