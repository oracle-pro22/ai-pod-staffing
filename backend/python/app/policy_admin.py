"""Administrator-owned, versioned utilization settings; never exposed as agent tools."""
from decimal import Decimal
from uuid import uuid4

import oracledb
from pydantic import Field, field_validator

from app.contracts import Contract
from app.errors import ServiceError
from app.storage import load_policy, rows


class UtilizationUpdate(Contract):
    maximum_allocation_pct: Decimal = Field(gt=0, le=100, decimal_places=2, allow_inf_nan=False)
    expected_policy_version: str = Field(min_length=1, max_length=60)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator('reason')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Explain the policy change')
        return value.strip()


def active_policy_version(connection, *, lock=False):
    try:
        records = rows(connection, 'SELECT policy_version FROM staffing_policy_control WHERE control_id=1'
                       + (' FOR UPDATE WAIT 5' if lock else ''))
    except oracledb.DatabaseError as error:
        if getattr(error.args[0], 'code', None) != 942:
            raise
        raise ServiceError('POLICY_NOT_CONFIGURED', 'Run utilization_policy.sql before starting agents.', 503) from error
    if len(records) != 1:
        raise ServiceError('POLICY_NOT_CONFIGURED', 'Install the utilization policy migration before running agents.', 503)
    return records[0]['policy_version']


def require_current_policy(connection, version, *, lock=False):
    if active_policy_version(connection, lock=lock) != version:
        raise ServiceError('STALE_POLICY', 'The utilization policy changed. Re-run fitment before approval.', 409)


class PolicyAdminStore:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def authorize(actor):
        permission = actor.require('BACKEND_CONFIGURATION', 'administer', 'SYSTEM_ADMINISTRATOR')
        if permission.scope != 'FULL':
            raise ServiceError('FORBIDDEN', 'Full Administrator configuration access is required.', 403)

    def get(self, actor):
        self.authorize(actor)
        with self.database.read() as connection:
            return load_policy(connection, active_policy_version(connection))

    def update(self, actor, body):
        self.authorize(actor)
        # Shared lock ordering: policy control -> request -> policy -> people.
        # The pointer and new immutable policy are committed in one transaction.
        from app.execution_store import execute
        from app.planning import json_text
        with self.database.write() as connection:
            version = active_policy_version(connection, lock=True)
            previous = load_policy(connection, version)
            if version != body.expected_policy_version:
                raise ServiceError('STALE_POLICY', 'Another Administrator changed the limit. Refresh before saving.', 409)
            if previous.maximum_allocation_pct == body.maximum_allocation_pct:
                return previous
            new_version = 'util-' + uuid4().hex
            binds = {'newVersion': new_version, 'oldVersion': version, 'actorSubject': actor.subject,
                     'descriptionText': body.reason}
            execute(connection, """INSERT INTO staffing_policies(policy_version,status,description,created_by)
                VALUES(:newVersion,'DRAFT',:descriptionText,:actorSubject)""",
                {k: binds[k] for k in ('newVersion','descriptionText','actorSubject')})
            clone = {'newVersion': new_version, 'oldVersion': version}
            execute(connection, """INSERT INTO eligibility_rules(policy_version,rule_code,rule_value_json)
                SELECT :newVersion,rule_code,rule_value_json FROM eligibility_rules WHERE policy_version=:oldVersion""", clone)
            execute(connection, """INSERT INTO scoring_weights(policy_version,skill_weight,deliverable_weight,capacity_weight,interest_weight)
                SELECT :newVersion,skill_weight,deliverable_weight,capacity_weight,interest_weight
                FROM scoring_weights WHERE policy_version=:oldVersion""", clone)
            execute(connection, """INSERT INTO load_guardrails(policy_version,default_weekly_hours,maximum_allocation_pct,scheduling_timezone)
                SELECT :newVersion,default_weekly_hours,:maximumPct,scheduling_timezone
                FROM load_guardrails WHERE policy_version=:oldVersion""", {**clone, 'maximumPct': body.maximum_allocation_pct})
            execute(connection, """UPDATE staffing_policies SET status='APPROVED',approved_by=:actorSubject,
                approved_at=SYSTIMESTAMP WHERE policy_version=:newVersion""",
                {'actorSubject': actor.subject, 'newVersion': new_version})
            policy = load_policy(connection, new_version)
            # Load/validate the entire clone before switching the active pointer.
            policy.require_published()
            execute(connection, """UPDATE staffing_policy_control SET policy_version=:newVersion,
                updated_by=:actorSubject,updated_at=SYSTIMESTAMP WHERE control_id=1""",
                {'newVersion': new_version, 'actorSubject': actor.subject})
            execute(connection, """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,
                correlation_id,after_state_json,reason) VALUES(:eventId,'STAFFING_POLICY',:newVersion,
                'UTILIZATION_LIMIT_CHANGED',:actorSubject,:eventId,:afterJson,:reasonText)""",
                {'eventId': uuid4().hex, 'newVersion': new_version, 'actorSubject': actor.subject,
                 'afterJson': json_text({'previous_policy_version': version, 'policy_version': new_version,
                     'before_maximum_pct': str(previous.maximum_allocation_pct),
                     'maximum_pct': str(body.maximum_allocation_pct)}), 'reasonText': body.reason}, ('afterJson',))
            return policy
