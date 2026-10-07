from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.accounts import AccountStore, PasswordChange, PasswordLogin, check_password, hash_password, normalize_email, session_hash
from app.auth import Actor, Permission
from app.config import Settings
from app.errors import ServiceError
from app.main import create_app


def test_password_hashes_are_salted_and_never_contain_the_password():
    password = 'MVP testing password only'
    a, b = hash_password(password), hash_password(password)
    assert a != b and password not in a
    assert check_password(password, a)
    assert not check_password('different', a)
    assert not check_password(password, 'broken')
    assert not check_password(password, a.replace('600000', '999999999'))


def test_email_normalization_and_strict_login_contract():
    assert normalize_email(' Alex.Rivera@Oracle.com ') == 'alex.rivera@oracle.com'
    with pytest.raises(ValueError):
        normalize_email('alex@example.invalid')
    with pytest.raises(ValidationError):
        PasswordLogin(email='alex@oracle.com', password='secret', role='POD_CAPTAIN')
    assert 'secret' not in repr(PasswordLogin(email='alex@oracle.com', password='secret'))


def test_password_mode_works_on_vm_without_oidc_but_not_with_persona_bypass():
    Settings(backend_env='production', backend_auth_mode='password')
    with pytest.raises(ValidationError):
        Settings(backend_auth_mode='password', staffing_demo_personas_enabled=True)


def test_only_opaque_password_sessions_are_accepted():
    token = 'Bearer aps1.' + 'a' * 43
    assert len(session_hash(token)) == 64
    for bad in (None, 'Bearer dps1.value.signature', 'Bearer local-management-secret', 'Bearer aps1.a', token + 'x'):
        with pytest.raises(ServiceError):
            session_hash(bad)


class FakeDatabase:
    def __init__(self):
        self.connection = MagicMock()
        self.committed = 0

    @contextmanager
    def write(self):
        yield self.connection
        self.committed += 1

    @contextmanager
    def read(self):
        yield self.connection

    def close(self):
        pass


@pytest.fixture
def store():
    value = AccountStore(FakeDatabase(), Settings(backend_auth_mode='password'))
    value._dummy_hash = hash_password('irrelevant dummy secret')
    return value


def account(**changes):
    return {'account_id': 'ACC-1', 'identity_subject': 'acct:ACC-1', 'password_hash': hash_password('shared-test-password'),
            'active_flag': 'Y', 'failed_attempts': 0, 'locked': 0, **changes}


def test_successful_login_stores_only_session_digest_and_resets_attempts(store):
    with patch('app.accounts.rows', side_effect=[[account()], [{'person_id': 'P-001', 'role_code': 'POD_MEMBER'}]]), patch('app.accounts.execute') as sql:
        result = store.login(PasswordLogin(email='alex@oracle.com', password='shared-test-password'))
    assert result['expires_in'] == 3600
    assert result['access_token'].startswith('aps1.')
    assert result['access_token'] not in str(sql.call_args_list)
    assert session_hash('Bearer ' + result['access_token']) in str(sql.call_args_list)
    assert store.database.committed == 1
    assert "SYSTIMESTAMP+NUMTODSINTERVAL(:seconds,'SECOND')" in sql.call_args_list[0].args[1]
    assert 'last_activity_at' in sql.call_args_list[0].args[1]
    assert sql.call_args_list[0].kwargs['seconds'] == 3600


def test_failed_login_commits_attempt_counter_without_enumerating_accounts(store):
    errors = []
    for result in ([], [account()], [account(active_flag='N')], [account(locked=1)]):
        with patch('app.accounts.rows', return_value=result), patch('app.accounts.execute'), pytest.raises(ServiceError) as error:
            store.login(PasswordLogin(email='alex@oracle.com', password='wrong'))
        errors.append((error.value.code, error.value.message))
    assert len(set(errors)) == 1
    assert store.database.committed == 4


def test_login_cannot_issue_session_without_role_mapping(store):
    with patch('app.accounts.rows', side_effect=[[account()], []]), patch('app.accounts.execute') as sql, pytest.raises(ServiceError):
        store.login(PasswordLogin(email='alex@oracle.com', password='shared-test-password'))
    assert 'INSERT INTO app_sessions' not in str(sql.call_args_list)


def test_session_resolution_checks_expiry_revocation_person_and_account(store):
    with patch('app.accounts.rows', return_value=[{'identity_subject': 'acct:ACC-1'}]) as read:
        assert store.subject('Bearer aps1.' + 'a' * 43) == 'acct:ACC-1'
    query = read.call_args.args[1]
    assert 's.revoked_at IS NULL' in query and 's.expires_at>SYSTIMESTAMP' in query
    assert 's.last_activity_at>SYSTIMESTAMP-NUMTODSINTERVAL(:idleSeconds' in query
    assert 's.created_at>SYSTIMESTAMP-NUMTODSINTERVAL(:absoluteSeconds' in query
    assert "a.active_flag='Y'" in query and "p.active_flag='Y'" in query
    with patch('app.accounts.rows', return_value=[]), pytest.raises(ServiceError):
        store.subject('Bearer aps1.' + 'a' * 43)


def test_logout_revokes_the_same_digest(store):
    with patch('app.accounts.execute') as sql:
        assert store.logout('Bearer aps1.' + 'a' * 43) == {'ok': True}
    assert sql.call_args.kwargs['token'] == session_hash('Bearer aps1.' + 'a' * 43)
    assert 'revoked_at=SYSTIMESTAMP' in sql.call_args.args[1]


