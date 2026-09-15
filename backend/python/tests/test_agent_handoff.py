"""The Analyst must hand off request inputs, not demand downstream computed outputs."""
import copy
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from pydantic import ValidationError
from test_demo_agent_planning import data
from test_phase3 import MemoryStore, job
from test_phase3_runtime import ScriptedModel

from app.agent_budget import reserve_call
from app.agents.staffing import (
    ANALYST_READS,
    ANALYST_TASK,
    BUSINESS_QUESTIONS,
    COMMON,
    Analysis,
    ToolSession,
    required_plan_references,
    run_agent,
)
from app.engine_version import new_checkpoint
from app.errors import ServiceError
from app.planning import find_options
from app.workflow import StaffingWorkflow


def complete_context():
    return data(context={
        "business_objectives": "Prepare a sales guide that helps the sales team explain the new AI service.",
        "expected_outcomes": "A reviewed deck covering capabilities, customer benefits and talking points.",
        "project_description": "Launch materials for the new AI service.",
    })


def analysis_values(**changes):
    return {"summary": "Sales guide scope and relevant recorded capabilities reviewed; planning follows.",
            "evidence_refs": ["request:REQ-1046"], "clarification_fields": [], **changes}


def evidence_calls():
    return [[(name, {})] for name in ("get_request_context", "get_candidate_overview", "get_rejection_feedback")]


class BudgetedMemoryStore(MemoryStore):
    """Offline graph test with the same counter reservation as Oracle, no I/O."""
    def save(self, item, stage, summary, reserve=None, **kwargs):
        if reserve:
            item.checkpoint.update(reserve_call(item.checkpoint, stage, reserve, item.evidence.policy.maximum_agent_steps))
        super().save(item, stage, summary, **kwargs)


