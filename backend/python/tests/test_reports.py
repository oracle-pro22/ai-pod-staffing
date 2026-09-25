from types import SimpleNamespace
from unittest.mock import MagicMock
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import Actor, Permission
from app.config import Settings
from app.main import create_app


def test_report_scope_migration_is_recoverable_and_does_not_touch_business_data():
    root = Path(__file__).resolve().parents[3]
    install = (root / 'sql/oracle/reports_scoped_access.sql').read_text(encoding='utf-8').upper()
    rollback = (root / 'sql/oracle/rollback_reports_scoped_access.sql').read_text(encoding='utf-8').upper()
    assert 'AIPS_RPT_ACCESS_BK' in install and 'AIPS_RPT_ACCESS_BK' in rollback
    assert "EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM AIPS_RPT_ACCESS_BK' INTO N" in install
    assert "ROLE_CODE='POD_LEAD'" in install and "ACCESS_SCOPE='SCOPED'" in install
    assert "ROLE_CODE='POD_MEMBER'" in install and "ACCESS_SCOPE='OWN'" in install
    for table in ('PEOPLE', 'REQUESTS', 'POD_ASSIGNMENTS', 'ASSIGNMENT_DAYS', 'PERSON_CAPACITY_DAYS'):
        assert f'UPDATE {table}' not in install
        assert f'DELETE FROM {table}' not in install
        assert f'TRUNCATE TABLE {table}' not in install


@pytest.mark.parametrize('role,actions,scope,expected', [
    ('POD_CAPTAIN', {'view','export'}, 'FULL', 200),
    ('SYSTEM_ADMINISTRATOR', {'view','export'}, 'FULL', 200),
    ('POD_CAPTAIN', {'view'}, 'FULL', 403),
    ('POD_MEMBER', {'view'}, 'OWN', 403),
    ('POD_LEAD', {'view'}, 'SCOPED', 403),
])
def test_export_requires_current_server_permission(role, actions, scope, expected):
    actor=Actor('subject','person',frozenset({role}),
                (Permission(role,'REPORTS',scope,frozenset(actions)),))
    assignments=MagicMock()
    assignments.workspace.return_value={'people':[], 'can_export':True}
    app=create_app(settings=Settings(_env_file=None),database=MagicMock(),assignments=assignments,
        verifier=SimpleNamespace(subject=lambda _: 'subject'),
        authorization=SimpleNamespace(resolve=lambda _: actor))
    with TestClient(app) as client:
        response=client.get('/v1/reports/export?week=2026-09-14',headers={'x-staffing-role':'Administrator'})
        assert response.status_code==expected
    if expected==200:
        assert assignments.workspace.call_args.args[2]=='REPORTS'
        assert assignments.workspace.call_args.args[0]==actor
        assert assignments.workspace.call_args.args[1].isoformat()=='2026-09-14'
    else:
        assignments.workspace.assert_not_called()
