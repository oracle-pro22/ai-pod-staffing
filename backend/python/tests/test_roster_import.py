"""Hermetic Phase 5/6 DML + password-flow checks; never connect to Oracle.

SQLite runs actual application inserts/queries/rollback. Oracle metadata, locks,
sequence and archival checks have separate tests and read-only deployment checks.
"""
import json
import re
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import roster_import as imp, roster_release as release
from app.accounts import AccountStore, PasswordLogin
from app.errors import ServiceError
from app.roster_audit import ARCHIVE_TABLES, digest, source_summary
from app.roster_reset import native_name, run
from app.storage import rows

BATCH = 'roster4-test'
PASSWORD = 'test-only-password'


def source():
    people = []
    for i in range(25):
        roles = ['POD_LEAD']
        if i != 3:  # Explicit Captain + Lead only, like Amy's workbook exception.
            roles.append('POD_MEMBER')
        if i < 8:
            roles.append('POD_CAPTAIN')
        if i < 3:
            roles.append('SYSTEM_ADMINISTRATOR')
        people.append(dict(name=f'Employee {i:02}', email=f'employee{i:02}@oracle.com', manager='Manager',
                           roles=roles, account_enabled=i < 18, source_row=i+2,
                           initial_daily_hours=8, initial_weekly_hours=40, onboarding_required=True))
    return dict(source_sha256='a'*64, tester_ignored=True, people=people)


def plan_for(s=None):
    s = s or source()
    p = dict(format_version=1, batch=BATCH, source_sha256=s['source_sha256'], archive_confirmation='old',
             people=imp.targets(s, 32, BATCH), summary=source_summary(s))
    return {**p, 'confirmation': digest(p)}


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.inner = connection.db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.inner.close()

    def setinputsizes(self, **kwargs):
        pass

    def execute(self, sql, binds=None):
        if 'person_id_seq.NEXTVAL' in sql:
            self.connection.sequence += 1
            sql, binds = 'SELECT :n n', {'n': self.connection.sequence}
        sql = re.sub(r'FOR UPDATE(?: WAIT 5)?', '', sql)
        sql = sql.replace('TRUNC(SYSDATE)', "date('now')")
        sql = sql.replace("SYSTIMESTAMP+NUMTODSINTERVAL(:seconds,'SECOND')", "datetime('now','+1 hour')")
        sql = sql.replace("SYSTIMESTAMP+INTERVAL '1' MINUTE", "datetime('now','+1 minute')")
        sql = sql.replace('SYSTIMESTAMP', "datetime('now')")
        self.inner.execute(sql, binds or {})
        return self

    @property
    def description(self):
        return self.inner.description

    @property
    def rowcount(self):
        return self.inner.rowcount

    def fetchall(self):
        return self.inner.fetchall()


class Database:
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.sequence = 31

    def cursor(self):
        return Cursor(self)

    @contextmanager
    def write(self):
        with self.db:
            yield self

    @contextmanager
    def read(self):
        yield self


