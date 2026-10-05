"""Offline tests for provisioning and business clarification; no Oracle writes."""
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr, ValidationError

from app.auth import Actor, Permission
from app.employee_provisioning import EmployeeInput, provision_employee
from app.errors import ServiceError
from app.request_clarification import ClarificationInput, answer_clarification, clarification_record
from app.storage import load_request_snapshot
from tests.test_storage import request_row, requirement


class Database:
    def __init__(self):
        self.c = MagicMock()
        self.commits = self.rollbacks = 0

    @contextmanager
    def write(self):
        try:
            yield self.c
            self.commits += 1
        except BaseException:
            self.rollbacks += 1
            raise

    read = write


ADMIN = Actor('acct:admin', 'P-1', frozenset({'SYSTEM_ADMINISTRATOR'}), (
    Permission('SYSTEM_ADMINISTRATOR', 'ACCESS_MANAGEMENT', 'FULL', frozenset({'view', 'administer'})),
    Permission('SYSTEM_ADMINISTRATOR', 'TEAM_SKILLS', 'FULL', frozenset({'view', 'create'})),
))
MEMBER = Actor('acct:member', 'P-2', frozenset({'POD_MEMBER'}), ())
CAPTAIN = Actor('acct:captain', 'P-3', frozenset({'POD_CAPTAIN'}), (
    Permission('POD_CAPTAIN', 'AI_FITMENT', 'FULL', frozenset({'view', 'approve'})),
    Permission('POD_CAPTAIN', 'AGENT_EXECUTION', 'FULL', frozenset({'view', 'create'})),
))


def settings(**changes):
    return SimpleNamespace(backend_auth_mode='password', staffing_mvp_default_password=SecretStr('offline-test-secret'),
                           **{'staffing_worker_enabled': True, **changes})


def employee(**changes):
    return EmployeeInput(**{**dict(fullName='New Employee', jobTitle='Engineer', location='Bengaluru',
        email='new.employee@oracle.com', roles=['POD_MEMBER', 'POD_LEAD'], enabled=True, staffingEligible=True), **changes})


@pytest.mark.parametrize('changes', [dict(email='new@example.com'), dict(email=''), dict(fullName='  '),
    dict(roles=[]), dict(roles=['EXECUTIVE']), dict(roles=['POD_LEAD', 'POD_LEAD']), dict(enabled='true'),
    dict(staffingEligible=1), dict(allocationPct=50), dict(activePods=1), dict(jobTitle='é'*200)])
def test_invalid_employee_inputs(changes):
    with pytest.raises(ValidationError):
        employee(**changes)


def provisioning_queries(duplicate=False, roles=('POD_MEMBER', 'POD_LEAD')):
    def query(c, sql, **binds):
        if 'roster_access_control' in sql:
            assert 'FOR UPDATE' in sql
            return [{'revision': 2}]
        if 'UNION ALL' in sql:
            assert 'app_accounts' in sql and 'active_flag' not in sql
            return [{'person_id': 'P-OLD'}] if duplicate else []
        if 'FROM app_roles' in sql:
            return [{'role_code': role} for role in roles]
        if 'person_id_seq' in sql:
            return [{'person_number': 101}]
        raise AssertionError(sql)
    return query


@pytest.mark.parametrize('enabled,eligible', [(True, True), (False, True), (True, False)])
def test_employee_person_login_roles_and_onboarding_commit_together(enabled, eligible):
    db = Database()
    with patch('app.employee_provisioning.authorize') as auth, patch('app.employee_provisioning.rows', side_effect=provisioning_queries()), \
            patch('app.employee_provisioning.hash_password', return_value='salted-hash') as hashed, \
            patch('app.employee_provisioning.execute') as execute, patch('app.employee_provisioning.audit') as audit:
        result = provision_employee(db, settings(), ADMIN, employee(enabled=enabled, staffingEligible=eligible))
    assert result == dict(personId='P-101', fullName='New Employee', enabled=enabled, onboarding='DRAFT')
    assert db.commits == 1 and db.rollbacks == 0
    assert auth.call_count == 2
    hashed.assert_called_once_with('offline-test-secret')
    calls = execute.call_args_list
    person = next(call for call in calls if 'INSERT INTO people' in call.args[1])
    account = next(call for call in calls if 'INSERT INTO app_accounts' in call.args[1])
    assert person.args[2]['eligible'] == ('Y' if eligible else 'N')
    assert '40' in person.args[1] and "0,0,'Y'" in person.args[1]
    assert account.args[2]['encoded'] == 'salted-hash'
    assert account.args[2]['active'] == ('Y' if enabled else 'N')
    assert account.args[2]['subject'] == person.args[2]['subject']
    assert sum('INSERT INTO app_user_roles' in call.args[1] for call in calls) == 2
    assert any("roster_onboarding(person_id,status) VALUES(:pid,'DRAFT')" in call.args[1] for call in calls)
    assert any('revision=revision+1' in call.args[1] for call in calls)
    assert all('pod_assignments' not in call.args[1] and 'person_capacity_days' not in call.args[1] for call in calls)
    assert 'secret' not in str(result) and 'salted-hash' not in str(audit.call_args)


