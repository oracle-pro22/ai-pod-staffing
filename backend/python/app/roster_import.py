"""Real roster Phase 5. Plan/verify are read-only; apply requires an already RESET batch.

No reset, grant, trigger changes, agent calls, notifications or service actions.
One transaction imports the roster and records completion in the existing journal.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.accounts import check_password, execute, hash_password
from app.errors import ServiceError
from app.execution_store import execute as clob_execute
from app.onboarding_schema import verify as verify_onboarding_schema
from app.roster_audit import ARCHIVE_TABLES, PROTECTED_TABLES, digest, read_workbook, source_summary
from app.roster_reset import (
    columns, constraints, fingerprint, lock_tables, maintenance_lock, run, save,
    stopped, trigger_metadata, verify_archive, verify_live,
)
from app.roster_schema import verify as verify_role_schema
from app.storage import document, rows

IMPORTED_TABLES = {'PEOPLE', 'APP_ACCOUNTS', 'APP_USER_ROLES', 'ROSTER_ONBOARDING'}
EXPECTED_ROLES = {'SYSTEM_ADMINISTRATOR': 3, 'POD_CAPTAIN': 8, 'POD_LEAD': 25, 'POD_MEMBER': 24}


def require(ok, message):
    if not ok:
        raise ServiceError('ROSTER_IMPORT_STOPPED', message, 409)


def validate_source(source):
    summary = source_summary(source)
    require((summary['accounts'], summary['enabled'], summary['disabled']) == (25, 18, 7),
            'Workbook differs from the approved 25 people / 18 enabled / 7 disabled plan.')
    require(summary['role_grants'] == EXPECTED_ROLES, 'Workbook role totals differ from the reviewed roster.')
    require(any(p['account_enabled'] and 'SYSTEM_ADMINISTRATOR' in p['roles'] for p in source['people']),
            'An enabled real Administrator is required.')
    for p in source['people']:
        require(len(p['name']) <= 120 and len(p['email']) <= 255 and len(p['manager']) <= 255,
                'A workbook identity exceeds the reviewed column limits.')
    return summary


def targets(source, first_id, batch):
    require(1 <= first_id <= 999999-len(source['people']), 'Person number is outside the reviewed range.')
    result = []
    for i, p in enumerate(sorted(source['people'], key=lambda item: item['email'])):
        identity = uuid5(NAMESPACE_URL, 'ai-pod-roster-v1/'+batch+'/'+source['source_sha256']+'/'+p['email']).hex
        result.append({**p, 'person_id': f'P-{first_id+i:03}', 'account_id': 'ACC-'+identity,
                       'identity_subject': 'acct:ACC-'+identity})
    return result


def check_schema(c):
    verify_onboarding_schema(c)
    verify_role_schema(c)
    active = {r['role_code'] for r in rows(c, "SELECT role_code FROM app_roles WHERE active_flag='Y'")}
    require(set(EXPECTED_ROLES) <= active, 'Required role definitions are missing or inactive.')
    require(rows(c, """SELECT role_code FROM role_permissions WHERE role_code='SYSTEM_ADMINISTRATOR'
        AND resource_code='ACCESS_MANAGEMENT' AND can_view='Y' AND can_administer='Y' AND access_scope='FULL'"""),
        'Administrator access-management permission must be configured before import.')
    sequence = rows(c, "SELECT increment_by,cycle_flag FROM user_sequences WHERE sequence_name='PERSON_ID_SEQ'")
    require(sequence == [{'increment_by': 1, 'cycle_flag': 'N'}], 'Person ID sequence must be present, increasing by one and non-cycling.')


def build_plan(c, source, batch):
    summary = validate_source(source)
    stopped(c)
    check_schema(c)
    state, archive = run(c, batch)
    require(state in ('REHEARSED', 'RESET') and 'roster_import' not in archive,
            'Use the rehearsed batch before import, or inspect the completed import.')
    require(archive.get('rehearsal', {}).get('fingerprint') == archive['confirmation'], 'Recovery rehearsal is missing.')
    verify_archive(c, archive)
    verify_live(c, archive, empty=state == 'RESET')
    archived_ids = rows(c, f"SELECT person_id FROM {archive['archives']['PEOPLE']}")
    require(all(re.fullmatch(r'P-\d+', p['person_id']) for p in archived_ids), 'Review nonuniform old person IDs before import.')
    first = max((int(p['person_id'][2:]) for p in archived_ids), default=0)+1
    payload = {'format_version': 1, 'batch': batch, 'source_sha256': source['source_sha256'],
               'archive_confirmation': archive['confirmation'], 'people': targets(source, first, batch), 'summary': summary}
    return {**payload, 'confirmation': digest(payload)}


def load_plan(path, source, batch):
    path = Path(path)
    require(path.stat().st_size <= 1000000, 'Import manifest exceeds size limit.')
    plan = json.loads(path.read_text(encoding='utf-8'))
    require(set(plan) == {'format_version', 'batch', 'source_sha256', 'archive_confirmation', 'people', 'summary', 'confirmation'},
            'Unexpected manifest format.')
    require(plan['format_version'] == 1 and plan['batch'] == batch and plan['source_sha256'] == source['source_sha256'],
            'Workbook, batch or manifest version changed. Prepare a fresh plan.')
    require(digest({k: v for k, v in plan.items() if k != 'confirmation'}) == plan['confirmation'], 'Manifest checksum does not match.')
    validate_source(source)
    require(plan['people'] and re.fullmatch(r'P-\d+', plan['people'][0]['person_id']), 'Invalid target IDs.')
    require(plan['people'] == targets(source, int(plan['people'][0]['person_id'][2:]), batch)
            and plan['summary'] == source_summary(source), 'Manifest rows differ from the authoritative workbook.')
    return plan


def protected_unchanged(c, archive):
    require(constraints(c) == archive['keys'] and trigger_metadata(c) == archive['triggers'],
            'Schema constraints or maintenance guards changed.')
    for table in PROTECTED_TABLES:
        require(columns(c, table) == archive['columns'][table], 'Protected table structure changed.')
        require(fingerprint(c, table, archive['columns'][table], archive.get('json_columns', {}).get(table, ())) == archive['fingerprints'][table],
                f'Protected data changed: {table}.')


def verify_import(c, plan, archive, password=None, initial=True):
    """Compare every identity/grant, not only totals. Never print password/session material."""
    expected = {p['person_id']: p for p in plan['people']}
    people = rows(c, """SELECT person_id,full_name,email_address,external_identity_subject,weekly_work_hours,
        active_flag,staffing_eligible_flag,staffing_seed_batch,deliverable_experience_json,allocation_pct,active_pods FROM people""")
    accounts = rows(c, 'SELECT account_id,person_id,identity_subject,login_email,active_flag,password_hash FROM app_accounts')
    grants = rows(c, """SELECT person_id,identity_subject,role_code,active_flag,
        CASE WHEN effective_from<=TRUNC(SYSDATE) AND (effective_to IS NULL OR effective_to>=TRUNC(SYSDATE)) THEN 1 ELSE 0 END effective
        FROM app_user_roles""")
    setup = rows(c, 'SELECT person_id,status FROM roster_onboarding')
    require({r['person_id'] for r in people} == set(expected) and len(people) == len(expected), 'People differ from the import manifest.')
    require(len(accounts) == len(expected) and {r['person_id'] for r in accounts} == set(expected), 'Account identities are incomplete or duplicated.')
    for p in people:
        e = expected[p['person_id']]
        require((p['full_name'], p['email_address'], p['external_identity_subject'], p['weekly_work_hours'], p['active_flag']) ==
                (e['name'], e['email'], e['identity_subject'], 40, 'Y'), 'A person differs from the reviewed identity/contract.')
        require(p['staffing_seed_batch'] == plan['batch'] and p['staffing_eligible_flag'] == 'Y',
                'Person import provenance or eligibility flag changed.')
        if initial:
            require(document(p['deliverable_experience_json'] or '[]') == [] and p['allocation_pct'] == p['active_pods'] == 0,
                    'Unexpected initial employee assessments/workload.')
    for a in accounts:
        e = expected[a['person_id']]
        require((a['account_id'], a['identity_subject'], a['login_email'], a['active_flag']) ==
                (e['account_id'], e['identity_subject'], e['email'], 'Y' if e['account_enabled'] else 'N'),
                'Account access differs from the approved roster.')
        if password is not None:
            require(check_password(password, a['password_hash']), 'An account password failed verification.')
    desired = {(p['person_id'], p['identity_subject'], role, 'Y', 1) for p in expected.values() for role in p['roles']}
    actual = {(g['person_id'], g['identity_subject'], g['role_code'], g['active_flag'], g['effective']) for g in grants}
    require(actual == desired and len(grants) == len(desired), 'Role grants differ from the Excel; no role inheritance is allowed.')
    require(len(setup) == len(expected) and {r['person_id'] for r in setup} == set(expected), 'Missing first-login enrollment.')
    require(all(r['status'] in (('DRAFT',) if initial else ('DRAFT', 'REVIEW', 'COMPLETE')) for r in setup), 'Unexpected onboarding state.')
    if initial:
        for table in set(ARCHIVE_TABLES)-IMPORTED_TABLES:
            require(rows(c, f'SELECT COUNT(*) n FROM {table}')[0]['n'] == 0, f'Unexpected initial business records in {table}.')
        protected_unchanged(c, archive)
    return {'verified': True, 'accounts': len(accounts), 'enabled': sum(a['active_flag'] == 'Y' for a in accounts),
            'disabled': sum(a['active_flag'] == 'N' for a in accounts), 'exact_roles': True,
            # REVIEW is retained only as a legacy database value. It is treated
            # as completed setup and is never a separate release state.
            'onboarding': {'DRAFT': sum(r['status'] == 'DRAFT' for r in setup),
                           'COMPLETE': sum(r['status'] in ('COMPLETE', 'REVIEW') for r in setup)},
            'initial': initial, 'passwords_verified': password is not None, 'writes': 0}


def apply(c, source, plan, operator, password):
    stopped(c)
    check_schema(c)
    state, archive = run(c, plan['batch'])
    require(state == 'RESET', 'Archive must be RESET before import. This command never resets data.')
    require(plan['archive_confirmation'] == archive['confirmation'], 'Archive confirmation changed.')
    if 'roster_import' in archive:
        require(archive['roster_import']['confirmation'] == plan['confirmation'], 'Another import already used this batch.')
        result = verify_import(c, plan, archive, password)
        return {**result, 'already_imported': True}
    require(build_plan(c, source, plan['batch']) == plan, 'Import no longer matches its reviewed plan.')
    lock_tables(c, archive['archives'].values())
    verify_live(c, archive, empty=True)
    verify_archive(c, archive)
    # Each account uses a fresh salt. Password plaintext never enters the journal/report.
    hashes = {p['person_id']: hash_password(password) for p in plan['people']}
    high = max(int(p['person_id'][2:]) for p in plan['people'])
    # Sequence advances are not transactional. Consume only this application's
    # sequence so future person creation cannot reuse our explicit numeric IDs.
    for _ in range(10000):
        if rows(c, 'SELECT person_id_seq.NEXTVAL n FROM dual')[0]['n'] > high:
            break
    else:
        require(False, 'Person ID sequence needs reviewed synchronization.')
    for p in plan['people']:
        initials = ''.join(part[0] for part in p['name'].split()[:2]).upper()
        clob_execute(c, """INSERT INTO people(person_id,full_name,initials,job_title,location,weekly_work_hours,
            email_address,external_identity_subject,allocation_pct,active_pods,active_flag,staffing_eligible_flag,
            skills_version,deliverable_experience_json,staffing_seed_batch)
            VALUES(:pid,:name,:initials,'Not provided','Not provided',40,:email,:subject,0,0,'Y','Y',0,:experience,:batch)""",
            {'pid': p['person_id'], 'name': p['name'], 'initials': initials, 'email': p['email'], 'subject': p['identity_subject'],
             'experience': '[]', 'batch': plan['batch']}, ('experience',))
        execute(c, """INSERT INTO app_accounts(account_id,person_id,identity_subject,login_email,password_hash,active_flag,created_by)
            VALUES(:account,:person,:subject,:email,:password,:active,:operator)""", account=p['account_id'],
            person=p['person_id'], subject=p['identity_subject'], email=p['email'], password=hashes[p['person_id']],
            active='Y' if p['account_enabled'] else 'N', operator=operator)
        for role in p['roles']:
            execute(c, """INSERT INTO app_user_roles(identity_subject,role_code,person_id,active_flag,effective_from,assigned_by)
                VALUES(:subject,:role,:person,'Y',TRUNC(SYSDATE),:operator)""", subject=p['identity_subject'],
                role=role, person=p['person_id'], operator=operator)
        execute(c, "INSERT INTO roster_onboarding(person_id,status) VALUES(:pid,'DRAFT')", pid=p['person_id'])
    result = verify_import(c, plan, archive, password)
    archive['roster_import'] = {'confirmation': plan['confirmation'], 'source_sha256': source['source_sha256'],
                                'operator': operator, 'manifest': plan, 'status': 'IMPORTED'}
    save(c, archive, 'RESET')  # preserve the original recovery journal/state contract
    return {**result, 'writes': 3*len(plan['people'])+sum(len(p['roles']) for p in plan['people'])+1,
            'status': 'IMPORTED', 'agents_enabled': False, 'notifications_enabled': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply', 'verify'])
    parser.add_argument('--env-file', default='.env')
    parser.add_argument('--workbook', required=True)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--operator', default='')
    parser.add_argument('--confirmation', default='')
    parser.add_argument('--services-stopped', action='store_true')
    parser.add_argument('--commit', action='store_true')
    args = parser.parse_args()
    if args.action == 'apply' and (not args.commit or not args.services_stopped or not args.operator.strip() or len(args.operator) > 255):
        parser.error('Apply requires --commit, --services-stopped and a named --operator.')
    from app.config import Settings
    from app.database import OracleDatabase
    db = None
    try:
        source = read_workbook(args.workbook)
        validate_source(source)
        settings = Settings(_env_file=args.env_file)
        require(settings.backend_auth_mode == 'password' and not settings.staffing_demo_personas_enabled, 'Use password mode with demo personas disabled.')
        password = settings.staffing_mvp_default_password.get_secret_value() if settings.staffing_mvp_default_password else ''
        password_ready = 8 <= len(password) <= 1024
        db = OracleDatabase(settings)
        if args.action == 'plan':
            require(not Path(args.manifest).exists(), 'Manifest exists; use a new filename instead of overwriting it.')
            with db.read() as c:
                plan = build_plan(c, source, args.batch)
            path = Path(args.manifest)
            require(path.parent.is_dir(), 'Create the local manifest directory first.')
            with path.open('x', encoding='utf-8') as out:
                json.dump(plan, out, indent=2)
            result = {'manifest': str(path), 'confirmation': plan['confirmation'], 'summary': plan['summary'],
                      'password_configured': password_ready, 'database_writes': 0, 'reset_performed': False}
        else:
            plan = load_plan(args.manifest, source, args.batch)
            if args.action == 'apply':
                require(password_ready, 'Set STAFFING_MVP_DEFAULT_PASSWORD to the agreed 8–1024 character MVP password in Python .env.')
                require(args.confirmation == plan['confirmation'], 'Supply the exact reviewed import confirmation, not the archive fingerprint.')
                with db.write() as c, maintenance_lock(c):
                    result = apply(c, source, plan, args.operator.strip(), password)
                    c.commit()
            else:
                with db.read() as c:
                    _, archive = run(c, args.batch)
                    require(archive.get('roster_import', {}).get('confirmation') == plan['confirmation'], 'No matching committed import journal.')
                    result = verify_import(c, plan, archive)
        print(json.dumps(result, indent=2))
        return 0
    except ServiceError as error:
        print(json.dumps({'error': error.code, 'message': error.message, 'keep_services_stopped': True}), file=sys.stderr)
    except Exception:
        print(json.dumps({'error': 'ROSTER_IMPORT_FAILED', 'message': 'Inspect the import journal before retrying. No credentials or row data are logged.', 'keep_services_stopped': True}), file=sys.stderr)
    finally:
        if db is not None:
            db.close()
    return 1


if __name__ == '__main__':
    sys.exit(main())
