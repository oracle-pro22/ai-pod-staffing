from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import Actor, Permission
from app.config import Settings
from app.main import create_app


@pytest.mark.parametrize('role,actions,scope,expected', [
    ('POD_CAPTAIN', {'view','export'}, 'FULL', 200),
    ('SYSTEM_ADMINISTRATOR', {'view','export'}, 'FULL', 200),
    ('POD_CAPTAIN', {'view'}, 'FULL', 403),
    ('POD_MEMBER', set(), 'LOCKED', 403),
    ('POD_LEAD', set(), 'LOCKED', 403),
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