@pytest.fixture
def db():
    d = Database()
    d.db.executescript("""
        CREATE TABLE people(person_id TEXT PRIMARY KEY, full_name TEXT, initials TEXT, job_title TEXT, location TEXT,
          weekly_work_hours INTEGER,email_address TEXT,external_identity_subject TEXT,allocation_pct INTEGER,active_pods INTEGER,
          active_flag TEXT,staffing_eligible_flag TEXT,skills_version INTEGER,deliverable_experience_json TEXT,staffing_seed_batch TEXT);
        CREATE TABLE app_accounts(account_id TEXT PRIMARY KEY,person_id TEXT UNIQUE REFERENCES people,identity_subject TEXT UNIQUE,
          login_email TEXT UNIQUE,password_hash TEXT,active_flag TEXT,created_by TEXT,failed_attempts INTEGER DEFAULT 0,locked_until TEXT);
        CREATE TABLE app_user_roles(identity_subject TEXT,role_code TEXT,person_id TEXT REFERENCES people,active_flag TEXT,
          effective_from TEXT,effective_to TEXT,assigned_by TEXT,PRIMARY KEY(identity_subject,role_code));
        CREATE TABLE roster_onboarding(person_id TEXT PRIMARY KEY REFERENCES people,status TEXT);
        CREATE TABLE roster_reset_runs(batch_id TEXT PRIMARY KEY,status TEXT,metadata_json TEXT);
        CREATE TABLE app_sessions(token_hash TEXT PRIMARY KEY,account_id TEXT REFERENCES app_accounts,expires_at TEXT,revoked_at TEXT);
        CREATE TABLE app_roles(role_code TEXT PRIMARY KEY,active_flag TEXT);
        CREATE TABLE roster_pod_claims(person_id TEXT REFERENCES people,status TEXT);
        CREATE TABLE staffing_runtime(runtime_id INTEGER,agents_enabled TEXT,notifications_enabled TEXT);
        INSERT INTO staffing_runtime VALUES(1,'N','N');
    """)
    existing = {'PEOPLE','APP_ACCOUNTS','APP_USER_ROLES','ROSTER_ONBOARDING','APP_SESSIONS','ROSTER_POD_CLAIMS'}
    for table in set(ARCHIVE_TABLES)-existing:
        d.db.execute(f'CREATE TABLE {table}(id TEXT)')
    for role in imp.EXPECTED_ROLES:
        d.db.execute('INSERT INTO app_roles VALUES(?,?)', (role, 'Y'))
    meta = dict(batch=BATCH, confirmation='old', rehearsal={'fingerprint': 'old'},
                archives={t: native_name(BATCH, 'B', i) for i,t in enumerate(sorted(ARCHIVE_TABLES))},
                shadows={t: native_name(BATCH, 'T', i) for i,t in enumerate(sorted(ARCHIVE_TABLES))})
    d.db.execute(f"CREATE TABLE {meta['archives']['PEOPLE']}(person_id TEXT)")
    d.db.execute(f"INSERT INTO {meta['archives']['PEOPLE']} VALUES('P-031')")
    d.db.execute('INSERT INTO roster_reset_runs VALUES(?,?,?)', (BATCH, 'RESET', json.dumps(meta)))
    d.db.commit()
    with patch.object(imp, 'stopped'), patch.object(imp, 'check_schema'), patch.object(imp, 'verify_archive'), \
         patch.object(imp, 'verify_live'), patch.object(imp, 'lock_tables'), patch.object(imp, 'protected_unchanged'), \
         patch('app.accounts.ITERATIONS', 1000), patch.object(release, 'check_schema'), \
         patch.object(release, 'verify_archive'), patch.object(release, 'stopped'):
        yield d
    d.db.close()


def imported(db):
    plan = imp.build_plan(db, source(), BATCH)
    assert plan == plan_for()
    with db.write() as c:
        result = imp.apply(c, source(), plan, 'test-operator', PASSWORD)
    return plan, result


def test_atomic_import_exact_accounts_roles_first_login_and_journal(db):
    plan, result = imported(db)
    assert result['status'] == 'IMPORTED'
    assert result['accounts'] == 25 and result['enabled'] == 18 and result['disabled'] == 7
    assert result['onboarding'] == {'DRAFT': 25, 'COMPLETE': 0}
    assert result['passwords_verified'] and result['writes'] == 136
    assert db.sequence > 56
    _, archive = run(db, BATCH)
    assert archive['roster_import']['manifest'] == plan
    assert PASSWORD not in json.dumps(archive)
    assert len({r['password_hash'] for r in rows(db, 'SELECT password_hash FROM app_accounts')}) == 25
    assert rows(db, "SELECT role_code FROM app_user_roles WHERE person_id='P-035' ORDER BY role_code") == [
        {'role_code': 'POD_CAPTAIN'}, {'role_code': 'POD_LEAD'}]


def test_imported_real_password_flow_enabled_and_disabled_accounts(db):
    plan, _ = imported(db)
    store = AccountStore(db, SimpleNamespace(backend_auth_mode='password', staffing_session_hours=1))
    for person in plan['people']:
        body = PasswordLogin(email=person['email'], password=PASSWORD)
        if person['account_enabled']:
            result = store.login(body)
            assert store.subject('Bearer '+result['access_token']) == person['identity_subject']
        else:
            with pytest.raises(ServiceError) as failure:
                store.login(body)
            assert failure.value.code == 'INVALID_CREDENTIALS'
    assert rows(db, 'SELECT COUNT(*) n FROM app_sessions') == [{'n': 18}]


def test_idempotent_retry_does_not_duplicate_accounts_or_change_hashes(db):
    plan, _ = imported(db)
    before = rows(db, 'SELECT * FROM app_accounts')
    with db.write() as c:
        result = imp.apply(c, source(), plan, 'retry', PASSWORD)
    assert result['already_imported'] and result['writes'] == 0
    assert rows(db, 'SELECT * FROM app_accounts') == before


@pytest.mark.parametrize('failure_point', ['accounts', 'verification', 'journal'])
def test_error_rolls_back_people_accounts_grants_enrollment_and_journal(db, failure_point):
    original = imp.execute
    def fail_account(c, sql, **binds):
        if 'INSERT INTO app_accounts' in sql and binds['person'] == 'P-034':
            raise RuntimeError('simulated insert failure')
        original(c, sql, **binds)
    target = {'accounts': 'execute', 'verification': 'protected_unchanged', 'journal': 'save'}[failure_point]
    with patch.object(imp, target, side_effect=fail_account if target == 'execute' else RuntimeError('simulated failure')):
        with pytest.raises(RuntimeError), db.write() as c:
            imp.apply(c, source(), plan_for(), 'test', PASSWORD)
    for table in imp.IMPORTED_TABLES:
        assert rows(db, f'SELECT COUNT(*) n FROM {table}') == [{'n': 0}]
    assert 'roster_import' not in run(db, BATCH)[1]


