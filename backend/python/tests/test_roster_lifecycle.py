from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.auth import Actor, Permission
from app.errors import ServiceError
from app.roster_lifecycle import (
    AccessChange,
    OnboardingInput,
    RosterLifecycle,
    WorkEntry,
    authorize,
    require_ready,
    status,
)

MON, FRI = date(2026, 9, 21), date(2026, 9, 25)
ADMIN = Actor('acct:A', 'A', frozenset({'SYSTEM_ADMINISTRATOR'}),
              (Permission('SYSTEM_ADMINISTRATOR', 'ACCESS_MANAGEMENT', 'FULL', frozenset({'view', 'administer'})),))
PERSON = Actor('acct:B', 'B', frozenset({'POD_MEMBER'}), ())


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

    @contextmanager
    def read(self):
        yield self.c


def setup_body(**extra):
    return OnboardingInput(revision=1, starts_on=MON, ends_on=FRI, confirmed=True, **extra)


def work(**changes):
    return {'kind': 'EXTERNAL', 'title': 'Genuine work', 'starts_on': MON, 'ends_on': FRI, 'total_hours': 16, **changes}


@pytest.mark.parametrize('change', [
    {'ends_on': date(2026, 9, 20)}, {'total_hours': -1}, {'total_hours': 'NaN'},
    {'kind': 'POD'}, {'kind': 'EXTERNAL', 'role_code': 'POD_MEMBER'},
    {'kind': 'LEAVE', 'total_hours': 41}, {'total_hours': 121},
])
def test_invalid_work_rejected(change):
    with pytest.raises(ValidationError):
        WorkEntry(**work(**change))


def test_overallocated_actual_work_is_preserved_not_clamped_to_85_or_100():
    assert setup_body(work=[work(total_hours=50)]).work[0].total_hours == 50
    assert setup_body().skills == () and setup_body().work == ()


def test_duplicate_and_outside_period_entries_rejected():
    with pytest.raises(ValidationError):
        setup_body(work=[work(), work()])
    with pytest.raises(ValidationError):
        setup_body(work=[work(ends_on=date(2026, 9, 28))])
    with pytest.raises(ValidationError):
        setup_body(work=[work(kind='LEAVE', total_hours=30), work(kind='LEAVE', title='More leave', total_hours=20)])


@pytest.mark.parametrize('state,allowed', [('DRAFT', False), ('COMPLETE', True), ('LEGACY', True)])
def test_readiness_is_separate_from_login_state(state, allowed):
    with patch('app.roster_lifecycle.status', return_value={'status': state}):
        if allowed:
            require_ready(None, 'B')
        else:
            with pytest.raises(ServiceError, match='first-login'):
                require_ready(None, 'B')


def test_legacy_review_rows_are_exposed_as_completed_setup():
    with patch('app.roster_lifecycle.rows', return_value=[{'status': 'REVIEW', 'revision': 2}]):
        assert status(None, 'B') == {'status': 'COMPLETE', 'revision': 2}


def test_no_admin_privilege_from_highest_role_alone_or_disabled_account():
    with pytest.raises(ServiceError):
        authorize(None, PERSON, 'ACCESS_MANAGEMENT', 'administer', 'SYSTEM_ADMINISTRATOR')
    with patch('app.roster_lifecycle.rows', return_value=[{'active_flag': 'N'}]), pytest.raises(ServiceError):
        authorize(None, ADMIN, 'ACCESS_MANAGEMENT', 'administer', 'SYSTEM_ADMINISTRATOR')


def access_query(*, lead=False, admins=('A',), pid='B', revision=1):
    def query(c, sql, **binds):
        if 'roster_access_control' in sql:
            return [{'revision': revision}]
        if 'SELECT DISTINCT a.person_id' in sql:
            return [{'person_id': p} for p in admins]
        if 'pod_assignments' in sql:
            return [{'assignment_id': 'POD1'}] if lead else []
        if 'app_accounts' in sql:
            return [{'person_id': pid, 'active_flag': 'Y'}]
        return [{'person_id': pid}]
    return query


@pytest.mark.parametrize('changes,reason', [({'lead': True}, 'leads an active'), ({'admins': ('B',)}, 'Administrator'), ({'pid': 'A'}, 'own account'), ({'revision': 2}, 'refresh')])
def test_disable_guards_have_no_writes(changes, reason):
    db = Database()
    with patch('app.roster_lifecycle.authorize'), patch('app.roster_lifecycle.rows', side_effect=access_query(**changes)), patch('app.roster_lifecycle.execute') as write:
        with pytest.raises(ServiceError, match=reason):
            RosterLifecycle(db).access(ADMIN, 'ACC-B', AccessChange(enabled=False, revision=1, reason='Timing TBD'))
    write.assert_not_called()
    assert db.rollbacks == 1 and db.commits == 0


