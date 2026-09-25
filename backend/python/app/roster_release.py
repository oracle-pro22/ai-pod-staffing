"""Phase 6 read-only release evidence. Never logs in, approves work or enables services.

Initial stage runs BEFORE first login; onboarding stage reports remaining setup
and self-reported real-POD workload AFTER people supply their own information.
Neither stage is a substitute for operator/browser acceptance.
"""
import argparse
import json
import sys

from app.errors import ServiceError
from app.roster_audit import read_workbook
from app.roster_import import check_schema, load_plan, require, verify_import
from app.roster_reset import run, stopped, verify_archive
from app.storage import rows


def inspect(c, plan, initial=True):
    check_schema(c)
    state, archive = run(c, plan['batch'])
    require(state == 'RESET' and archive.get('roster_import', {}).get('status') == 'IMPORTED'
            and archive['roster_import']['confirmation'] == plan['confirmation'],
            'A matching, committed real-roster import is required before release checks.')
    verify_archive(c, archive)
    if initial:
        stopped(c)
    result = verify_import(c, plan, archive, initial=initial)
    setup = rows(c, """SELECT o.person_id,o.status,a.active_flag FROM roster_onboarding o
        JOIN app_accounts a ON a.person_id=o.person_id""")
    reported = rows(c, "SELECT person_id,COUNT(*) n FROM roster_pod_claims WHERE status='PENDING' GROUP BY person_id")
    states = {r['person_id']: r['status'] for r in setup}
    require(all(states.get(r['person_id']) in ('COMPLETE', 'REVIEW') for r in reported),
            'Reported POD work must belong to a submitted profile.')
    ready = {r['person_id'] for r in setup if r['status'] in ('COMPLETE', 'REVIEW') and r['active_flag'] == 'Y'}
    require(all(r['person_id'] in {p['person_id'] for p in plan['people']} for r in setup), 'Unexpected onboarding identity.')
    role_counts = {role: sum(p['person_id'] in ready and role in p['roles'] for p in plan['people'])
                   for role in ('SYSTEM_ADMINISTRATOR', 'POD_CAPTAIN', 'POD_LEAD', 'POD_MEMBER')}
    switches = rows(c, 'SELECT agents_enabled,notifications_enabled FROM staffing_runtime WHERE runtime_id=1')
    require(len(switches) == 1, 'Missing runtime control row.')
    return {**result, 'stage': 'initial' if initial else 'onboarding',
            'archive_verified': True, 'onboarding_complete_enabled': len(ready),
            'enabled_waiting_for_setup': sum(r['active_flag'] == 'Y' and r['status'] == 'DRAFT' for r in setup),
            'self_reported_pod_entries': sum(r['n'] for r in reported), 'ready_role_counts': role_counts,
            'runtime': switches[0], 'browser_acceptance': 'NOT_AUTOMATICALLY_VERIFIED',
            'existing_project_details': 'Self-reported POD hours count toward capacity immediately and do not require approval.',
            'model_calls': 0, 'emails_sent': 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage', choices=['initial', 'onboarding'], default='initial')
    p.add_argument('--env-file', default='.env')
    p.add_argument('--workbook', required=True)
    p.add_argument('--manifest', required=True)
    p.add_argument('--batch', required=True)
    args = p.parse_args()
    from app.config import Settings
    from app.database import OracleDatabase
    db = None
    try:
        settings = Settings(_env_file=args.env_file)
        require(settings.backend_auth_mode == 'password' and not settings.staffing_demo_personas_enabled,
                'Release requires password authentication and disabled demo personas.')
        plan = load_plan(args.manifest, read_workbook(args.workbook), args.batch)
        db = OracleDatabase(settings)
        with db.read() as c:
            result = inspect(c, plan, initial=args.stage == 'initial')
        print(json.dumps(result, indent=2))
        return 0
    except ServiceError as error:
        print(json.dumps({'error': error.code, 'message': error.message, 'writes': 0}), file=sys.stderr)
    except Exception:
        print(json.dumps({'error': 'ROSTER_RELEASE_CHECK_FAILED', 'message': 'Release check did not finish; no changes were made.', 'writes': 0}), file=sys.stderr)
    finally:
        if db is not None:
            db.close()
    return 1


if __name__ == '__main__':
    sys.exit(main())
