"""Read-only Administrator history. Explicit projections never expose raw snapshots or credentials."""
import base64
import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from app.contracts import Contract
from app.errors import ServiceError
from app.roster_lifecycle import authorize
from app.storage import rows


class AuditQuery(Contract):
    kind: Literal['events', 'decisions', 'assignments'] = 'events'
    from_date: date | None = None
    to_date: date | None = None
    request_id: str = Field(default='', max_length=30, pattern=r'^[A-Za-z0-9_-]*$')
    actor: str = Field(default='', max_length=255)
    action: str = Field(default='', max_length=60)
    cursor: str = Field(default='', max_length=800, pattern=r'^[A-Za-z0-9_-]*$')
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode='after')
    def dates(self):
        if self.from_date and self.to_date and self.to_date < self.from_date:
            raise ValueError('End date must not precede start date')
        if self.to_date == date.max:
            raise ValueError('End date is out of range')
        return self


# Fixed queries, never supplied by the browser. No SELECT *, before/after JSON,
# idempotency keys, session data, hashes, or model evidence are returned.
SOURCES = {
    'events': """SELECT e.audit_event_id record_id,e.performed_at occurred_at,e.action_type action,
        e.actor_subject,COALESCE(actor.full_name,e.actor_subject) actor_name,
        COALESCE(r.request_id,p.request_id,a.request_id) request_id,
        e.entity_type,e.entity_id,e.reason
        FROM audit_events e LEFT JOIN people actor ON actor.external_identity_subject=e.actor_subject
        LEFT JOIN requests r ON r.request_id=e.entity_id
        LEFT JOIN pod_proposals p ON p.proposal_id=e.entity_id
        LEFT JOIN pod_assignments a ON a.assignment_id=e.entity_id""",
    'decisions': """SELECT d.decision_id record_id,d.decided_at occurred_at,d.action_type action,
        d.actor_subject,COALESCE(actor.full_name,d.actor_subject) actor_name,d.request_id,
        'PROPOSAL' entity_type,d.proposal_id entity_id,d.reason,p.policy_version
        FROM approval_decisions d JOIN pod_proposals p ON p.proposal_id=d.proposal_id
        LEFT JOIN people actor ON actor.external_identity_subject=d.actor_subject""",
    'assignments': """SELECT a.assignment_id record_id,a.created_at occurred_at,a.status action,
        d.actor_subject,COALESCE(actor.full_name,d.actor_subject) actor_name,a.request_id,
        'ASSIGNMENT' entity_type,a.assignment_id entity_id,a.close_reason reason,
        a.policy_version,a.person_id,person.full_name person_name,a.role_in_pod,
        TO_CHAR(a.starts_on,'YYYY-MM-DD') starts_on,TO_CHAR(a.ends_on,'YYYY-MM-DD') ends_on,
        a.assigned_hours,a.proposal_id,a.decision_id,
        TO_CHAR(SYS_EXTRACT_UTC(a.closed_at),'YYYY-MM-DD"T"HH24:MI:SS.FF6') closed_at
        FROM pod_assignments a JOIN approval_decisions d ON d.decision_id=a.decision_id
        JOIN people person ON person.person_id=a.person_id
        LEFT JOIN people actor ON actor.external_identity_subject=d.actor_subject""",
}
COMMON_FIELDS = 'record_id,action,actor_subject,actor_name,request_id,entity_type,entity_id,reason'
EXTRA_FIELDS = {
    'events': '', 'decisions': ',policy_version',
    'assignments': ',policy_version,person_id,person_name,role_in_pod,starts_on,ends_on,assigned_hours,proposal_id,decision_id,closed_at',
}


def fingerprint(query):
    return hashlib.sha256(query.model_dump_json(exclude={'cursor', 'limit'}).encode()).hexdigest()


def decode_cursor(query):
    if not query.cursor:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(query.cursor + '=' * (-len(query.cursor) % 4)))
        if not isinstance(data, dict) or set(data) != {'time', 'id', 'filter'} or data['filter'] != fingerprint(query):
            raise ValueError('Changed filters')
        if not isinstance(data['id'], str) or not 1 <= len(data['id']) <= 64:
            raise ValueError('Invalid ID')
        timestamp = datetime.strptime(data['time'], '%Y-%m-%dT%H:%M:%S.%f')
        return timestamp, data['id']
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise ServiceError('INVALID_CURSOR', 'History filters changed or the page cursor is invalid. Start from the first page.', 400) from error


def read_audit(database, actor, query):
    actor.require('ADMINISTRATION', 'view', 'SYSTEM_ADMINISTRATOR')
    cursor = decode_cursor(query)
    with database.read() as c:
        authorize(c, actor, 'ADMINISTRATION', 'view', 'SYSTEM_ADMINISTRATOR')
        predicates, binds = [], {'take': query.limit + 1}
        if query.from_date:
            predicates.append('SYS_EXTRACT_UTC(occurred_at)>=:firstDay')
            binds['firstDay'] = datetime.combine(query.from_date, datetime.min.time())
        if query.to_date:
            predicates.append('SYS_EXTRACT_UTC(occurred_at)<:afterDay')
            binds['afterDay'] = datetime.combine(query.to_date + timedelta(days=1), datetime.min.time())
        if query.request_id:
            predicates.append('request_id=:requestId')
            binds['requestId'] = query.request_id
        if query.actor:
            predicates.append('(INSTR(LOWER(actor_subject),LOWER(:actorText))>0 OR INSTR(LOWER(actor_name),LOWER(:actorText))>0)')
            binds['actorText'] = query.actor
        if query.action:
            predicates.append('UPPER(action)=UPPER(:actionText)')
            binds['actionText'] = query.action
        if cursor:
            predicates.append('(SYS_EXTRACT_UTC(occurred_at)<:beforeTime OR (SYS_EXTRACT_UTC(occurred_at)=:beforeTime AND record_id<:beforeId))')
            binds.update(beforeTime=cursor[0], beforeId=cursor[1])
        where = ' AND '.join(predicates) or '1=1'
        records = rows(c, f"""SELECT {COMMON_FIELDS}{EXTRA_FIELDS[query.kind]},
            TO_CHAR(SYS_EXTRACT_UTC(occurred_at),'YYYY-MM-DD"T"HH24:MI:SS.FF6') occurred_at
            FROM ({SOURCES[query.kind]}) history WHERE {where}
            ORDER BY history.occurred_at DESC,record_id DESC FETCH FIRST :take ROWS ONLY""", **binds)
        more = len(records) > query.limit
        records = records[:query.limit]
        next_cursor = None
        if more:
            last = records[-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps(dict(time=last['occurred_at'], id=last['record_id'],
                filter=fingerprint(query)), separators=(',', ':')).encode()).decode().rstrip('=')
        return {'kind': query.kind, 'records': records, 'next_cursor': next_cursor, 'timezone': 'UTC', 'read_only': True}
