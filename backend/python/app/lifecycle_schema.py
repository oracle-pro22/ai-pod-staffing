"""Read-only verification before starting the lifecycle-fixes release."""
import argparse
import json
from app.errors import ServiceError
from app.storage import rows


def verify(c):
    columns = {r['column_name']: r for r in rows(c, """SELECT column_name,data_type,nullable FROM user_tab_columns
        WHERE table_name='AVAILABILITY' AND column_name IN ('EFFECTIVE_UNTIL','REVISION')""")}
    if (columns.get('EFFECTIVE_UNTIL', {}).get('data_type') != 'DATE'
        or columns.get('REVISION', {}).get('data_type') != 'NUMBER'
        or columns.get('REVISION', {}).get('nullable') != 'N'):
        raise ServiceError('LIFECYCLE_SCHEMA_REQUIRED', 'Run staffing_lifecycle_fixes.sql before starting this release.', 503)
    checks = rows(c, """SELECT constraint_name FROM user_constraints WHERE table_name='AVAILABILITY'
        AND constraint_name IN ('AVAIL_REVISION_CK','AVAIL_CUTOFF_CK') AND status='ENABLED' AND validated='VALIDATED'""")
    if len(checks) != 2:
        raise ServiceError('LIFECYCLE_SCHEMA_REQUIRED', 'Lifecycle constraints are missing or disabled.', 503)
    legacy = rows(c, "SELECT COUNT(*) n FROM availability WHERE event_type='Commitment'")[0]['n']
    if legacy:
        raise ServiceError('LIFECYCLE_SCHEMA_REQUIRED', 'Finish normalizing legacy external commitments.', 503)
    return {'verified': True, 'writes': 0, 'legacy_external_commitments': legacy}


def main():
    from app.config import Settings
    from app.database import OracleDatabase
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', default='.env')
    args = parser.parse_args()
    with OracleDatabase(Settings(_env_file=args.env_file)).read() as c:
        print(json.dumps(verify(c)))


if __name__ == '__main__':
    main()
