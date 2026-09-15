"""Offline phase-3 rules, tools, checkpoints and publication boundaries (no Oracle/OCI calls)."""
import copy
import unittest
from contextlib import contextmanager
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from test_rules import MON, person, request

from app.agents.staffing import BUSINESS_QUESTIONS, Analysis, Selection, ToolSession
from app.capacity import CapacityLedger, DailyHours
from app.engine_version import new_checkpoint
from app.errors import ServiceError
from app.execution_store import ExecutionStore, Job, LeaseLost
from app.planning import EvidenceBundle, SearchResult, divide_hours, find_options, json_text
from app.policy import DEFAULT_POLICY
from app.workflow import StaffingWorkflow


def bundle(**updates):
    people = (person(), person(person_id="P-007", roles=[{"code": "POD_MEMBER", "starts_on": MON}]))
    return EvidenceBundle(request=request(member_count=1), policy=DEFAULT_POLICY, candidates=people,
        ledgers={p.person_id: CapacityLedger() for p in people},
        versions={p.person_id: {"skills_version": 0, "workload_version": 0, "availability_version": 0} for p in people},
        names={p.person_id: "Private full name" for p in people}, context={}, catalogue={"DEL-001": {}},
        **updates)


def job(data=None):
    return Job("RUN-1", "REQ-1046", 1, DEFAULT_POLICY.version, "captain-subject", "current-token",
               new_checkpoint(), data)


def plan_references(data):
    return [f"request:{data.request.request_id}", f"policy:{data.policy.version}",
            *[f"person:{person.person_id}" for person in data.candidates],
            *[f"capacity:{person.person_id}" for person in data.candidates]]


class PlanningTests(unittest.TestCase):
    def test_hours_conserved_and_capacity_bounded(self):
        for total, caps in ((2000, [100, 5000]), (3, [4, 4]), (7901, [4000, 4000]), (2, [1, 1])):
            with self.subTest(total=total):
                shares = divide_hours(total, caps)
                self.assertEqual(sum(shares), total)
                self.assertTrue(all(0 < value <= cap for value, cap in zip(shares, caps)))
        self.assertIsNone(divide_hours(5, [1, 2]))
        self.assertIsNone(divide_hours(1, [2, 2]))

    def test_feasible_team_has_no_duplicates_and_conserved_effort(self):
        result = find_options(bundle())
        self.assertEqual(len(result.options), 1)
        proposal = result.options[0].proposal
        self.assertEqual(sum(m.hours for m in proposal.members), D(20))
        self.assertEqual(len({m.person_id for m in proposal.members}), 2)
        self.assertEqual(result, find_options(bundle()))
        self.assertTrue(result.exhaustive)

    def test_checkpoint_round_trip_keeps_valid_option(self):
        search = find_options(bundle())
        restored = SearchResult.model_validate_json(json_text(search))
        self.assertEqual(restored.options[0].proposal, search.options[0].proposal)
        self.assertEqual(D(str(restored.options[0].scores["P-006"]["score"])), search.options[0].scores["P-006"]["score"])

    def test_missing_capacity_is_not_free(self):
        data = bundle().model_copy(update={"ledgers": {}, "exclusions": {"P-006": "CAPACITY_UNKNOWN"}})
        result = find_options(data)
        self.assertEqual(result.options, ())
        self.assertEqual(result.exclusions["P-006"], "CAPACITY_UNKNOWN")

    def test_unavailable_lead_does_not_get_assigned(self):
        data = bundle()
        data.ledgers["P-006"] = CapacityLedger(absences=(DailyHours(day=MON, hours=8),))
        self.assertFalse(find_options(data).options)

    def test_bounded_search_does_not_claim_exhaustive(self):
        data = bundle()
        extra = person(person_id="P-008", roles=[{"code": "POD_MEMBER", "starts_on": MON}])
        data = data.model_copy(update={"candidates": (*data.candidates, extra), "ledgers": {**data.ledgers, "P-008": CapacityLedger()}})
        result = find_options(data, limit=1)
        self.assertFalse(result.exhaustive)
        self.assertEqual(result.examined, 1)

    def test_skill_gap_cannot_be_overridden_by_interest(self):
        data = bundle()
        data = data.model_copy(update={"candidates": tuple(p.model_copy(update={"skills": ()}) for p in data.candidates)})
        self.assertFalse(find_options(data).options)

    def test_names_are_not_model_selection_inputs(self):
        session = ToolSession(bundle())
        self.assertNotIn("Private full name", json_text(session.candidate_overview()))
        self.assertNotIn("Private full name", json_text(session.person_evidence("P-006")))


