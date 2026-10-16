"""Optional copy polishing cannot change facts, block staffing or run on reads."""
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.execution_store import ExecutionStore
from app.pod_explanation import ExplanationCopy, polish_copy, saved_copy
from app.selections import ReviewSnapshot, SelectionStore


@pytest.fixture
def settings():
    return Settings(_env_file=None, backend_env='test',
        oci_genai_endpoint='https://example.test', oci_genai_compartment_id='test-compartment',
        oci_genai_model_id='test-model', oci_genai_provider='generic')


def reply(content, **changes):
    return SimpleNamespace(content=content, tool_calls=[], **changes)


def test_oci_polishes_only_approved_wording_and_has_small_bounded_call(settings):
    model = MagicMock()
    model.invoke.return_value = reply('{"opening":"work_first","effort":"people_first"}')
    with patch('app.agents.oci_model.build_model', return_value=model) as build:
        value = polish_copy(settings)
    assert value == ExplanationCopy(opening='work_first', effort='people_first', source='llm')
    assert build.call_args.args[0].oci_timeout_seconds == 6
    assert build.call_args.args[0].oci_max_output_tokens == 128
    model.invoke.assert_called_once()
    assert model.invoke.call_args.kwargs == {'config': {'callbacks': []}}
    assert set(value.model_dump()) == {'version', 'opening', 'effort', 'source'}


@pytest.mark.parametrize('output', [
    'The team is guaranteed to succeed at 999% allocation.',
    '{"opening":"best-qualified team","effort":"total_first"}',
    '{"opening":"work_first","effort":"people_first","hours":999}',
    '{"opening":"work_first","effort":"people_first","source":"llm"}',
    '[]', 'null', '', 'x' * 1001,
])
def test_untrusted_or_invented_model_output_uses_fallback(settings, output):
    model = MagicMock()
    model.invoke.return_value = reply(output)
    with patch('app.agents.oci_model.build_model', return_value=model):
        assert polish_copy(settings) == ExplanationCopy()


def test_timeout_falls_back_without_logging_provider_payload(settings, caplog):
    with patch('app.agents.oci_model.build_model', side_effect=TimeoutError('PRIVATE-PROVIDER-PAYLOAD')):
        assert polish_copy(settings) == ExplanationCopy()
    assert 'PRIVATE-PROVIDER-PAYLOAD' not in caplog.text
    assert 'TimeoutError' in caplog.text


def test_unconfigured_or_disabled_copy_never_constructs_a_model(settings):
    with patch('app.agents.oci_model.build_model') as build:
        assert polish_copy(SimpleNamespace()) == ExplanationCopy()
        assert polish_copy(settings.model_copy(update={'staffing_explanation_enabled': False})) == ExplanationCopy()
    build.assert_not_called()


def test_saved_copy_is_strict_and_legacy_metadata_gets_fallback():
    for invalid in (None, 'free-form prose', {'opening': 'invented', 'effort': 'total_first'}):
        assert saved_copy(invalid) == ExplanationCopy()


def test_worker_checkpoints_before_copy_and_does_not_regenerate_on_recovery(settings):
    store = ExecutionStore(MagicMock(), settings)
    store.save = MagicMock()
    job = SimpleNamespace(checkpoint={})
    polished = ExplanationCopy(opening='work_first', source='llm')
    def generate(_settings):
        assert store.save.call_count == 1
        assert job.checkpoint['explanation_copy']['source'] == 'fallback'
        store.database.write.assert_not_called()
        return polished
    with patch('app.pod_explanation.polish_copy', side_effect=generate) as model:
        first = store.prepare_explanation_copy(job)
        second = store.prepare_explanation_copy(job)
    assert first == second == polished.model_dump(mode='json')
    model.assert_called_once()
    assert store.save.call_count == 2
    # A crash after attempt intent was saved reuses fallback, not another OCI call.
    job.checkpoint['explanation_copy'] = ExplanationCopy().model_dump(mode='json')
    with patch('app.pod_explanation.polish_copy') as model:
        assert store.prepare_explanation_copy(job)['source'] == 'fallback'
        model.assert_not_called()


def test_selection_copy_is_authorized_outside_read_and_write_locks_and_replay_skips_model(settings):
    in_read = False
    @contextmanager
    def read():
        nonlocal in_read
        in_read = True
        try:
            yield None
        finally:
            in_read = False
    database = SimpleNamespace(read=read, write=MagicMock())
    store = SelectionStore(database, settings)
    actor = object()
    def generate(_settings):
        assert not in_read
        database.write.assert_not_called()
        return ExplanationCopy(source='llm')
    with patch('app.selections.rows', side_effect=[[{'responsible_captain_id': 'captain'}], []]), \
         patch('app.decisions.DecisionStore.authorize') as authorize, \
         patch('app.selections.polish_copy', side_effect=generate) as model:
        assert store.prepare_copy(actor, 'PP-1', 'key', 'hash').source == 'llm'
    authorize.assert_called_once_with(None, actor, 'captain')
    model.assert_called_once()
    with patch('app.selections.rows', side_effect=[[{'responsible_captain_id': 'captain'}], [{'proposal_id': 'PP-1', 'body_hash': 'hash'}]]), \
         patch('app.decisions.DecisionStore.authorize'), patch('app.selections.polish_copy') as model:
        store.prepare_copy(actor, 'PP-1', 'key', 'hash')
        model.assert_not_called()


def test_saved_selection_copy_survives_json_roundtrip_and_legacy_reviews():
    from test_mvp_phase2 import roster

    from app.alternatives import exact_team
    from app.planning import json_text
    from app.selections import review_view, snapshot
    bundle = roster()
    option = exact_team(bundle, ('P-001',), ('P-004', 'P-005'))
    original = snapshot(bundle, option, option, 2000)
    polished = original.model_copy(update={'explanation_copy': ExplanationCopy(opening='work_first', source='llm')})
    restored = ReviewSnapshot.model_validate_json(json_text(polished))
    assert review_view(original, restored)['explanation_copy']['source'] == 'llm'
    legacy = json.loads(json_text(original))
    legacy.pop('explanation_copy')
    assert ReviewSnapshot.model_validate(legacy).explanation_copy == ExplanationCopy()
