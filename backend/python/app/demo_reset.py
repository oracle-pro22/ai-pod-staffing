"""Restore a verified pre-demo baseline over a separately archived test state.

This is intentionally a local/operator maintenance command, not a web endpoint.
It reuses roster_reset's native Oracle archives and requires both the baseline
and the current test state to have completed archive rehearsals.  The current
test archive is retained as a recovery copy after the baseline is restored.
"""
import argparse
import json
import sys

from app.accounts import execute
from app.errors import ServiceError
from app.roster_audit import ARCHIVE_TABLES, PROTECTED_TABLES
from app import roster_reset as recovery


def require_rehearsed(state, meta, confirmation, label):
    recovery.demand(state == 'REHEARSED', f'{label} archive must be REHEARSED.')
    recovery.demand(
        confirmation == meta.get('confirmation')
        and meta.get('rehearsal', {}).get('fingerprint') == confirmation,
        f'Supply the exact {label.lower()} rehearsal fingerprint.',
    )


def require_compatible(baseline, current):
    recovery.demand(baseline['columns'] == current['columns'], 'Table columns changed between baseline and test archive.')
    recovery.demand(baseline['keys'] == current['keys'], 'Constraints changed between baseline and test archive.')
    recovery.demand(baseline['triggers'] == current['triggers'], 'Trigger definitions changed between baseline and test archive.')
    for table in PROTECTED_TABLES:
        recovery.demand(
            baseline['fingerprints'][table] == current['fingerprints'][table],
            f'Protected table {table} changed during testing; automatic restore refused.',
        )


def restore(c, baseline_batch, baseline_confirmation, current_batch, current_confirmation):
    recovery.demand(baseline_batch != current_batch, 'Baseline and current test archives must be different batches.')
    baseline_state, baseline = recovery.run(c, baseline_batch)
    current_state, current = recovery.run(c, current_batch)
    require_rehearsed(baseline_state, baseline, baseline_confirmation, 'Baseline')
    require_rehearsed(current_state, current, current_confirmation, 'Current test')
    require_compatible(baseline, current)
    recovery.verify_archive(c, baseline)
    recovery.verify_archive(c, current)
    # Prove no writer changed the database after the emergency test-state copy.
    recovery.verify_live(c, current)

    try:
        for name in current['triggers']:
            execute(c, f'ALTER TRIGGER {recovery.identifier(name)} DISABLE')
        recovery.lock_tables(c, [*baseline['archives'].values(), *current['archives'].values()])
        recovery.verify_archive(c, baseline)
        recovery.verify_archive(c, current)
        recovery.verify_live(c, current, guards_disabled=True)

        for table in current['order']:
            execute(c, f'DELETE FROM {recovery.identifier(table)}')
        for table in reversed(baseline['order']):
            column_list = ','.join(
                recovery.identifier(column['column_name']) for column in baseline['columns'][table]
            )
            execute(
                c,
                f"INSERT INTO {recovery.identifier(table)}({column_list}) "
                f"SELECT {column_list} FROM {recovery.identifier(baseline['archives'][table])}",
            )

        # Verify the exact baseline before deliberately revoking restored sessions.
        recovery.verify_live(c, baseline, guards_disabled=True)
        execute(c, 'UPDATE app_sessions SET revoked_at=SYSTIMESTAMP WHERE revoked_at IS NULL')
        baseline['demo_restore'] = {
            'current_test_batch': current_batch,
            'current_test_confirmation': current_confirmation,
            'sessions_revoked': True,
        }
        recovery.save(c, baseline, 'RESTORED')
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        recovery.restore_guards(c, current)

    return {
        'baseline_batch': baseline_batch,
        'current_test_batch': current_batch,
        'status': 'RESTORED',
        'active_data_restored': True,
        'current_test_archive_retained': True,
        'protected_data_unchanged': True,
        'sessions_revoked': True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['restore'])
    parser.add_argument('--env-file', default='.env')
    parser.add_argument('--baseline-batch', required=True)
    parser.add_argument('--baseline-confirmation', required=True)
    parser.add_argument('--current-batch', required=True)
    parser.add_argument('--current-confirmation', required=True)
    parser.add_argument('--operator', required=True)
    parser.add_argument('--services-stopped', action='store_true')
    parser.add_argument('--commit', action='store_true')
    args = parser.parse_args()
    if not args.services_stopped or not args.commit or not args.operator.strip() or len(args.operator) > 255:
        parser.error('Restore requires --commit, --services-stopped and a named --operator.')

    # Validate identifiers before connecting or writing.
    recovery.native_name(args.baseline_batch, 'B', 0)
    recovery.native_name(args.current_batch, 'B', 0)

    from app.config import Settings
    from app.database import OracleDatabase
    database = OracleDatabase(Settings(_env_file=args.env_file))
    try:
        with database.write() as connection, recovery.maintenance_lock(connection):
            recovery.stopped(connection)
            result = restore(
                connection,
                args.baseline_batch,
                args.baseline_confirmation,
                args.current_batch,
                args.current_confirmation,
            )
            connection.commit()
        print(json.dumps(result, indent=2))
    except ServiceError as error:
        print(json.dumps({
            'error': error.code,
            'message': error.message,
            'keep_services_stopped': True,
        }), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({
            'error': 'DEMO_RESTORE_RECOVERY_REQUIRED',
            'message': 'Keep services stopped. Inspect both retained archives and restore all guards before retrying.',
            'keep_services_stopped': True,
        }), file=sys.stderr)
        return 1
    finally:
        database.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
