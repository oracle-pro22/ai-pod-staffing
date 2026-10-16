"""Shared administrator notepad. Not staffing evidence or an agent tool."""
from uuid import uuid4

import oracledb
from pydantic import ConfigDict, Field

from app.contracts import Contract
from app.errors import ServiceError
from app.execution_store import execute
from app.roster_lifecycle import authorize
from app.storage import rows


class EnhancementUpdate(Contract):
    model_config = ConfigDict(str_strip_whitespace=False)
    content: str = Field(max_length=50000, strict=True)
    expected_revision: int = Field(ge=1, strict=True)


def require_admin(actor, action):
    permission = actor.require('ADMINISTRATION', action, 'SYSTEM_ADMINISTRATOR')
    if permission.scope != 'FULL':
        raise ServiceError('FORBIDDEN', 'Full Administrator access is required.', 403)


def read_document(connection, *, lock=False):
    try:
        result = rows(connection, """SELECT content,revision,updated_by_name,
            TO_CHAR(SYS_EXTRACT_UTC(updated_at),'YYYY-MM-DD"T"HH24:MI:SS.FF6"Z"') updated_at
            FROM admin_enhancement_notes WHERE document_id=1""" + (' FOR UPDATE WAIT 5' if lock else ''))
    except oracledb.DatabaseError as error:
        if getattr(error.args[0], 'code', None) == 942:
            raise ServiceError('ENHANCEMENTS_SETUP_REQUIRED',
                               'Install admin_enhancements.sql to enable the shared notepad.', 503) from error
        raise
    if len(result) != 1:
        raise ServiceError('ENHANCEMENTS_SETUP_REQUIRED',
                           'Install admin_enhancements.sql to initialize the shared notepad.', 503)
    value = result[0]
    content = value['content']
    value['content'] = (content.read() if hasattr(content, 'read') else content) or ''
    value['revision'] = int(value['revision'])
    return value


def get_enhancements(database, actor):
    require_admin(actor, 'view')
    with database.read() as connection:
        authorize(connection, actor, 'ADMINISTRATION', 'view', 'SYSTEM_ADMINISTRATOR')
        return read_document(connection)


def save_enhancements(database, actor, body):
    require_admin(actor, 'update')
    with database.write() as connection:
        authorize(connection, actor, 'ADMINISTRATION', 'update', 'SYSTEM_ADMINISTRATOR')
        previous = read_document(connection, lock=True)
        if previous['revision'] != body.expected_revision:
            raise ServiceError('ENHANCEMENTS_CONFLICT',
                               'Another administrator saved changes. Review the latest text before saving your draft.', 409)
        if previous['content'] == body.content:
            return previous
        execute(connection, """UPDATE admin_enhancement_notes SET content=NVL(:content,EMPTY_CLOB()),
            revision=revision+1,updated_by_person_id=:person,updated_by_name=:name,
            updated_at=SYSTIMESTAMP WHERE document_id=1""",
            {'content': body.content, 'person': actor.person_id, 'name': actor.full_name or actor.person_id}, ('content',))
        execute(connection, """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,
            action_type,actor_subject,correlation_id,reason)
            VALUES(:id,'ENHANCEMENT_NOTEPAD','1','ENHANCEMENTS_UPDATED',:actor,:id,:reason)""",
            {'id': uuid4().hex, 'actor': actor.subject,
             'reason': f'Shared enhancement notepad saved; revision {previous["revision"] + 1}.'})
        return read_document(connection)
