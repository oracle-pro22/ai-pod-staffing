"""Offline regression tests: stage reservations survive retries and never exceed total cost caps."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from test_phase3 import bundle, job

from app.agent_budget import (
    budget_counters,
    model_call_limit,
    model_call_limits,
    remaining_model_calls,
    reserve_call,
)
from app.engine_version import ENGINE_VERSION, PROMPT_VERSION, new_checkpoint, validate_execution_checkpoint
from app.errors import ServiceError
from app.execution_store import ExecutionStore


def checkpoint(analyst=0, planner=0, tools=0):
    return {**new_checkpoint(), "analyst_model_calls": analyst, "planner_model_calls": planner,
            "model_calls": analyst + planner, "tool_calls": tools}


class StageBudgetTests(unittest.TestCase):
    def test_analyst_stops_at_six_leaving_planner_capacity(self):
        value = checkpoint()
        for _ in range(6):
            value.update(reserve_call(value, "analyst", "model_calls", 12))
        before = copy.deepcopy(value)
        with self.assertRaises(ServiceError) as error:
            reserve_call(value, "analyst", "model_calls", 12)
        self.assertEqual(error.exception.code, "AGENT_BUDGET_EXCEEDED")
        self.assertEqual(value, before)
        self.assertEqual(remaining_model_calls(value, 12, "analyst"), 0)
        self.assertEqual(remaining_model_calls(value, 12, "planner"), 6)

    def test_lowest_policy_reserves_two_planner_calls(self):
        self.assertEqual(model_call_limits(6), (6, 4))
        value = checkpoint(analyst=4)
        self.assertEqual(remaining_model_calls(value, 6, "analyst"), 0)
        self.assertEqual(remaining_model_calls(value, 6, "planner"), 2)
        for _ in range(2):
            value.update(reserve_call(value, "planner", "model_calls", 6))
        self.assertEqual(value["model_calls"], 6)
        with self.assertRaises(ServiceError):
            reserve_call(value, "planner", "model_calls", 6)

    def test_planner_can_use_unused_analyst_budget_without_increasing_total(self):
        value = checkpoint(analyst=2)
        self.assertEqual(remaining_model_calls(value, 12, "planner"), 10)
        for _ in range(10):
            value.update(reserve_call(value, "planner", "model_calls", 12))
        self.assertEqual(value["planner_model_calls"], 10)
        self.assertEqual(value["model_calls"], 12)
        with self.assertRaises(ServiceError):
            reserve_call(value, "planner", "model_calls", 12)

    def test_larger_policy_cannot_raise_the_hard_total_cap(self):
        self.assertEqual(model_call_limits(30), (12, 6))
        self.assertEqual(model_call_limit(30, "planner"), 12)
        with self.assertRaises(ServiceError):
            reserve_call(checkpoint(6, 6), "planner", "model_calls", 30)

    def test_policy_too_small_for_six_stage_calls_fails_before_reservation(self):
        for maximum in (0, 1, 2, 3, 4, 5, True, 6.0, "12"):
            value = checkpoint()
            with self.subTest(maximum=maximum), self.assertRaises(ServiceError) as error:
                reserve_call(value, "analyst", "model_calls", maximum)
            self.assertEqual(error.exception.code, "AGENT_BUDGET_CONFIGURATION")
            self.assertEqual(value, checkpoint())

    def test_all_stage_counters_are_required_and_sum_to_total(self):
        for changes in ({"analyst_model_calls": None}, {"planner_model_calls": True},
                        {"analyst_model_calls": -1}, {"planner_model_calls": 1},
                        {"model_calls": 13, "analyst_model_calls": 6, "planner_model_calls": 7},
                        {"model_calls": 7, "analyst_model_calls": 7}, {"tool_calls": 41}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                budget_counters({**checkpoint(), **changes})

    def test_tool_counter_does_not_change_model_counters(self):
        value = checkpoint(analyst=6, tools=39)
        result = reserve_call(value, "analyst", "tool_calls", 12)
        self.assertEqual(result["tool_calls"], 40)
        self.assertEqual(result["model_calls"], 6)
        self.assertEqual(result["planner_model_calls"], 0)
        with self.assertRaises(ServiceError):
            reserve_call(result, "planner", "tool_calls", 12)
        self.assertEqual(value["tool_calls"], 39)

    def test_invalid_stage_or_counter_cannot_bypass_reservations(self):
        for stage, counter in (("rules", "model_calls"), ("planner", "planner_model_calls"),
                               ("analysis", "tool_calls"), ("analyst", "")):
            with self.subTest(stage=stage, counter=counter), self.assertRaises(ServiceError) as error:
                reserve_call(checkpoint(), stage, counter, 12)
            self.assertEqual(error.exception.code, "INVALID_AGENT_BUDGET")

    def test_policy_reduction_never_reinterprets_prior_stage_usage(self):
        with self.assertRaises(ValueError):
            remaining_model_calls(checkpoint(analyst=6), 6, "planner")


class PersistedBudgetTests(unittest.TestCase):
    def setUp(self):
        self.database = MagicMock()
        self.settings = SimpleNamespace(staffing_worker_enabled=True, staffing_lease_seconds=180,
                                        oci_genai_model_id="model")
        self.store = ExecutionStore(self.database, self.settings)
        self.item = job(bundle())

    def save_with(self, previous, *, stage="analyst", reserve="model_calls"):
        with patch.object(self.store, "lock_job", return_value={"checkpoint_json": json.dumps(previous)}), \
             patch.object(self.store, "event"), patch("app.execution_store.execute") as write:
            self.store.save(self.item, stage, "Reserved", reserve=reserve)
        return json.loads(write.call_args.args[2]["checkpointJson"])

    def test_reservation_restores_committed_total_and_both_stage_counters(self):
        self.item.checkpoint.update(model_calls=0, analyst_model_calls=0, planner_model_calls=0, tool_calls=0)
        result = self.save_with(checkpoint(analyst=5, tools=8))
        self.assertEqual(budget_counters(result), budget_counters(checkpoint(analyst=6, tools=8)))
        self.assertEqual(self.item.checkpoint, result)

    def test_no_reservation_save_also_cannot_reset_or_forge_counters(self):
        self.item.checkpoint.update(model_calls=1000, analyst_model_calls=-1, tool_calls=True)
        self.item.checkpoint["analysis"] = {"summary": "Completed"}
        result = self.save_with(checkpoint(2, 1, 7), stage="analysis", reserve=None)
        self.assertEqual(budget_counters(result), budget_counters(checkpoint(2, 1, 7)))
        self.assertIn("analysis", result)

    def test_exhausted_persisted_analyst_cannot_resume_as_new(self):
        original = copy.deepcopy(self.item.checkpoint)
        with patch.object(self.store, "lock_job", return_value={"checkpoint_json": json.dumps(checkpoint(6))}), \
             patch("app.execution_store.execute") as write, self.assertRaises(ServiceError) as error:
            self.store.save(self.item, "analyst", "Call", reserve="model_calls")
        self.assertEqual(error.exception.code, "AGENT_BUDGET_EXCEEDED")
        write.assert_not_called()
        self.assertEqual(self.item.checkpoint, original)
        result = self.save_with(checkpoint(6), stage="planner")
        self.assertEqual(budget_counters(result), budget_counters(checkpoint(6, 1)))

    def test_failed_commit_does_not_mutate_in_memory_reservations(self):
        original = copy.deepcopy(self.item.checkpoint)

        @contextmanager
        def transaction():
            yield None
            raise ConnectionError("simulated uncertain commit")

        self.database.write = transaction
        with patch.object(self.store, "lock_job", return_value={"checkpoint_json": json.dumps(checkpoint(2))}), \
             patch.object(self.store, "event"), patch("app.execution_store.execute"), self.assertRaises(ConnectionError):
            self.store.save(self.item, "analyst", "Call", reserve="model_calls")
        self.assertEqual(self.item.checkpoint, original)
        # If the server committed despite the lost response, its counter wins on retry.
        self.database.write = MagicMock()
        result = self.save_with(checkpoint(3))
        self.assertEqual(result["analyst_model_calls"], 4)

    def test_old_or_missing_stage_counters_rejected_not_zeroed(self):
        for previous in ({"format_version": 2, "engine_version": "staffing-engine-v2", "model_calls": 3,
                          "tool_calls": 5}, {**checkpoint(), "planner_model_calls": None}, {}):
            with self.subTest(previous=previous), \
                 patch.object(self.store, "lock_job", return_value={"checkpoint_json": json.dumps(previous)}), \
                 patch("app.execution_store.execute") as write, self.assertRaises(ServiceError) as error:
                self.store.save(self.item, "analyst", "Call", reserve="model_calls")
            self.assertEqual(error.exception.code, "CHECKPOINT_VERSION")
            write.assert_not_called()

    def test_first_save_initializes_all_stage_counters(self):
        with patch.object(self.store, "lock_job", return_value={"checkpoint_json": None}), \
             patch.object(self.store, "event"), patch("app.execution_store.execute"):
            self.store.save(self.item, "evidence", "Loaded", bundle=self.item.evidence)
        self.assertEqual(self.item.checkpoint, checkpoint())

    def test_retry_command_retains_checkpoint_and_all_budget_counters(self):
        self.item.checkpoint = checkpoint(4, 2, 9)
        with patch.object(self.store, "lock_job", return_value={"attempt_count": 1, "max_attempts": 3}), \
             patch.object(self.store, "event"), patch("app.execution_store.execute") as write:
            self.store.retry(self.item)
        self.assertNotIn("checkpoint", write.call_args.args[1])
        self.assertEqual(self.item.checkpoint, checkpoint(4, 2, 9))

    def test_undersized_policy_cannot_reserve_even_if_enqueued_by_an_old_process(self):
        self.item.evidence = self.item.evidence.model_copy(update={
            "policy": self.item.evidence.policy.model_copy(update={"maximum_agent_steps": 5})})
        with patch.object(self.store, "lock_job", return_value={"checkpoint_json": json.dumps(checkpoint())}), \
             patch("app.execution_store.execute") as write, self.assertRaises(ServiceError) as error:
            self.store.save(self.item, "analyst", "Call", reserve="model_calls")
        self.assertEqual(error.exception.code, "AGENT_BUDGET_CONFIGURATION")
        write.assert_not_called()

    def test_old_inflight_checkpoint_or_old_queued_prompt_is_terminal_before_model_use(self):
        cursor = self.database.write.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("RUN-1",)
        for saved, prompt in ((None, "staffing-tools-v3"),
                              (json.dumps({**checkpoint(), "format_version": 2}), PROMPT_VERSION)):
            record = {"attempt_count": 0, "max_attempts": 3, "checkpoint_json": saved,
                      "prompt_version": prompt, "model_id": "model", "evidence_snapshot_json": None}
            with self.subTest(prompt=prompt), patch.object(self.store, "require_enabled"), \
                 patch("app.execution_store.rows", return_value=[record]), \
                 patch("app.execution_store.execute"), patch.object(self.store, "terminal") as terminal:
                self.assertIsNone(self.store.claim("worker"))
            self.assertEqual(terminal.call_args.args[3], "CHECKPOINT_VERSION")

    def test_new_engine_accepts_consistent_durable_stage_counts(self):
        value = checkpoint(5, 4, 18)
        validate_execution_checkpoint(value, PROMPT_VERSION, "model", "model")
        self.assertEqual(value["engine_version"], ENGINE_VERSION)
        missing = dict(value)
        del missing["planner_model_calls"]
        with self.assertRaises(ValueError):
            validate_execution_checkpoint(missing, PROMPT_VERSION, "model", "model")


if __name__ == "__main__":
    unittest.main()