@pytest.mark.parametrize('state', ['PREPARING','ARCHIVED','REHEARSED','RESTORED'])
def test_apply_requires_reset_and_never_deletes_data(db, state):
    db.db.execute('UPDATE roster_reset_runs SET status=?', (state,))
    db.db.commit()
    with pytest.raises(ServiceError, match='RESET'):
        imp.apply(db, source(), plan_for(), 'test', PASSWORD)
    assert rows(db, 'SELECT COUNT(*) n FROM people') == [{'n': 0}]


@pytest.mark.parametrize('kind', ['checksum','workbook','extra_role','access'])
def test_manifest_and_source_drift_block_import(tmp_path, kind):
    s, p = source(), plan_for()
    if kind == 'checksum':
        p['confirmation'] = 'wrong'
    elif kind == 'workbook':
        s['source_sha256'] = 'new-source'
    else:
        if kind == 'extra_role':
            p['people'][3]['roles'].append('POD_MEMBER')
        else:
            p['people'][24]['account_enabled'] = True
        p['confirmation'] = digest({k:v for k,v in p.items() if k != 'confirmation'})
    path = tmp_path/'plan.json'
    path.write_text(json.dumps(p), encoding='utf-8')
    with pytest.raises(ServiceError):
        imp.load_plan(path, s, BATCH)


def test_fresh_subjects_for_different_batches_and_manifest_round_trip(tmp_path):
    s, p = source(), plan_for()
    assert imp.targets(s, 32, 'roster4-another')[0]['identity_subject'] != p['people'][0]['identity_subject']
    path = tmp_path/'plan.json'
    path.write_text(json.dumps(p), encoding='utf-8')
    assert imp.load_plan(path, s, BATCH) == p


@pytest.mark.parametrize('change', ['access','role','enrollment','old_people','seed','claims'])
def test_post_import_verification_detects_unexpected_data(db, change):
    plan, _ = imported(db)
    sql = {'access': "UPDATE app_accounts SET active_flag='Y' WHERE person_id='P-056'",
           'role': "INSERT INTO app_user_roles VALUES('acct:unexpected','POD_MEMBER','P-035','Y',date('now'),NULL,'test')",
           'enrollment': "DELETE FROM roster_onboarding WHERE person_id='P-032'",
           'old_people': "INSERT INTO people(person_id) VALUES('P-001')",
           'seed': "UPDATE people SET staffing_seed_batch='wrong' WHERE person_id='P-032'",
           'claims': "INSERT INTO roster_pod_claims VALUES('P-032','PENDING')"}[change]
    db.db.execute(sql)
    with pytest.raises(ServiceError):
        imp.verify_import(db, plan, run(db, BATCH)[1])


def test_release_self_reported_pod_work_does_not_block_access(db):
    plan, _ = imported(db)
    initial = release.inspect(db, plan)
    assert initial['writes'] == 0 and initial['onboarding_complete_enabled'] == 0
    assert initial['enabled_waiting_for_setup'] == 18
    assert initial['browser_acceptance'] == 'NOT_AUTOMATICALLY_VERIFIED'
    db.db.execute("UPDATE roster_onboarding SET status='REVIEW' WHERE person_id='P-032'")
    db.db.execute("INSERT INTO roster_pod_claims VALUES('P-032','PENDING')")
    db.db.execute("UPDATE roster_onboarding SET status='COMPLETE' WHERE person_id IN ('P-033','P-056')")
    after = release.inspect(db, plan, initial=False)
    assert after['self_reported_pod_entries'] == 1
    assert after['onboarding_complete_enabled'] == 2  # legacy REVIEW is ready; disabled COMPLETE stays excluded
    assert after['ready_role_counts']['POD_CAPTAIN'] == 2
    db.db.execute("UPDATE roster_onboarding SET status='COMPLETE' WHERE person_id='P-032'")
    after = release.inspect(db, plan, initial=False)
    assert after['onboarding_complete_enabled'] == 2


def test_cli_apply_requires_stopped_commit_operator_before_database(monkeypatch):
    monkeypatch.setattr('sys.argv', ['roster_import','apply','--workbook','unused.xlsx','--batch',BATCH,'--manifest','unused.json'])
    with patch('app.database.OracleDatabase') as database, pytest.raises(SystemExit):
        imp.main()
    database.assert_not_called()
