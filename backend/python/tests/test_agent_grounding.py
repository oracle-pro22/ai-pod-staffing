"""Offline contracts for versioned tool facts and authoritative review explanations."""
import unittest
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agents.grounding import checked_plan_scores, grounded_plan_rationale
from app.agents.staffing import Analysis, Selection, ToolSession, required_plan_references
from app.engine_version import (CHECKPOINT_FORMAT_VERSION, ENGINE_VERSION, PROMPT_VERSION,
                                new_checkpoint, validate_execution_checkpoint)
from app.errors import ServiceError
from app.execution_store import ExecutionStore
from app.planning import SearchResult, find_options, json_text
from test_phase3 import bundle, job


class CheckpointVersionTests(unittest.TestCase):
    def test_new_checkpoint_matches_shared_engine_and_prompt(self):
        value = new_checkpoint()
        self.assertEqual(value["format_version"], CHECKPOINT_FORMAT_VERSION)
        self.assertEqual(value["engine_version"], ENGINE_VERSION)
        validate_execution_checkpoint(value, PROMPT_VERSION, "model", "model")

    def test_old_or_changed_engine_and_prompt_cannot_resume(self):
        for change in ({"format_version": 1}, {"engine_version": "old-engine"},
                       {"format_version": True}, {"model_calls": True}, {"tool_calls": -1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_execution_checkpoint({**new_checkpoint(), **change}, PROMPT_VERSION, "model", "model")
        for prompt, model in (("staffing-tools-v1", "model"), ("staffing-tools-v2", "model"), (PROMPT_VERSION, "old-model")):
            with self.subTest(prompt=prompt, model=model), self.assertRaises(ValueError):
                validate_execution_checkpoint(new_checkpoint(), prompt, model, "model")

    def test_enqueue_persists_actual_prompt_version(self):
        data = bundle()
        settings = SimpleNamespace(staffing_worker_enabled=True, staffing_policy_version=data.policy.version,
                                   backend_env="local", oci_genai_model_id="model")
        store = ExecutionStore(MagicMock(), settings)
        with patch.object(store, "require_enabled"), patch.object(store, "event"), \
             patch('app.policy_admin.rows', return_value=[{'policy_version': data.policy.version}]), \
             patch("app.execution_store.assert_captain"), patch("app.execution_store.load_policy", return_value=data.policy), \
             patch("app.execution_store.rows", side_effect=[[
                 {"request_revision": 1, "responsible_captain_id": data.request.responsible_captain_id,
                  "status": "NEEDS_RECOMMENDATION", "agent_enabled": "Y"}], [], []]), \
             patch("app.execution_store.execute") as write:
            store.enqueue(data.request.request_id, "subject", data.request.responsible_captain_id, "key")
        self.assertIn(":promptVersion", write.call_args.args[1])
        self.assertEqual(write.call_args.args[2]["promptVersion"], PROMPT_VERSION)


class GroundedToolTests(unittest.TestCase):
    def setUp(self):
        self.data = bundle()
        self.search = find_options(self.data)
        self.option = self.search.options[0]
        self.session = ToolSession(self.data, self.search, Analysis(summary="Evidence reviewed.",
                                  evidence_refs=[f"request:{self.data.request.request_id}"]))

    def test_completion_requires_request_policy_people_and_capacity(self):
        references = required_plan_references(self.data, self.option.proposal)
        self.session.seen.add("get_validated_options")
        values = {"plan_id": self.option.plan_id, "explanation": "The returned hours fit known capacity.",
                  "evidence_refs": sorted(references)}
        for reference in references:
            with self.subTest(missing=reference), self.assertRaises(ValueError):
                self.session.complete_plan(**{**values, "evidence_refs": sorted(references - {reference})})
        self.session.complete_plan(**values)
        self.assertIsInstance(self.session.result, Selection)

    def test_tool_exposes_dates_denominators_and_citation_contract(self):
        response = self.session.validated_options()
        option = response["options"][0]
        self.assertEqual(set(option["required_evidence_refs"]), required_plan_references(self.data, self.option.proposal))
        self.assertFalse(response["capacity_definitions"]["pending_proposals_reserve_hours"])
        for facts in option["scores"].values():
            for field in ("daily_schedule", "weekly_capacity", "current_allocation_pct", "projected_allocation_pct",
                          "window_allocation_pct", "current_window_allocation_pct", "available_hours",
                          "committed_hours", "proposed_hours", "scheduling_algorithm", "peak_week_start"):
                self.assertIn(field, facts)
        self.assertNotIn("Private full name", json_text(response))

    def test_tool_recomputes_instead_of_echoing_tampered_scores(self):
        self.option.scores["P-006"]["projected_allocation_pct"] = Decimal("99.99")
        response = self.session.validated_options()
        self.assertNotEqual(response["options"][0]["scores"]["P-006"]["projected_allocation_pct"], Decimal("99.99"))

    def test_saved_score_and_schedule_facts_are_fenced_before_publication(self):
        computed = checked_plan_scores(self.data, self.option)
        self.assertEqual(set(computed), {member.person_id for member in self.option.proposal.members})
        for field in ("projected_allocation_pct", "daily_schedule", "scheduling_algorithm"):
            altered = self.option.model_copy(deep=True)
            altered.scores["P-006"][field] = "tampered"
            with self.subTest(field=field), self.assertRaises(ServiceError) as error:
                checked_plan_scores(self.data, altered)
            self.assertEqual(error.exception.code, "INVALID_CHECKPOINT")

    def test_missing_member_metrics_are_rejected(self):
        altered = self.option.model_copy(deep=True)
        del altered.scores["P-006"]
        with self.assertRaises(ServiceError):
            checked_plan_scores(self.data, altered)

    def test_database_json_round_trip_preserves_checked_facts(self):
        restored = SearchResult.model_validate_json(json_text(self.search))
        self.assertEqual(checked_plan_scores(self.data, restored.options[0]),
                         checked_plan_scores(self.data, self.option))

    def test_rationale_is_server_authored_and_distinguishes_window_from_peak(self):
        facts = checked_plan_scores(self.data, self.option)
        text = grounded_plan_rationale(self.data, self.option.proposal, facts)
        self.assertIn("20 person-hours", text)
        self.assertIn("10 planned hours", text)
        self.assertIn("projected busiest-week allocation", text)
        self.assertIn("request-window allocation", text)
        self.assertIn("external work", text)
        self.assertIn("pending proposals do not reserve hours", text)

    def test_direct_publication_cannot_skip_completion_references(self):
        store = ExecutionStore(MagicMock(), SimpleNamespace())
        selection = Selection(plan_id=self.option.plan_id, explanation="Invented 999% allocation.",
                              evidence_refs=["person:P-006", "person:P-007"])
        with self.assertRaises(ServiceError) as error:
            store.publish(job(self.data), self.option, selection)
        self.assertEqual(error.exception.code, "INVALID_CHECKPOINT")
        store.database.write.assert_not_called()

    def test_publication_uses_fresh_facts_and_not_model_numerical_assertions(self):
        settings = SimpleNamespace(staffing_max_candidates=60, backend_env="local")
        store = ExecutionStore(MagicMock(), settings)
        selection = Selection(plan_id=self.option.plan_id, explanation="Invented 999% allocation and 900 hours.",
                              evidence_refs=sorted(required_plan_references(self.data, self.option.proposal)))

        def read(_connection, sql, **_binds):
            if "SELECT request_revision" in sql:
                return [{"request_revision": 1, "responsible_captain_id": self.data.request.responsible_captain_id,
                         "status": "NEEDS_RECOMMENDATION"}]
            if "next_version" in sql:
                return [{"next_version": 1}]
            return []

        with patch("app.execution_store.rows", side_effect=read), patch("app.execution_store.execute") as write, \
             patch('app.policy_admin.rows', return_value=[{'policy_version': self.data.policy.version}]), \
             patch("app.execution_store.assert_captain"), patch.object(store, "lock_job"), \
             patch("app.execution_store.collect_evidence", return_value=self.data):
            result = store.publish(job(self.data), self.option, selection)
        self.assertTrue(result.startswith("PP"))
        proposal_write = next(call for call in write.call_args_list if "INSERT INTO pod_proposals(" in call.args[1])
        binds = proposal_write.args[2]
        self.assertNotIn("999%", binds["rationaleText"])
        self.assertIn("10 planned hours", binds["rationaleText"])
        metadata = json.loads(binds["validationJson"])
        self.assertEqual(metadata["engine_version"], ENGINE_VERSION)
        self.assertEqual(metadata["prompt_version"], PROMPT_VERSION)
        member_writes = [call for call in write.call_args_list if "INSERT INTO pod_proposal_members(" in call.args[1]]
        self.assertEqual(len(member_writes), 2)
        for member in member_writes:
            self.assertIn("daily_schedule", json.loads(member.args[2]["factorsJson"]))


if __name__ == "__main__":
    unittest.main()