class ToolBoundaryTests(unittest.TestCase):
    def test_analyst_must_read_and_cite_evidence(self):
        session = ToolSession(bundle())
        values = {"summary": "Needs a POD", "evidence_refs": ["request:REQ-1046"]}
        with self.assertRaises(ValueError):
            session.complete_analysis(**values)
        session.seen.update(("get_request_context", "get_candidate_overview", "get_rejection_feedback"))
        session.complete_analysis(**values)
        self.assertIsInstance(session.result, Analysis)

    def test_invented_reference_rejected(self):
        with self.assertRaises(ValueError):
            ToolSession(bundle()).references(["person:UNKNOWN"])

    def test_planner_cannot_invent_or_edit_a_team(self):
        data = bundle()
        search = find_options(data)
        session = ToolSession(data, search, Analysis(summary="Ready", evidence_refs=["request:REQ-1046"]))
        session.seen.add("get_validated_options")
        values = {"plan_id": search.options[0].plan_id, "explanation": "Capability and capacity fit.",
                  "evidence_refs": plan_references(data)}
        with self.assertRaises(ValueError):
            session.complete_plan(**{**values, "plan_id": "invented"})
        with self.assertRaises(ValueError):
            session.complete_plan(**{**values, "evidence_refs": ["person:P-006"]})
        with self.assertRaises(ValueError):
            session.complete_plan(**values, hours=100)
        session.complete_plan(**values)
        self.assertIsInstance(session.result, Selection)


class MemoryStore:
    settings = SimpleNamespace(staffing_search_limit=2000)

    def __init__(self):
        self.saved = []
        self.outcome = None

    def load_evidence(self, _job):
        return bundle()

    def save(self, item, stage, summary, **_kwargs):
        self.saved.append((stage, copy.deepcopy(item.checkpoint)))

    def finish(self, _job, status, *_args):
        self.outcome = status

    def publish(self, _job, option, selection):
        self.outcome = "READY_FOR_REVIEW"
        self.published = (option, selection)