def test_disable_serializes_then_revokes_sessions_retaining_roles_and_assignments():
    db = Database()
    with patch('app.roster_lifecycle.authorize'), patch('app.roster_lifecycle.rows', side_effect=access_query()) as read, patch('app.roster_lifecycle.execute') as write:
        result = RosterLifecycle(db).access(ADMIN, 'ACC-B', AccessChange(enabled=False, revision=1, reason='Timing TBD'))
    assert result['revision'] == 2
    assert 'FOR UPDATE' in read.call_args_list[0].args[1]
    sql = '\n'.join(call.args[1] for call in write.call_args_list)
    assert 'revoked_at=SYSTIMESTAMP' in sql and 'ACCOUNT_DISABLED' in str(write.call_args_list)
    assert 'DELETE' not in sql and 'UPDATE pod_assignments' not in sql and 'UPDATE app_user_roles' not in sql
    assert db.commits == 1


def onboarding_query(c, sql, **binds):
    if 'SELECT status,revision' in sql:
        return [{'status': 'DRAFT', 'revision': 1}]
    if 'FROM app_accounts a' in sql:
        return [{'account_id': 'ACC-B', 'active_flag': 'Y'}]
    if 'SELECT weekly_work_hours' in sql:
        return [{'weekly_work_hours': 40, 'deliverable_experience_json': '[]'}]
    if 'TRUNC(SYSDATE) today' in sql:
        return [{'today': MON}]
    if "FROM interests WHERE assessment_type='SELF_RATED'" in sql:
        return [{'interest_id': 'SK1'}]
    if 'FROM deliverables' in sql:
        return [{'deliverable_id': 'D1'}]
    return []


def test_onboarding_writes_only_genuine_sources_and_capacity_atomically():
    db = Database()
    body = setup_body(skills=[{'skill_id': 'SK1', 'strength': 3}],
                      deliverables=[{'deliverable_id': 'D1', 'experience_level': 'SUPPORTED', 'contribution_scope': 'CONTRIBUTOR'}],
                      work=[work(), work(kind='LEAVE', title='Leave', total_hours=8)])
    with patch('app.roster_lifecycle.rows', side_effect=onboarding_query), patch('app.roster_lifecycle.execute') as write, patch('app.execution_store.execute') as clob, patch('app.roster_lifecycle.refresh') as refresh:
        result = RosterLifecycle(db).submit(PERSON, body)
    assert result == {'status': 'COMPLETE', 'revision': 2}
    sql = '\n'.join(call.args[1] for call in write.call_args_list)
    assert 'INSERT INTO person_interests' in sql and 'INSERT INTO availability' in sql
    assert 'pod_assignments' not in sql and 'allocation_pct' not in sql.lower()
    assert refresh.call_args.kwargs['commit'] is True and refresh.call_args.args[0].c is db.c
    assert 'COMPLETE' in str(clob.call_args_list) and db.commits == 1


def test_pod_claims_are_not_external_work_or_fake_assignments():
    db = Database()
    with patch('app.roster_lifecycle.rows', side_effect=onboarding_query), patch('app.roster_lifecycle.execute') as write, patch('app.execution_store.execute'), patch('app.roster_lifecycle.refresh'):
        result = RosterLifecycle(db).submit(PERSON, setup_body(work=[work(kind='POD', role_code='POD_MEMBER')]))
    assert result['status'] == 'COMPLETE'
    sql = '\n'.join(call.args[1] for call in write.call_args_list)
    assert 'INSERT INTO roster_pod_claims' in sql
    assert 'INSERT INTO availability' not in sql and 'INSERT INTO pod_assignments' not in sql


def test_capacity_failure_rolls_back_profile_submission():
    db = Database()
    with patch('app.roster_lifecycle.rows', side_effect=onboarding_query), patch('app.roster_lifecycle.execute'), patch('app.execution_store.execute'), patch('app.roster_lifecycle.refresh', side_effect=ServiceError('STALE', 'capacity', 409)):
        with pytest.raises(ServiceError):
            RosterLifecycle(db).submit(PERSON, setup_body(work=[work()]))
    assert db.rollbacks == 1 and db.commits == 0


def test_role_derived_skill_or_second_submission_cannot_write():
    for result, body in [({'status': 'COMPLETE', 'revision': 2}, setup_body()), ({'status': 'DRAFT', 'revision': 1}, setup_body(skills=[{'skill_id': 'POD_LEAD', 'strength': 5}]))]:
        with patch('app.roster_lifecycle.rows', side_effect=onboarding_query), patch('app.roster_lifecycle.status', return_value=result), patch('app.roster_lifecycle.execute') as write, patch('app.execution_store.execute') as clob:
            with pytest.raises(ServiceError):
                RosterLifecycle(Database()).submit(PERSON, body)
        write.assert_not_called()
        clob.assert_not_called()
