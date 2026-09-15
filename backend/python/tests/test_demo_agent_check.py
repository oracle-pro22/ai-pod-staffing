"""Read-only operator checks and real graph outcome regressions; no Oracle/OCI calls."""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agents.staffing import Analysis
from app.demo_agent_check import (DEMO_POLICY_VERSION, PREVIEW_SOURCE_POLICY, evaluate,
                                  preview_bundle, report_options)
from app.errors import ServiceError
from app.planning import SearchResult, find_options
from app.worker import process_job
from test_phase3 import MemoryStore, bundle, job


def evidenced_bundle():
    data = bundle()
    return data.model_copy(update={"catalogue": {"DEL-001": {"deliverable_name": "Launch guide",
        "mapped_capabilities": [{"skill_id": "INT-001", "interest_name": "Launch capability"}]}},
        "candidates": tuple(person.model_copy(update={
        "skills": tuple(skill.model_copy(update={"evidence": "Prepared and reviewed launch messaging."})
                        for skill in person.skills)}) for person in data.candidates)})


class ReadOnlyOperatorTests(unittest.TestCase):
    def setUp(self):
        self.database = MagicMock()
        self.settings = SimpleNamespace(staffing_max_candidates=60, staffing_search_limit=2000)
        self.data = evidenced_bundle()

    def test_explicit_preview_is_in_memory_and_never_approves_or_writes(self):
        original = self.data.model_dump(mode="json")
        with patch("app.demo_agent_check.collect_evidence", return_value=self.data) as read:
            result = evaluate(self.database, self.settings, self.data.request.request_id, preview_policy=True)
        self.database.read.assert_called_once()
        self.database.write.assert_not_called()
        self.assertEqual(read.call_args.args[2], PREVIEW_SOURCE_POLICY)
        self.assertEqual(result["policy_version"], DEMO_POLICY_VERSION)
        self.assertEqual(result["policy_source"], "in-memory-preview")
        self.assertEqual(result["policy_status"], "DRAFT")
        self.assertEqual(result["status"], "OPTIONS_AVAILABLE")
        self.assertEqual(self.data.model_dump(mode="json"), original)
        for key in ("writes", "model_calls", "queued_jobs", "emails_sent"):
            self.assertEqual(result[key], 0)

    def test_default_uses_database_policy_instead_of_implicitly_previewing(self):
        actual = preview_bundle(self.data)
        with patch("app.demo_agent_check.collect_evidence", return_value=actual) as read:
            result = evaluate(self.database, self.settings, self.data.request.request_id)
        self.assertEqual(read.call_args.args[2], DEMO_POLICY_VERSION)
        self.assertEqual(result["policy_source"], "database")
        self.database.write.assert_not_called()

    def test_preview_never_inherits_approval_metadata(self):
        approved = self.data.policy.model_copy(update={"status": "APPROVED", "approved_by": "real-approver",
                                                      "approved_at": "2026-09-01"})
        result = preview_bundle(self.data.model_copy(update={"policy": approved}))
        self.assertEqual(result.policy.status, "DRAFT")
        self.assertIsNone(result.policy.approved_by)
        self.assertIsNone(result.policy.approved_at)

    def test_options_include_named_people_exact_schedules_and_both_percentages(self):
        data = preview_bundle(self.data)
        report = report_options(data, find_options(data))
        option = report["options"][0]
        self.assertEqual(option["total_planned_hours"], Decimal(20))
        for member in option["members"]:
            self.assertEqual(member["name"], "Private full name")
            self.assertEqual(sum(Decimal(day["hours"]) for day in member["daily_schedule"]), member["planned_hours"])
            for field in ("current_window_allocation_pct", "projected_window_allocation_pct",
                          "projected_peak_week_allocation_pct", "projected_peak_week_start",
                          "peak_week_available_hours", "peak_week_committed_hours", "weekly_capacity"):
                self.assertIn(field, member)

    def test_missing_database_policy_is_not_silently_replaced(self):
        with patch("app.demo_agent_check.collect_evidence", side_effect=ServiceError("POLICY_NOT_FOUND", "Missing policy")), \
             self.assertRaises(ServiceError) as error:
            evaluate(self.database, self.settings, self.data.request.request_id)
        self.assertEqual(error.exception.code, "POLICY_NOT_FOUND")
        self.database.write.assert_not_called()

    def test_tiny_total_effort_returns_information_needed(self):
        data = self.data.model_copy(update={"request": self.data.request.model_copy(update={"total_hours": Decimal(1)})})
        with patch("app.demo_agent_check.collect_evidence", return_value=data):
            result = evaluate(self.database, self.settings, data.request.request_id, preview_policy=True)
        self.assertEqual(result["status"], "NEEDS_INFORMATION")
        self.assertEqual(result["code"], "NEEDS_INFORMATION")
        self.assertIn("at least", result["message"])
        self.assertEqual(result["writes"], 0)

    def test_no_feasible_unknown_and_bounded_results_remain_distinct(self):
        for exhaustive, exclusions, status, code in (
            (True, {}, "NO_FEASIBLE_POD", "NO_FEASIBLE_POD"),
            (True, {"P-006": "CAPACITY_STALE"}, "NEEDS_INFORMATION", "CAPACITY_INFORMATION"),
            (False, {}, "FAILED", "SEARCH_LIMIT"),
        ):
            with self.subTest(status=status):
                report = report_options(self.data, SearchResult(options=(), examined=1,
                                        exhaustive=exhaustive, exclusions=exclusions))
                self.assertEqual((report["status"], report["code"]), (status, code))

    def test_invalid_request_id_stops_before_reading(self):
        with self.assertRaises(ServiceError):
            evaluate(self.database, self.settings, "REQ-1' OR 1=1")
        self.database.read.assert_not_called()


class GraphInformationOutcomeTests(unittest.TestCase):
    def test_real_graph_worker_preserves_tiny_effort_information_outcome(self):
        data = preview_bundle(evidenced_bundle())
        data = data.model_copy(update={"request": data.request.model_copy(update={"total_hours": Decimal(1)})})
        item, store = job(data), MemoryStore()
        item.policy_version = data.policy.version
        item.checkpoint["analysis"] = Analysis(summary="Evidence is ready.",
            evidence_refs=[f"request:{data.request.request_id}"]).model_dump(mode="json")
        result = process_job(store, item, lambda: self.fail("Information-needed scheduling must not call another model"))
        self.assertEqual(result, {"outcome": "NEEDS_INFORMATION"})
        self.assertEqual(store.outcome, "NEEDS_INFORMATION")


if __name__ == "__main__":
    unittest.main()
