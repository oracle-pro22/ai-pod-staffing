import inspect
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app import roster_reset as reset
from app.errors import ServiceError
from app.roster_audit import ARCHIVE_TABLES, PROTECTED_TABLES


@pytest.mark.parametrize('bad', ['roster4-x;DELETE', '../roster4-x', 'roster4-'+('a'*23), 'PEOPLE'])
def test_batch_cannot_escape_exact_native_targets(bad):
    with pytest.raises(ServiceError):
        reset.native_name(bad, 'B', 0)


def test_archive_names_are_deterministic_scoped_and_never_original_tables():
    a = reset.native_name('roster4-test', 'B', 0)
    assert a == reset.native_name('roster4-test', 'B', 0)
    assert a != reset.native_name('roster4-test', 'T', 0)
    assert len(a) <= 30 and a not in ARCHIVE_TABLES
    assert set(ARCHIVE_TABLES).isdisjoint(PROTECTED_TABLES)


@pytest.mark.parametrize('action', ['archive', 'resume-archive', 'rehearse', 'reset', 'restore', 'recover-guards'])
def test_every_write_requires_explicit_commit_and_stopped_ack(action, monkeypatch):
    monkeypatch.setattr('sys.argv', ['roster_reset', action, '--batch', 'roster4-test'])
    with patch('app.database.OracleDatabase') as db, pytest.raises(SystemExit) as error:
        reset.main()
    assert error.value.code == 2
    db.assert_not_called()


def metadata():
    return {'batch': 'roster4-test', 'confirmation': 'abc', 'rehearsal': {'fingerprint': 'abc'},
            'archives': {'PEOPLE': 'R4B_TEST_00'}, 'order': ['APP_SESSIONS', 'APP_ACCOUNTS', 'PEOPLE'],
            'columns': {t: [{'column_name': 'ID'}] for t in ('APP_SESSIONS', 'APP_ACCOUNTS', 'PEOPLE')},
            'triggers': {'P2_AUDIT_APPEND': {'sha256': 'original'}}}


@pytest.mark.parametrize('state,confirmation', [('ARCHIVED', 'abc'), ('PREPARING', 'abc'), ('RESET', 'abc'), ('REHEARSED', 'wrong')])
def test_reset_requires_completed_rehearsal_and_exact_confirmation(state, confirmation):
    with patch.object(reset, 'run', return_value=(state, metadata())), patch.object(reset, 'execute') as sql:
        with pytest.raises(ServiceError):
            reset.mutate(MagicMock(), 'roster4-test', confirmation)
    sql.assert_not_called()


def test_changed_live_data_blocks_before_guard_ddl():
    with patch.object(reset, 'run', return_value=('REHEARSED', metadata())), patch.object(reset, 'verify_archive'), patch.object(reset, 'verify_live', side_effect=ServiceError('STALE', 'New writes', 409)), patch.object(reset, 'execute') as sql:
        with pytest.raises(ServiceError):
            reset.mutate(MagicMock(), 'roster4-test', 'abc')
    sql.assert_not_called()


def test_reset_uses_child_first_deletes_one_commit_then_restores_guards():
    c, events = MagicMock(), []
    c.commit.side_effect = lambda: events.append('COMMIT')
    with patch.object(reset, 'run', return_value=('REHEARSED', metadata())), patch.object(reset, 'verify_archive'), patch.object(reset, 'verify_live'), patch.object(reset, 'lock_tables'), patch.object(reset, 'save'), patch.object(reset, 'execute', side_effect=lambda c, sql: events.append(sql)), patch.object(reset, 'restore_guards', side_effect=lambda c, meta: events.append('RESTORE_GUARDS')):
        result = reset.mutate(c, 'roster4-test', 'abc')
    assert events == ['ALTER TRIGGER P2_AUDIT_APPEND DISABLE', 'DELETE FROM APP_SESSIONS', 'DELETE FROM APP_ACCOUNTS', 'DELETE FROM PEOPLE', 'COMMIT', 'RESTORE_GUARDS']
    assert result['archive_retained'] and result['runtime_switches'] == 'OFF'
    c.rollback.assert_not_called()


