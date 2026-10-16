"""Read-only response regressions: last saved proposal is not necessarily current."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.execution_store import ExecutionStore


@contextmanager
def read():
    yield None


def store_rows(_connection, sql, **_binds):
    if 'SELECT responsible_captain_id FROM requests' in sql:
        return [{'responsible_captain_id': 'captain'}]
    if sql.startswith('SELECT proposal_id FROM pod_proposals'):
        return [{'proposal_id': 'proposal-1'}]
    if 'SELECT p.proposal_id' in sql:
        return [{'proposal_id': 'proposal-1', 'request_id': 'REQ-1', 'execution_id': 'run-1',
                 'status': 'READY_FOR_REVIEW', 'stale': 'N', 'policy_version': 'policy-1',
                 'responsible_captain_id': 'captain', 'rationale': 'Saved team',
                 'evidence_refs_json': '[]', 'validation_json': '{}'}]
    return []


@pytest.mark.parametrize('status', ['NO_FEASIBLE_POD', 'FAILED', 'RUNNING', 'READY_FOR_REVIEW'])
def test_later_run_returns_previous_team_only_in_history(status):
    store = ExecutionStore(SimpleNamespace(read=read), SimpleNamespace())
    with patch('app.execution_store.rows', side_effect=store_rows), \
         patch.object(store, 'authorize_read') as authorize, \
         patch('app.proposal_state.rows', return_value=[{'execution_id': 'run-2', 'status': status}]), \
         patch('app.execution_store.active_policy_version', return_value='policy-1'), \
         patch('app.selections.attach_review'):
        result = store.latest_proposal('REQ-1', object())
    assert result['current_proposal'] is None
    assert result['previous_proposal']['proposal_id'] == 'proposal-1'
    assert result['previous_proposal']['stale'] == 'Y'
    assert authorize.call_count == 2


def test_matching_successful_run_is_current_and_empty_history():
    store = ExecutionStore(SimpleNamespace(read=read), SimpleNamespace())
    with patch('app.execution_store.rows', side_effect=store_rows), \
         patch.object(store, 'authorize_read'), \
         patch('app.proposal_state.rows', return_value=[{'execution_id': 'run-1', 'status': 'READY_FOR_REVIEW'}]), \
         patch('app.execution_store.active_policy_version', return_value='policy-1'), \
         patch('app.selections.attach_review'):
        result = store.latest_proposal('REQ-1', object())
    assert result['current_proposal']['proposal_id'] == 'proposal-1'
    assert result['previous_proposal'] is None


def test_no_saved_proposal_returns_empty_current_and_history():
    store = ExecutionStore(SimpleNamespace(read=read), SimpleNamespace())
    with patch('app.execution_store.rows', return_value=[{'responsible_captain_id': 'captain'}]) as query, \
         patch.object(store, 'authorize_read'):
        query.side_effect = [[{'responsible_captain_id': 'captain'}], []]
        result = store.latest_proposal('REQ-1', object())
    assert result == {'current_proposal': None, 'previous_proposal': None}


@pytest.mark.parametrize('status', ['APPROVED', 'REJECTED'])
def test_completed_decisions_remain_readable_without_becoming_stale(status):
    store = ExecutionStore(SimpleNamespace(read=read), SimpleNamespace())
    saved = {'proposal_id': 'proposal-1', 'status': status, 'stale': 'N'}
    with patch('app.execution_store.rows', side_effect=store_rows), \
         patch.object(store, 'authorize_read'), patch.object(store, 'get_proposal', return_value=saved):
        result = store.latest_proposal('REQ-1', object())
    assert result == {'current_proposal': saved, 'previous_proposal': None}