def test_activity_renews_only_a_live_session_and_status_reports_both_deadlines(store):
    now = datetime.now(timezone.utc)
    absolute = (now + timedelta(hours=1)).isoformat()
    idle = (now + timedelta(minutes=5)).isoformat()
    store.database.connection.cursor.return_value.__enter__.return_value.rowcount = 1
    with patch('app.accounts.rows', return_value=[{
        'absolute_expires_at': absolute,
        'idle_expires_at': idle,
    }]):
        status = store.record_activity('Bearer aps1.' + 'a' * 43)
    assert status['absolute_expires_at'] == absolute
    assert status['idle_expires_at'] == idle
    statement = store.database.connection.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
    assert 's.revoked_at IS NULL' in statement
    assert 's.created_at>SYSTIMESTAMP-NUMTODSINTERVAL(:absoluteSeconds' in statement
    assert 's.last_activity_at>SYSTIMESTAMP-NUMTODSINTERVAL(:idleSeconds' in statement
    store.database.connection.cursor.return_value.__enter__.return_value.rowcount = 0
    with pytest.raises(ServiceError) as failure:
        store.record_activity('Bearer aps1.' + 'a' * 43)
    assert failure.value.code == 'UNAUTHENTICATED'


def test_password_change_replaces_hash_audits_without_secrets_and_revokes_every_session(store):
    existing = account(password_hash=hash_password('CurrentPass1!'))
    body = PasswordChange(current_password='CurrentPass1!', new_password='Replacement2$')
    assert 'CurrentPass1!' not in repr(body) and 'Replacement2$' not in repr(body)
    with patch('app.accounts.rows', return_value=[existing]) as read, patch('app.accounts.execute') as sql:
        assert store.change_password('Bearer aps1.' + 'a' * 43, body) == {'ok': True, 'sessions_revoked': True}
    statements = [(call.args[1], call.kwargs) for call in sql.call_args_list]
    account_update = next(item for item in statements if 'UPDATE app_accounts SET password_hash' in item[0])
    assert check_password('Replacement2$', account_update[1]['passwordHash'])
    assert not check_password('CurrentPass1!', account_update[1]['passwordHash'])
    assert any('UPDATE app_sessions SET revoked_at=SYSTIMESTAMP' in statement for statement, _ in statements)
    audit = next(item for item in statements if 'INSERT INTO audit_events' in item[0])
    assert 'PASSWORD_CHANGED' in audit[0] and audit[1]['actor'] == existing['identity_subject']
    assert all('CurrentPass1!' not in str(item) and 'Replacement2$' not in str(item) for item in statements)
    assert read.call_args.kwargs['token'] == session_hash('Bearer aps1.' + 'a' * 43)
    assert store.database.committed == 1


def test_password_change_rejects_wrong_weak_and_reused_passwords_before_writing(store):
    existing = account(password_hash=hash_password('CurrentPass1!'))
    cases = [
        (PasswordChange(current_password='wrong', new_password='Replacement2$'), 'CURRENT_PASSWORD_INCORRECT'),
        (PasswordChange(current_password='CurrentPass1!', new_password='weak'), 'WEAK_PASSWORD'),
        (PasswordChange(current_password='CurrentPass1!', new_password='CurrentPass1!'), 'PASSWORD_REUSED'),
    ]
    for body, code in cases:
        with patch('app.accounts.rows', return_value=[existing]), patch('app.accounts.execute') as sql, pytest.raises(ServiceError) as error:
            store.change_password('Bearer aps1.' + 'a' * 43, body)
        assert error.value.code == code
        sql.assert_not_called()


def test_password_api_uses_current_role_mapping_not_browser_claims():
    accounts = MagicMock()
    accounts.subject.return_value = 'acct:ACC-1'
    accounts.login.return_value = {'access_token': 'aps1.' + 'a' * 43, 'expires_in': 28800}
    accounts.change_password.return_value = {'ok': True, 'sessions_revoked': True}
    authorization = MagicMock()
    authorization.resolve.return_value = Actor('acct:ACC-1', 'P-001', frozenset({'POD_MEMBER'}),
        (Permission('POD_MEMBER', 'TEAM_SKILLS', 'OWN', frozenset({'view'})),))
    verifier = MagicMock()
    client = TestClient(create_app(Settings(backend_auth_mode='password'), database=FakeDatabase(),
                                  accounts=accounts, authorization=authorization, verifier=verifier))
    result = client.get('/v1/me', headers={'authorization': 'Bearer aps1.' + 'a' * 43, 'x-staffing-role': 'SYSTEM_ADMINISTRATOR'})
    assert result.status_code == 200 and result.json()['roles'] == ['POD_MEMBER']
    verifier.subject.assert_not_called()
    assert client.get('/v1/local-personas', headers={'authorization': 'Bearer legacy-control'}).status_code == 404
    assert client.post('/v1/local-personas/session', json={'person_id': 'P-009', 'role_code': 'POD_CAPTAIN'}).status_code == 404
    invalid = client.post('/v1/auth/password/login', json={'email': 'alex@oracle.com', 'password': 'do-not-echo', 'person_id': 'P-009'})
    assert invalid.status_code == 422 and 'do-not-echo' not in invalid.text
    changed = client.post('/v1/auth/password/change', headers={'authorization': 'Bearer aps1.' + 'a' * 43},
                          json={'current_password': 'current-secret', 'new_password': 'Replacement2$'})
    assert changed.status_code == 200 and changed.json()['sessions_revoked'] is True
    accounts.change_password.assert_called_once()


def test_login_endpoint_is_disabled_in_other_modes():
    client = TestClient(create_app(Settings(), database=FakeDatabase()))
    response = client.post('/v1/auth/password/login', json={'email': 'alex@oracle.com', 'password': 'anything'})
    assert response.status_code == 404
