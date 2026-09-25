"""Read-only Phase 3/4 structure verification. Never enrolls existing accounts."""
import argparse
import json
import re

from app.errors import ServiceError
from app.storage import rows

COLUMNS = {
    'ROSTER_ACCESS_CONTROL': {'CONTROL_ID', 'REVISION'},
    'ROSTER_ONBOARDING': {'PERSON_ID', 'STATUS', 'REVISION', 'SUBMITTED_JSON', 'COMPLETED_AT', 'CREATED_AT'},
    'ROSTER_POD_CLAIMS': {'CLAIM_ID', 'PERSON_ID', 'TITLE', 'STARTS_ON', 'ENDS_ON', 'TOTAL_HOURS', 'ROLE_CODE',
                          'STATUS', 'ASSIGNMENT_ID', 'REVIEWED_BY', 'REVIEW_REASON', 'REVIEWED_AT'},
    'ROSTER_RESET_RUNS': {'BATCH_ID', 'STATUS', 'METADATA_JSON', 'OPERATOR_NAME', 'CREATED_AT'},
}

PRIMARY_KEYS = {'ROSTER_ACCESS_CONTROL': 'CONTROL_ID', 'ROSTER_ONBOARDING': 'PERSON_ID',
                'ROSTER_POD_CLAIMS': 'CLAIM_ID', 'ROSTER_RESET_RUNS': 'BATCH_ID'}
CHECKS = {
    'ROSTER_ACCESS_CONTROL': {'control_id=1', 'revision>=1'},
    'ROSTER_ONBOARDING': {"status IN ('DRAFT','REVIEW','COMPLETE')", 'revision>=1', 'submitted_json IS JSON'},
    'ROSTER_POD_CLAIMS': {'total_hours>0', "role_code IN ('POD_LEAD','POD_MEMBER')",
        "status IN ('PENDING','LINKED','DISMISSED')", 'ends_on>=starts_on',
        "(status='LINKED' AND assignment_id IS NOT NULL) OR (status<>'LINKED' AND assignment_id IS NULL)"},
    'ROSTER_RESET_RUNS': {"status IN ('PREPARING','ARCHIVED','REHEARSED','RESET','RESTORED')", 'metadata_json IS JSON'},
}
NULLABLE = {'SUBMITTED_JSON', 'COMPLETED_AT', 'ASSIGNMENT_ID', 'REVIEWED_BY', 'REVIEW_REASON', 'REVIEWED_AT'}


def normalized_check(value):
    # Keep parentheses: different AND/OR grouping must not pass verification.
    return re.sub(r'\s+', '', (value or '').replace('"', '')).upper()


def verify(c):
    for table, expected in COLUMNS.items():
        actual = rows(c, 'SELECT column_name,data_type,nullable FROM user_tab_columns WHERE table_name=:name', name=table)
        if {r['column_name'] for r in actual} != expected:
            raise ServiceError('ROSTER_SCHEMA_MISMATCH', 'Run roster_onboarding.sql and review its structures before starting services.', 503)
        for col in actual:
            name, kind = col['column_name'], col['data_type']
            expected_kind = ('CLOB' if name.endswith('_JSON') else 'NUMBER' if name in ('CONTROL_ID', 'REVISION', 'TOTAL_HOURS')
                else 'DATE' if name in ('STARTS_ON', 'ENDS_ON') else 'TIMESTAMP' if name.endswith('_AT') else 'VARCHAR2')
            if not kind.startswith(expected_kind) or col['nullable'] != ('Y' if name in NULLABLE else 'N'):
                raise ServiceError('ROSTER_SCHEMA_MISMATCH', 'Roster column types/nullability need review.', 503)
        invalid = rows(c, "SELECT constraint_name FROM user_constraints WHERE table_name=:name AND (status<>'ENABLED' OR validated<>'VALIDATED')", name=table)
        primary = rows(c, """SELECT b.column_name FROM user_constraints a JOIN user_cons_columns b
            ON b.constraint_name=a.constraint_name WHERE a.table_name=:name AND a.constraint_type='P'""", name=table)
        checks = rows(c, "SELECT search_condition_vc condition FROM user_constraints WHERE table_name=:name AND constraint_type='C'", name=table)
        if invalid or primary != [{'column_name': PRIMARY_KEYS[table]}] or not {normalized_check(s) for s in CHECKS[table]} <= {normalized_check(r['condition']) for r in checks}:
            raise ServiceError('ROSTER_SCHEMA_MISMATCH', 'Roster constraints need review.', 503)
    links = rows(c, """SELECT a.table_name,b.table_name parent_table,x.column_name,y.column_name parent_column FROM user_constraints a JOIN user_constraints b
        ON a.r_constraint_name=b.constraint_name AND a.r_owner=USER
        JOIN user_cons_columns x ON x.constraint_name=a.constraint_name
        JOIN user_cons_columns y ON y.constraint_name=b.constraint_name AND y.position=x.position WHERE a.constraint_type='R'
        AND a.table_name IN ('ROSTER_ONBOARDING','ROSTER_POD_CLAIMS')""")
    if {(r['table_name'], r['parent_table'], r['column_name'], r['parent_column']) for r in links} != {
        ('ROSTER_ONBOARDING', 'PEOPLE', 'PERSON_ID', 'PERSON_ID'),
        ('ROSTER_POD_CLAIMS', 'ROSTER_ONBOARDING', 'PERSON_ID', 'PERSON_ID'),
        ('ROSTER_POD_CLAIMS', 'POD_ASSIGNMENTS', 'ASSIGNMENT_ID', 'ASSIGNMENT_ID')}:
        raise ServiceError('ROSTER_SCHEMA_MISMATCH', 'Roster foreign keys need review.', 503)
    unique = rows(c, """SELECT b.column_name FROM user_constraints a JOIN user_cons_columns b
        ON b.constraint_name=a.constraint_name WHERE a.table_name='ROSTER_POD_CLAIMS' AND a.constraint_type='U'""")
    if unique != [{'column_name': 'ASSIGNMENT_ID'}]:
        raise ServiceError('ROSTER_SCHEMA_MISMATCH', 'Assignment claim uniqueness needs review.', 503)
    if len(rows(c, 'SELECT revision FROM roster_access_control WHERE control_id=1')) != 1:
        raise ServiceError('ROSTER_SCHEMA_MISMATCH', 'Access serialization row is missing.', 503)
    return {'verified': True, 'tables': sorted(COLUMNS), 'writes': 0, 'accounts_enrolled': 0, 'data_reset': False}


def main():
    from app.config import Settings
    from app.database import OracleDatabase
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env-file', default='.env')
    args = p.parse_args()
    db = OracleDatabase(Settings(_env_file=args.env_file))
    try:
        with db.read() as c:
            print(json.dumps(verify(c), indent=2))
    except ServiceError as error:
        print(json.dumps({'error': error.code, 'message': error.message}))
        raise SystemExit(1) from None
    finally:
        db.close()


if __name__ == '__main__':
    main()