def test_provisioning_rolls_back_when_onboarding_insert_fails():
    db = Database()
    def write(c, sql, *args):
        if 'INSERT INTO roster_onboarding' in sql:
            raise RuntimeError('simulated write failure')
    with patch('app.employee_provisioning.authorize'), patch('app.employee_provisioning.rows', side_effect=provisioning_queries()), \
            patch('app.employee_provisioning.hash_password', return_value='hash'), \
            patch('app.employee_provisioning.execute', side_effect=write), pytest.raises(RuntimeError):
        provision_employee(db, settings(), ADMIN, employee())
    assert db.commits == 0 and db.rollbacks == 1


@pytest.mark.parametrize('duplicate,roles,code', [(True, ('POD_MEMBER', 'POD_LEAD'), 'EMPLOYEE_EXISTS'),
                                               (False, ('POD_MEMBER',), 'ROLE_UNAVAILABLE')])
def test_duplicate_disabled_identity_and_missing_role_stop_before_any_insert(duplicate, roles, code):
    db = Database()
    with patch('app.employee_provisioning.authorize'), patch('app.employee_provisioning.rows', side_effect=provisioning_queries(duplicate, roles)), \
            patch('app.employee_provisioning.hash_password', return_value='hash'), patch('app.employee_provisioning.execute') as write, \
            pytest.raises(ServiceError) as error:
        provision_employee(db, settings(), ADMIN, employee())
    assert error.value.code == code and not write.called and db.commits == 0


def test_only_admin_with_both_permissions_can_provision_and_password_must_exist():
    db = Database()
    with patch('app.employee_provisioning.hash_password') as hashed:
        for actor in [MEMBER, CAPTAIN, Actor(ADMIN.subject, ADMIN.person_id, ADMIN.roles, ADMIN.permissions[:1])]:
            with pytest.raises(ServiceError):
                provision_employee(db, settings(), actor, employee())
        assert not hashed.called
        config = settings()
        config.staffing_mvp_default_password = None
        with pytest.raises(ServiceError) as error:
            provision_employee(db, config, ADMIN, employee())
        assert error.value.code == 'EMPLOYEE_PASSWORD_CONFIGURATION'
    assert db.commits == 0


def answer(**changes):
    return ClarificationInput(**{**dict(revision=2, execution_id='RUN-old', business_objectives='Business objective',
        expected_outcomes='Publish a reviewed guide for the sales team', project_description='Project scope'), **changes})


def current_question(**changes):
    return {**dict(revision=2, execution_id='RUN-old', fields=['expected_outcomes'], questions=['What outcomes?'],
        business_objectives='Business objective', expected_outcomes='', project_description='Project scope'), **changes}


def clarification_mocks(stack, *, current=None, queued=True, queue_error=False, assignments=False, active=False):
    stack.enter_context(patch('app.request_clarification.active_policy_version', return_value='policy'))
    record = stack.enter_context(patch('app.request_clarification.clarification_record', return_value=current or current_question()))
    stack.enter_context(patch('app.request_clarification.load_request_snapshot', return_value=object()))
    stack.enter_context(patch('app.request_clarification.load_policy', return_value=object()))
    stack.enter_context(patch('app.request_clarification.require_future_schedule'))
    stack.enter_context(patch('app.request_clarification.runtime_enabled', return_value=queued))
    def query(c, sql, **binds):
        if 'pod_assignments' in sql:
            return [{'assignment_id': 'A'}] if assignments else []
        if 'agent_executions' in sql:
            return [{'execution_id': 'RUN-new'}] if active else []
        return [{'request_revision': 3}]
    stack.enter_context(patch('app.request_clarification.rows', side_effect=query))
    write = stack.enter_context(patch('app.request_clarification.execute'))
    audit = stack.enter_context(patch('app.request_clarification.audit'))
    enqueue = stack.enter_context(patch('app.request_clarification.ExecutionStore.enqueue',
        return_value=dict(execution_id='RUN-new', status='QUEUED'), side_effect=RuntimeError('queue failed') if queue_error else None))
    return record, write, audit, enqueue