def test_failure_rolls_back_before_guard_enable_never_commits_partial_delete():
    c, events = MagicMock(), []
    def sql(c, query):
        if query == 'DELETE FROM APP_ACCOUNTS':
            raise RuntimeError('Interrupted deletion')
    c.rollback.side_effect = lambda: events.append('ROLLBACK')
    with patch.object(reset, 'run', return_value=('REHEARSED', metadata())), patch.object(reset, 'verify_archive'), patch.object(reset, 'verify_live'), patch.object(reset, 'lock_tables'), patch.object(reset, 'execute', side_effect=sql), patch.object(reset, 'restore_guards', side_effect=lambda c, meta: events.append('RESTORE_GUARDS')):
        with pytest.raises(RuntimeError):
            reset.mutate(c, 'roster4-test', 'abc')
    assert events == ['ROLLBACK', 'RESTORE_GUARDS']
    c.commit.assert_not_called()


def test_concurrent_change_after_guard_disable_still_blocks_all_deletes():
    with patch.object(reset, 'run', return_value=('REHEARSED', metadata())), patch.object(reset, 'verify_archive'), patch.object(reset, 'verify_live', side_effect=[None, ServiceError('STALE', 'Changed under lock', 409)]), patch.object(reset, 'lock_tables'), patch.object(reset, 'execute') as sql, patch.object(reset, 'restore_guards') as recover:
        with pytest.raises(ServiceError):
            reset.mutate(MagicMock(), 'roster4-test', 'abc')
    assert all('DELETE' not in call.args[1] for call in sql.call_args_list)
    recover.assert_called_once()


def test_guard_recovery_refuses_changed_definitions():
    with patch.object(reset, 'trigger_metadata', return_value={'P2_AUDIT_APPEND': {'sha256': 'CHANGED'}}), patch.object(reset, 'execute') as sql:
        with pytest.raises(ServiceError):
            reset.restore_guards(None, metadata())
    sql.assert_not_called()


def test_fingerprints_preserve_large_numbers_lobs_timestamp_precision_without_logging():
    c = MagicMock()
    cursor = c.cursor.return_value.__enter__.return_value
    cursor.fetchmany.side_effect = [[('123456789012345678901234567890.12', '2026-09-23T12:00:00.123456789+05:30', 'sensitive')], []]
    meta = [{'column_name': 'N', 'data_type': 'NUMBER'}, {'column_name': 'T', 'data_type': 'TIMESTAMP(9) WITH TIME ZONE'}, {'column_name': 'PAYLOAD', 'data_type': 'CLOB'}]
    result = reset.fingerprint(c, 'APP_ACCOUNTS', meta)
    sql = cursor.execute.call_args.args[0]
    assert 'TM9' in sql and 'FF9' in sql and result['count'] == 1
    assert 'sensitive' not in str(result) and len(result['sha256']) == 64


def test_json_fingerprint_forces_same_text_fetch_for_source_and_ctas_archive():
    c = MagicMock()
    cursor = c.cursor.return_value.__enter__.return_value
    source_lob, archive_lob = MagicMock(), MagicMock()
    source_lob.read.return_value = archive_lob.read.return_value = '{"value":1}'
    cursor.fetchmany.side_effect = [[(source_lob,)], [], [(archive_lob,)], []]
    meta = [{'column_name': 'PAYLOAD', 'data_type': 'CLOB'}]
    source = reset.fingerprint(c, 'SOURCE_TABLE', meta, ['PAYLOAD'])
    archived = reset.fingerprint(c, 'ARCHIVE_TABLE', meta, ['PAYLOAD'])
    assert source == archived
    assert all('TO_CLOB(PAYLOAD)' in call.args[0] for call in cursor.execute.call_args_list)


