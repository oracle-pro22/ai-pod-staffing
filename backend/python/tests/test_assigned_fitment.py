"""Assigned fitment is a read projection, never an agent execution permission."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import Actor, Permission
from app.config import Settings
from app.errors import ServiceError
from app.execution_store import ExecutionStore
from app.main import create_app


@pytest.mark.parametrize('role,scope', [('POD_LEAD', 'SCOPED'), ('POD_MEMBER', 'OWN')])
def test_route_accepts_assigned_fitment_resource_with_verified_actor(role, scope):
    actor = Actor('subject', 'person', frozenset({role}),
                  (Permission(role, 'AI_FITMENT', scope, frozenset({'view'})),))
    auth, assignments = MagicMock(), MagicMock()
    auth.resolve.return_value = actor
    assignments.workspace.return_value = {'requests': [], 'assignments': []}
    settings = Settings(backend_env='test', backend_auth_mode='local',
                        backend_local_token='x' * 32, backend_local_subject='subject')
    client = TestClient(create_app(settings, MagicMock(), authorization=auth, assignments=assignments))
    headers = {'Authorization': 'Bearer ' + 'x' * 32, 'x-staffing-role': 'POD Captain'}
    response = client.get('/v1/workspace?resource=AI_FITMENT', headers=headers)
    assert response.status_code == 200
    assignments.workspace.assert_called_once_with(actor, None, 'AI_FITMENT')
    assert response.headers['cache-control'] == 'no-store'
    assert client.post('/v1/workspace?resource=AI_FITMENT', headers=headers, json={}).status_code == 405


@pytest.mark.parametrize('role', ['POD_LEAD', 'POD_MEMBER'])
def test_assigned_view_grant_does_not_allow_raw_execution_read_or_captain_actions(role):
    actor = Actor('subject', 'person', frozenset({role}),
                  (Permission(role, 'AI_FITMENT', 'FULL', frozenset({'view'})),))
    with pytest.raises(ServiceError) as denied:
        ExecutionStore.authorize_read(actor, 'captain')
    assert denied.value.status == 403
    with pytest.raises(ServiceError):
        actor.require('AI_FITMENT', 'approve', 'POD_CAPTAIN')
    with pytest.raises(ServiceError):
        actor.require('AGENT_EXECUTION', 'create')