class StageTests(unittest.TestCase):
    def test_stages_resume_without_repeating_completed_agents(self):
        store, item = MemoryStore(), job()
        flow = StaffingWorkflow(store, item, lambda: self.fail("Completed agents should not be called"))
        flow.collect({})
        item.checkpoint["analysis"] = Analysis(summary="Ready", evidence_refs=["request:REQ-1046"]).model_dump(mode="json")
        search = find_options(item.evidence)
        item.checkpoint["search"] = search.model_dump(mode="json")
        item.checkpoint["selection"] = Selection(plan_id=search.options[0].plan_id, explanation="Skills and capacity fit.",
            evidence_refs=plan_references(item.evidence)).model_dump(mode="json")
        self.assertEqual(flow.analyse({})["outcome"], "RUNNING")
        self.assertEqual(flow.plan({})["outcome"], "RUNNING")
        self.assertEqual(flow.publish({})["outcome"], "READY_FOR_REVIEW")
        self.assertEqual(store.outcome, "READY_FOR_REVIEW")

    def test_clarifications_stop_before_planning(self):
        item, store = job(bundle()), MemoryStore()
        item.checkpoint["analysis"] = Analysis(summary="Ambiguous objective", evidence_refs=["request:REQ-1046"],
            clarification_fields=["business_objectives"],
            clarification_questions=[BUSINESS_QUESTIONS["business_objectives"]]).model_dump(mode="json")
        flow = StaffingWorkflow(store, item, lambda: None)
        self.assertEqual(flow.analyse({})["outcome"], "NEEDS_INFORMATION")

    def test_unknown_capacity_outcome_is_not_no_feasible(self):
        item, store = job(bundle()), MemoryStore()
        item.checkpoint["search"] = SearchResult(options=(), examined=0, exhaustive=True,
            exclusions={"P-006": "CAPACITY_UNKNOWN"}).model_dump(mode="json")
        self.assertEqual(StaffingWorkflow(store, item, lambda: None).plan({})["outcome"], "NEEDS_INFORMATION")

    def test_search_limit_is_not_no_feasible(self):
        item, store = job(bundle()), MemoryStore()
        item.checkpoint["search"] = SearchResult(options=(), examined=1, exhaustive=False, exclusions={}).model_dump(mode="json")
        self.assertEqual(StaffingWorkflow(store, item, lambda: None).plan({})["outcome"], "FAILED")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.database = MagicMock()
        self.settings = SimpleNamespace(staffing_worker_enabled=True, staffing_lease_seconds=180)
        self.store = ExecutionStore(self.database, self.settings)

    def test_lease_fences_stale_or_expired_workers(self):
        for token, valid, status in (("old", 1, "RUNNING"), ("current-token", 0, "RUNNING"), ("current-token", 1, "QUEUED")):
            with self.subTest(token=token, valid=valid, status=status), patch("app.execution_store.rows", return_value=[
                {"lease_token": token, "lease_valid": valid, "status": status}]), self.assertRaises(LeaseLost):
                self.store.lock_job(None, job())

    def test_counter_budget_uses_committed_state(self):
        item = job(bundle())
        checkpoint = {**new_checkpoint(), "model_calls": 12, "analyst_model_calls": 6, "planner_model_calls": 6}
        with patch.object(self.store, "lock_job", return_value={"checkpoint_json": json_text(checkpoint)}), \
             patch("app.execution_store.execute") as write, self.assertRaises(ServiceError) as error:
            self.store.save(item, "analyst", "Call", reserve="model_calls")
        self.assertEqual(error.exception.code, "AGENT_BUDGET_EXCEEDED")
        write.assert_not_called()

    def test_terminal_state_never_assigns_or_sends_email(self):
        with patch("app.execution_store.execute") as write:
            self.store.terminal(None, "RUN-1", "READY_FOR_REVIEW", None, "Ready")
        sql = " ".join(call.args[1].lower() for call in write.call_args_list)
        self.assertNotIn("pod_assignments", sql)
        self.assertNotIn("notification_outbox", sql)
        self.assertIn("lease_token=null", sql)

    def test_both_runtime_switches_required(self):
        with patch("app.execution_store.runtime_enabled", return_value=False), self.assertRaises(ServiceError):
            self.store.require_enabled(None)
        self.settings.staffing_worker_enabled = False
        with patch("app.execution_store.runtime_enabled", return_value=True), self.assertRaises(ServiceError):
            self.store.require_enabled(None)

    def test_publication_rolls_back_all_commands_on_member_failure(self):
        data, item = bundle(), job(bundle())
        search = find_options(data)
        option = search.options[0]
        selection = Selection(plan_id=option.plan_id, explanation="Fits", evidence_refs=plan_references(data))
        committed, pending = [], []
        @contextmanager
        def transaction():
            try:
                yield None
                committed.extend(pending)
            finally:
                pending.clear()
        self.database.write = transaction
        self.settings.staffing_max_candidates = 60
        self.settings.backend_env = "local"
        def read(_conn, sql, **_binds):
            if "SELECT request_revision" in sql:
                return [{"request_revision": 1, "responsible_captain_id": "P-010", "status": "NEEDS_RECOMMENDATION"}]
            if "next_version" in sql:
                return [{"next_version": 1}]
            return []
        def write(_conn, sql, *_args):
            pending.append(sql)
            if "INSERT INTO pod_proposal_members" in sql:
                raise RuntimeError("simulated member failure")
        with patch("app.execution_store.rows", side_effect=read), patch("app.execution_store.execute", side_effect=write), \
             patch('app.policy_admin.rows', return_value=[{'policy_version': data.policy.version}]), \
             patch("app.execution_store.assert_captain"), patch("app.execution_store.collect_evidence", return_value=data), \
             patch.object(self.store, "lock_job"), self.assertRaises(RuntimeError):
            self.store.publish(item, option, selection)
        self.assertEqual(committed, [])


if __name__ == "__main__":
    unittest.main()