def test_legacy_preparing_batch_upgrades_only_after_old_live_and_empty_archive_checks():
    c = MagicMock()
    meta = metadata()
    meta['keys'] = []
    meta['fingerprints'] = {'PEOPLE': {'count': 1, 'sha256': 'old'}}
    meta['columns'] = {'PEOPLE': [{'column_name': 'PROFILE_JSON', 'data_type': 'CLOB'}]}
    with patch.object(reset, 'verify_live') as live, patch.object(reset, 'fingerprint', side_effect=[
            {'count': 0, 'sha256': 'empty'}, {'count': 1, 'sha256': 'new'}]), \
            patch.object(reset, 'json_columns', return_value=['PROFILE_JSON']), patch.object(reset, 'save') as save:
        upgraded = reset.upgrade_preparing_fingerprints(c, meta)
    live.assert_called_once()
    save.assert_called_once_with(c, upgraded, 'PREPARING')
    assert upgraded['fingerprints']['PEOPLE']['sha256'] == 'new'
    assert upgraded['json_columns']['PEOPLE'] == ['PROFILE_JSON']
    c.commit.assert_called_once()


def test_legacy_journal_is_not_changed_when_live_snapshot_or_archive_is_not_safe():
    meta = metadata()
    meta['fingerprints'] = {'PEOPLE': {'count': 1, 'sha256': 'old'}}
    with patch.object(reset, 'verify_live', side_effect=ServiceError('STALE', 'Changed', 409)), \
            patch.object(reset, 'save') as save:
        with pytest.raises(ServiceError):
            reset.upgrade_preparing_fingerprints(MagicMock(), meta)
    save.assert_not_called()


def test_maintenance_lock_survives_ddl_commits_and_is_released():
    c = MagicMock()
    c.cursor.return_value.__enter__.return_value.var.return_value.getvalue.return_value = 0
    with reset.maintenance_lock(c):
        c.commit()
    queries = str(c.cursor.return_value.__enter__.return_value.execute.call_args_list)
    assert 'release_on_commit=>FALSE' in queries and 'DBMS_LOCK.RELEASE' in queries


def test_another_operator_holding_lock_blocks_maintenance():
    c = MagicMock()
    c.cursor.return_value.__enter__.return_value.var.return_value.getvalue.return_value = 1
    with pytest.raises(ServiceError), reset.maintenance_lock(c):
        pytest.fail('Must not enter maintenance')


def test_cli_commits_journal_before_releasing_maintenance_lock(monkeypatch):
    events = []
    c, db = MagicMock(), MagicMock()
    db.write.return_value.__enter__.return_value = c
    c.commit.side_effect = lambda: events.append('COMMIT')

    @contextmanager
    def held(c):
        events.append('LOCK')
        yield
        events.append('UNLOCK')

    monkeypatch.setattr('sys.argv', ['roster_reset', 'rehearse', '--batch', 'roster4-test', '--commit', '--services-stopped', '--operator', 'test'])
    with patch('app.config.Settings'), patch('app.database.OracleDatabase', return_value=db), patch.object(reset, 'maintenance_lock', held), patch.object(reset, 'stopped'), patch.object(reset, 'rehearse', return_value={'status': 'REHEARSED'}):
        assert reset.main() == 0
    assert events == ['LOCK', 'COMMIT', 'UNLOCK']


def test_failed_maintenance_rolls_back_before_unlock():
    c, events = MagicMock(), []
    cursor = c.cursor.return_value.__enter__.return_value
    cursor.var.return_value.getvalue.return_value = 0
    cursor.execute.side_effect = lambda query, **kwargs: events.append('UNLOCK' if 'RELEASE' in query else 'LOCK')
    c.rollback.side_effect = lambda: events.append('ROLLBACK')
    with pytest.raises(RuntimeError), reset.maintenance_lock(c):
        raise RuntimeError('Failure')
    assert events == ['LOCK', 'ROLLBACK', 'UNLOCK']


def test_native_restore_never_reuses_password_sessions_or_drops_archives():
    source = inspect.getsource(reset)
    assert 'UPDATE app_sessions SET revoked_at=SYSTIMESTAMP' in source
    assert 'DROP TABLE' not in source and 'TRUNCATE TABLE' not in source
    assert 'release_on_commit=>FALSE' in source and "args.action in ('plan', 'inspect')" in source
    assert 'DBMS_METADATA.GET_DDL' in source