class ClarificationContractTests(unittest.TestCase):
    def session(self, source=None):
        session = ToolSession(source or complete_context())
        session.seen.update(ANALYST_READS)
        return session

    def test_analyst_has_only_stage_relevant_tools_and_prompt(self):
        tools = set(self.session().tools())
        self.assertEqual(tools, ANALYST_READS | {"complete_analysis"})
        self.assertIn("NEXT stage calculates the hour split", ANALYST_TASK)
        self.assertIn("NEVER ask the Captain", ANALYST_TASK)
        self.assertNotIn("Explain relevant recorded skills", COMMON)
        self.assertNotIn("Compare only the validated options", COMMON)

    def test_computed_outputs_are_explicitly_not_missing_request_inputs(self):
        context = self.session().request_context()
        self.assertEqual(context["available_clarifications"], {})
        self.assertIn("not missing request inputs", context["planning_handoff"])
        self.assertEqual(context["request"]["total_hours"], "24")
        self.assertNotIn("options", context)
        self.assertNotIn("projected_allocation_pct", context)

    def test_exact_bad_hour_split_question_cannot_block_request(self):
        session = self.session()
        with self.assertRaises(ValidationError):
            session.complete_analysis(**analysis_values(), clarification_questions=[
                "What proposed hour split should be used across the lead and two members? Without it, "
                "actual contribution hours and server-calculated projected allocation measures cannot be evaluated."])
        self.assertIsNone(session.result)

    def test_agent_cannot_relabel_derived_or_present_inputs_as_missing(self):
        for field in ("hour_split", "projected_allocation_pct", "preferred_person", "business_objectives"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.session().complete_analysis(**analysis_values(clarification_fields=[field]))

    def test_genuine_missing_business_input_uses_server_question(self):
        source = complete_context()
        source.context["business_objectives"] = "  "
        session = self.session(source)
        self.assertEqual(session.request_context()["available_clarifications"],
                         {"business_objectives": BUSINESS_QUESTIONS["business_objectives"]})
        session.complete_analysis(**analysis_values(clarification_fields=["business_objectives"]))
        self.assertEqual(session.result.clarification_questions, (BUSINESS_QUESTIONS["business_objectives"],))
        self.assertEqual(Analysis.model_validate_json(session.result.model_dump_json()), session.result)

    def test_blank_optional_context_is_not_automatically_a_blocker(self):
        session = self.session(data())
        session.complete_analysis(**analysis_values())
        self.assertEqual(session.result.clarification_questions, ())

    def test_duplicates_and_invented_saved_questions_are_rejected(self):
        with self.assertRaises(ValueError):
            self.session(data()).complete_analysis(**analysis_values(
                clarification_fields=["business_objectives", "business_objectives"]))
        with self.assertRaises(ValueError):
            Analysis(**analysis_values(), clarification_questions=["Provide computed hours."])

    def test_resumed_analysis_cannot_claim_filled_field_is_missing(self):
        item = job(complete_context())
        item.checkpoint["analysis"] = Analysis(**analysis_values(clarification_fields=["business_objectives"]),
            clarification_questions=[BUSINESS_QUESTIONS["business_objectives"]]).model_dump(mode="json")
        store = BudgetedMemoryStore()
        with self.assertRaises(ServiceError) as error:
            StaffingWorkflow(store, item, lambda: None).analyse({})
        self.assertEqual(error.exception.code, "INVALID_CHECKPOINT")
        self.assertIsNone(store.outcome)


class HandoffGraphTests(unittest.TestCase):
    def test_bad_analysis_is_repaired_then_real_24_hour_plan_reaches_review(self):
        source = complete_context()
        option = find_options(source).options[0]
        model = ScriptedModel([
            *evidence_calls(),
            [("complete_analysis", {**analysis_values(), "clarification_questions": [
                "What proposed hour split should be used across the lead and two members?"]})],
            [("complete_analysis", analysis_values(clarification_fields=["projected_allocation_pct"]))],
            [("complete_analysis", analysis_values())],
            [("get_validated_options", {})],
            [("complete_plan", {"plan_id": option.plan_id,
                "explanation": "The returned plan supplies meaningful contributions within known capacity.",
                "evidence_refs": sorted(required_plan_references(source, option.proposal))})],
        ])
        store, item = BudgetedMemoryStore(), job(source)
        item.checkpoint = new_checkpoint()
        result = StaffingWorkflow(store, item, lambda: model).run()
        self.assertEqual(result["outcome"], "READY_FOR_REVIEW")
        self.assertEqual(item.checkpoint["analyst_model_calls"], 6)
        self.assertEqual(item.checkpoint["planner_model_calls"], 2)
        self.assertEqual(item.checkpoint["model_calls"], 8)
        self.assertEqual(item.checkpoint["analysis"]["clarification_questions"], [])
        self.assertEqual([member.hours for member in store.published[0].proposal.members], [Decimal(8)] * 3)
        self.assertEqual(sum(day.hours for member in store.published[0].proposal.members
                             for day in member.daily_schedule), Decimal(24))
        self.assertIn({"complete_analysis"}, model.bound)

    def test_genuine_missing_input_still_stops_before_planning(self):
        source = complete_context()
        source.context["business_objectives"] = ""
        model = ScriptedModel([*evidence_calls(), [("complete_analysis",
            analysis_values(clarification_fields=["business_objectives"]))]])
        store, item = BudgetedMemoryStore(), job(source)
        item.checkpoint = new_checkpoint()
        self.assertEqual(StaffingWorkflow(store, item, lambda: model).run()["outcome"], "NEEDS_INFORMATION")
        self.assertNotIn("search", item.checkpoint)
        self.assertEqual(item.checkpoint["planner_model_calls"], 0)
        self.assertFalse(hasattr(store, "published"))

    def test_missing_capacity_still_stops_without_invented_free_capacity(self):
        source = complete_context()
        source.ledgers.clear()
        source.exclusions.update({person.person_id: "CAPACITY_UNKNOWN" for person in source.candidates})
        model = ScriptedModel([*evidence_calls(), [("complete_analysis", analysis_values())]])
        store, item = BudgetedMemoryStore(), job(source)
        item.checkpoint = new_checkpoint()
        self.assertEqual(StaffingWorkflow(store, item, lambda: model).run()["outcome"], "NEEDS_INFORMATION")
        self.assertEqual(item.checkpoint["analysis"]["clarification_questions"], [])
        self.assertFalse(hasattr(store, "published"))

    def test_completion_only_cannot_be_avoided_by_repeating_evidence_reads(self):
        source, calls = complete_context(), MagicMock()
        model = ScriptedModel([*evidence_calls(), *[[('get_request_context', {})]] * 6])
        with self.assertRaises(ServiceError) as error:
            run_agent(model, ToolSession(source), calls, lambda _: None)
        self.assertEqual(error.exception.code, "AGENT_BUDGET_EXCEEDED")
        self.assertEqual(calls.call_count, 6)
        self.assertEqual(model.bound[-1], {"complete_analysis"})

    def test_resumed_exhausted_analyst_cannot_restart_its_model_allowance(self):
        source, model, store = complete_context(), MagicMock(), BudgetedMemoryStore()
        item = job(source)
        item.checkpoint = {**new_checkpoint(), "model_calls": 6, "analyst_model_calls": 6}
        original = copy.deepcopy(item.checkpoint)
        with self.assertRaises(ServiceError) as error:
            StaffingWorkflow(store, item, lambda: model).analyse({})
        self.assertEqual(error.exception.code, "AGENT_BUDGET_EXCEEDED")
        model.bind_tools.return_value.invoke.assert_not_called()
        self.assertEqual(item.checkpoint, original)

    def test_transient_third_call_resumes_completed_reads_without_resetting_budget(self):
        source, store = complete_context(), BudgetedMemoryStore()
        item = job(source)
        item.checkpoint = new_checkpoint()

        class TimeoutModel(ScriptedModel):
            def invoke(self, messages, **kwargs):
                try:
                    return super().invoke(messages, **kwargs)
                except StopIteration:
                    raise TimeoutError("temporary model timeout") from None

        with self.assertRaises(TimeoutError):
            StaffingWorkflow(store, item, lambda: TimeoutModel(evidence_calls()[:2])).analyse({})
        self.assertEqual(item.checkpoint["analyst_model_calls"], 3)
        self.assertEqual(set(item.checkpoint["analysis_reads"]), {"get_request_context", "get_candidate_overview"})

        class ResumingModel(ScriptedModel):
            def invoke(self, messages, **kwargs):
                self.last_messages = list(messages)
                return super().invoke(messages, **kwargs)

        option = find_options(source).options[0]
        model = ResumingModel([
            [("get_rejection_feedback", {})], [("complete_analysis", analysis_values())],
            [("get_validated_options", {})], [("complete_plan", {
                "plan_id": option.plan_id, "explanation": "Returned plan fits capacity.",
                "evidence_refs": sorted(required_plan_references(source, option.proposal))})],
        ])
        flow = StaffingWorkflow(store, item, lambda: model)
        self.assertEqual(flow.analyse({})["outcome"], "RUNNING")
        restored_calls = [call["name"] for message in model.last_messages
                          for call in getattr(message, "tool_calls", [])
                          if call["id"].startswith("checkpoint-read-")]
        self.assertCountEqual(restored_calls, ["get_request_context", "get_candidate_overview"])
        self.assertEqual(item.checkpoint["analyst_model_calls"], 5)
        self.assertEqual(flow.plan({})["outcome"], "RUNNING")
        self.assertEqual(flow.publish({})["outcome"], "READY_FOR_REVIEW")
        self.assertEqual(item.checkpoint["model_calls"], 7)

    def test_malformed_or_non_read_checkpoint_progress_is_never_replayed(self):
        for reads in ({"get_request_context": True}, ["get_request_context"] * 2,
                      ["complete_analysis"], ["execute_sql"], [42]):
            item, factory = job(complete_context()), MagicMock()
            item.checkpoint = {**new_checkpoint(), "analysis_reads": reads}
            with self.subTest(reads=reads), self.assertRaises(ServiceError) as error:
                StaffingWorkflow(BudgetedMemoryStore(), item, factory).analyse({})
            self.assertEqual(error.exception.code, "INVALID_CHECKPOINT")
            factory.assert_not_called()

    def test_failure_saving_read_is_not_treated_as_model_argument_error(self):
        model = ScriptedModel(evidence_calls())
        save = MagicMock(side_effect=ValueError("checkpoint transaction failed"))
        with self.assertRaisesRegex(ValueError, "checkpoint transaction failed"):
            run_agent(model, ToolSession(complete_context()), lambda: None, lambda _: None,
                      after_analysis_read=save)
        save.assert_called_once_with("get_request_context")


if __name__ == "__main__":
    unittest.main()