@pytest.mark.parametrize('queued', [True, False])
def test_answer_creates_revision_with_queued_or_durable_pending_rerun(queued):
    db = Database()
    with ExitStack() as stack:
        record, write, audit, enqueue = clarification_mocks(stack, queued=queued)
        result = answer_clarification(db, settings(), CAPTAIN, 'REQ-1', answer())
    assert db.commits == 1 and db.rollbacks == 0
    assert result['revision'] == 3
    assert result['status'] == ('QUEUED' if queued else 'PENDING_AGENT')
    assert enqueue.called == queued
    assert record.call_args.kwargs['lock'] is True
    assert "agent_enabled='Y'" in write.call_args.args[1]
    assert 'request_revision=' not in write.call_args.args[1]  # Trigger, not double increment.
    assert write.call_args.args[2]['outcomes'] == answer().expected_outcomes
    assert 'RUN-old retained' in audit.call_args.args[-1]


@pytest.mark.parametrize('changes,options,code', [
    ({'revision': 1}, {}, 'STALE_REQUEST'), ({'execution_id': 'RUN-other'}, {}, 'STALE_REQUEST'),
    ({'expected_outcomes': '   '}, {}, 'ANSWER_REQUIRED'), ({}, {'assignments': True}, 'ALREADY_ASSIGNED'),
    ({}, {'active': True}, 'EXECUTION_ACTIVE'),
])
def test_answer_rejects_stale_missing_or_assigned_input_without_writes(changes, options, code):
    db = Database()
    with ExitStack() as stack:
        _, write, _, enqueue = clarification_mocks(stack, **options)
        with pytest.raises(ServiceError) as error:
            answer_clarification(db, settings(), CAPTAIN, 'REQ-1', answer(**changes))
    assert error.value.code == code and not write.called and not enqueue.called
    assert db.commits == 0


def test_queue_failure_rolls_back_answers_and_revision_not_partial_success():
    db = Database()
    with ExitStack() as stack:
        clarification_mocks(stack, queue_error=True)
        with pytest.raises(RuntimeError):
            answer_clarification(db, settings(), CAPTAIN, 'REQ-1', answer())
    assert db.commits == 0 and db.rollbacks == 1


def test_clarification_contract_rejects_assignment_edits_and_oversized_answers():
    for change in [dict(person_id='P-OTHER'), dict(revision=0), dict(expected_outcomes='x'*32001)]:
        with pytest.raises(ValidationError):
            answer(**change)


def test_clarification_record_requires_real_captain_and_current_server_authored_fields():
    with pytest.raises(ServiceError):
        clarification_record(None, MEMBER, 'REQ-1')
    request = dict(request_revision=2, responsible_captain_id='P-3', status='NEEDS_RECOMMENDATION',
                   business_objectives='Objective', expected_outcomes=None, project_description=None)
    for fields, status, revision, valid in [(['expected_outcomes'], 'NEEDS_INFORMATION', 2, True),
        (['password'], 'NEEDS_INFORMATION', 2, False), ([], 'NEEDS_INFORMATION', 2, False),
        (['expected_outcomes'], 'RUNNING', 2, False), (['expected_outcomes'], 'NEEDS_INFORMATION', 1, False)]:
        run = dict(execution_id='RUN-old', request_revision=revision, status=status,
                   checkpoint_json={'analysis': {'clarification_fields': fields}})
        with patch('app.request_clarification.rows', side_effect=[[request], [run]]), \
                patch('app.request_clarification.current_account'), patch('app.request_clarification.DecisionStore.authorize'), \
                patch('app.request_clarification.assert_captain'):
            if valid:
                result = clarification_record(None, CAPTAIN, 'REQ-1')
                assert result['fields'] == fields and result['expected_outcomes'] == ''
                assert 'outcomes or success' in result['questions'][0]
            else:
                with pytest.raises(ServiceError):
                    clarification_record(None, CAPTAIN, 'REQ-1')


def test_legacy_same_id_deliverables_are_normalized_without_double_work():
    row = request_row()
    row['deliverables_json'] = [{'id': 'DEL-1', 'name': 'Guide'}, {'id': 'DEL-1', 'name': 'Guide', 'resolution': 'EXACT_NAME'}]
    with patch('app.storage.rows', side_effect=[[row], [requirement()]]):
        assert load_request_snapshot(None, 'REQ-1').deliverable_ids == ('DEL-1',)
    row['deliverables_json'][1]['custom'] = True
    with patch('app.storage.rows', side_effect=[[row], [requirement()]]), pytest.raises(ServiceError):
        load_request_snapshot(None, 'REQ-1')
