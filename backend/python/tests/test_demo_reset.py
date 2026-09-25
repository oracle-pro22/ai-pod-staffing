from unittest.mock import MagicMock, patch

import pytest

from app import demo_reset
from app.errors import ServiceError


def metadata(batch, protected='same'):
    columns = {
        'APP_SESSIONS': [{'column_name': 'SESSION_ID'}],
        'PEOPLE': [{'column_name': 'PERSON_ID'}],
    }
    return {
        'batch': batch,
        'confirmation': f'{batch}-confirmation',
        'rehearsal': {'fingerprint': f'{batch}-confirmation'},
        'archives': {
            'APP_SESSIONS': f'{batch}_SESSIONS'.upper(),
            'PEOPLE': f'{batch}_PEOPLE'.upper(),
        },
        'columns': columns,
        'keys': [{'constraint_name': 'PK_PEOPLE'}],
        'triggers': {'AUDIT_APPEND': {'sha256': 'same', 'status': 'ENABLED'}},
        'order': ['APP_SESSIONS', 'PEOPLE'],
        'fingerprints': {'POLICY': protected},
    }


def test_restore_requires_two_different_rehearsed_archives():
    c = MagicMock()
    with pytest.raises(ServiceError):
        demo_reset.restore(c, 'roster4-same', 'x', 'roster4-same', 'x')


def test_changed_protected_data_refuses_restore_before_any_sql(monkeypatch):
    monkeypatch.setattr(demo_reset, 'PROTECTED_TABLES', ('POLICY',))
    baseline = metadata('baseline', protected='before')
    current = metadata('current', protected='after')
    with patch.object(demo_reset.recovery, 'run', side_effect=[('REHEARSED', baseline), ('REHEARSED', current)]), \
            patch.object(demo_reset.recovery, 'verify_archive'), \
            patch.object(demo_reset, 'execute') as sql:
        with pytest.raises(ServiceError):
            demo_reset.restore(
                MagicMock(), 'baseline', 'baseline-confirmation', 'current', 'current-confirmation'
            )
    sql.assert_not_called()


def test_restore_archives_are_verified_then_baseline_replaces_test_data(monkeypatch):
    monkeypatch.setattr(demo_reset, 'PROTECTED_TABLES', ('POLICY',))
    baseline, current = metadata('baseline'), metadata('current')
    events = []
    c = MagicMock()
    c.commit.side_effect = lambda: events.append('COMMIT')
    c.rollback.side_effect = lambda: events.append('ROLLBACK')

    with patch.object(demo_reset.recovery, 'run', side_effect=[('REHEARSED', baseline), ('REHEARSED', current)]), \
            patch.object(demo_reset.recovery, 'verify_archive'), \
            patch.object(demo_reset.recovery, 'verify_live'), \
            patch.object(demo_reset.recovery, 'lock_tables'), \
            patch.object(demo_reset.recovery, 'save', side_effect=lambda c, meta, state: events.append(f'SAVE {state}')), \
            patch.object(demo_reset.recovery, 'restore_guards', side_effect=lambda c, meta: events.append('RESTORE_GUARDS')), \
            patch.object(demo_reset, 'execute', side_effect=lambda c, sql: events.append(sql)):
        result = demo_reset.restore(
            c, 'baseline', 'baseline-confirmation', 'current', 'current-confirmation'
        )

    assert events == [
        'ALTER TRIGGER AUDIT_APPEND DISABLE',
        'DELETE FROM APP_SESSIONS',
        'DELETE FROM PEOPLE',
        'INSERT INTO PEOPLE(PERSON_ID) SELECT PERSON_ID FROM BASELINE_PEOPLE',
        'INSERT INTO APP_SESSIONS(SESSION_ID) SELECT SESSION_ID FROM BASELINE_SESSIONS',
        'UPDATE app_sessions SET revoked_at=SYSTIMESTAMP WHERE revoked_at IS NULL',
        'SAVE RESTORED',
        'COMMIT',
        'RESTORE_GUARDS',
    ]
    assert result['active_data_restored'] is True
    assert result['current_test_archive_retained'] is True
    assert result['sessions_revoked'] is True
    c.rollback.assert_not_called()


def test_restore_failure_rolls_back_and_restores_guards(monkeypatch):
    monkeypatch.setattr(demo_reset, 'PROTECTED_TABLES', ('POLICY',))
    baseline, current = metadata('baseline'), metadata('current')
    c = MagicMock()
    with patch.object(demo_reset.recovery, 'run', side_effect=[('REHEARSED', baseline), ('REHEARSED', current)]), \
            patch.object(demo_reset.recovery, 'verify_archive'), \
            patch.object(demo_reset.recovery, 'verify_live'), \
            patch.object(demo_reset.recovery, 'lock_tables'), \
            patch.object(demo_reset.recovery, 'restore_guards') as guards, \
            patch.object(demo_reset, 'execute', side_effect=RuntimeError('interrupted')):
        with pytest.raises(RuntimeError):
            demo_reset.restore(
                c, 'baseline', 'baseline-confirmation', 'current', 'current-confirmation'
            )
    c.rollback.assert_called_once()
    guards.assert_called_once_with(c, current)
