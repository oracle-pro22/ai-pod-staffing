"""Actual framework tests with scripted model responses. No live credentials or database needed."""
# ruff: noqa: E402
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

MISSING = [name for name in ("langgraph", "langchain_core", "fastapi", "httpx", "jwt", "pydantic_settings", "oracledb")
           if importlib.util.find_spec(name) is None]
if MISSING:
    raise unittest.SkipTest("Phase-3 framework dependencies not installed: " + ", ".join(MISSING))

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from test_phase3 import MemoryStore, bundle, job, plan_references

from app.agents.staffing import AGENT_OUTPUT_MESSAGES, ToolSession, run_agent
from app.auth import Actor, Permission
from app.config import Settings
from app.errors import ServiceError
from app.execution_store import ExecutionStore
from app.main import create_app
from app.planning import find_options
from app.worker import process_job
from app.workflow import StaffingWorkflow


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.bound = []

    def bind_tools(self, tools, *, tool_choice=None):
        if tool_choice != "required":
            raise AssertionError("Staffing agents must explicitly require tool calls")
        self.bound.append({tool.name for tool in tools})
        return self

    def invoke(self, _messages, **_kwargs):
        calls = next(self.responses)
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{i}"}
                                                 for i, (name, args) in enumerate(calls)])


class FrameworkTests(unittest.TestCase):
    def test_invalid_tool_ids_and_arguments_are_not_executed(self):
        responses = [
            AIMessage(content="", tool_calls=[{"name": "get_request_context", "args": {}, "id": ""}]),
            AIMessage(content="", tool_calls=[{"name": "get_request_context", "args": {}, "id": "same"}] * 2),
            AIMessage(content="", invalid_tool_calls=[{"name": "get_request_context", "args": "{",
                "id": "bad", "error": "invalid JSON"}]),
        ]
        for response in responses:
            model = MagicMock()
            model.bind_tools.return_value.invoke.return_value = response
            tool_budget = MagicMock()
            with self.subTest(response=response), self.assertRaises(ServiceError) as error:
                run_agent(model, ToolSession(bundle()), lambda: None, tool_budget)
            self.assertEqual(error.exception.code, "INVALID_AGENT_OUTPUT")
            tool_budget.assert_not_called()

    def test_worker_records_only_allowlisted_output_diagnostics(self):
        for message in (*AGENT_OUTPUT_MESSAGES, "private model response"):
            store = MagicMock()
            with patch("app.worker.StaffingWorkflow") as workflow:
                workflow.return_value.run.side_effect = ServiceError("INVALID_AGENT_OUTPUT", message, 502)
                self.assertEqual(process_job(store, object(), lambda: None), {"outcome": "FAILED"})
            summary = store.finish.call_args.args[3]
            if message in AGENT_OUTPUT_MESSAGES:
                self.assertEqual(summary, message)
            else:
                self.assertNotIn(message, summary)

    def test_invalid_response_has_specific_safe_diagnostic(self):
        for calls, expected in (
            ([], "no tool call"),
            ([("get_request_context", {})] * 5, "more than four"),
            ([("get_request_context", {}), ("complete_analysis", {})], "separate final"),
        ):
            with self.subTest(expected=expected), self.assertRaises(ServiceError) as error:
                run_agent(ScriptedModel([calls]), ToolSession(bundle()), lambda: None, lambda _: None)
            self.assertEqual(error.exception.code, "INVALID_AGENT_OUTPUT")
            self.assertIn(expected, error.exception.message)

    def test_actual_graph_and_three_tool_calling_agents_publish(self):
        data = bundle()
        option = find_options(data).options[0]
        model = ScriptedModel([
            [("delegate_analysis", {})],
            [("get_request_context", {}), ("get_candidate_overview", {}), ("get_rejection_feedback", {})],
            [("complete_analysis", {"summary": "Request evidence reviewed.", "evidence_refs": ["request:REQ-1046"]})],
            [("delegate_planning", {})],
            [("get_validated_options", {})],
            [("complete_plan", {"plan_id": option.plan_id, "explanation": "Mandatory capability and known capacity fit.",
                                "evidence_refs": plan_references(data)})],
            [("finish_review", {})],
        ])
        store = MemoryStore()
        result = StaffingWorkflow(store, job(data), lambda: model).run()
        self.assertEqual(result["outcome"], "READY_FOR_REVIEW")
        self.assertEqual(len(model.bound), 6)
        self.assertIn("delegate_analysis", model.bound[0])
        self.assertIn("complete_analysis", model.bound[1])
        self.assertNotIn("complete_plan", model.bound[1])
        self.assertEqual(model.bound[2], {"complete_analysis"})
        self.assertIn("complete_plan", model.bound[4])
        self.assertIn("finish_review", model.bound[5])
        self.assertFalse(any("assign" in name or "sql" in name or "email" in name for names in model.bound for name in names))

    def test_unapproved_tool_is_blocked(self):
        model = ScriptedModel([[("execute_sql", {"sql": "DELETE FROM people"})]])
        with self.assertRaises(ServiceError) as error:
            run_agent(model, ToolSession(bundle()), lambda: None, lambda _name: None)
        self.assertEqual(error.exception.code, "UNAPPROVED_TOOL")

    def test_completion_cannot_share_turn_with_other_tools(self):
        model = ScriptedModel([[("get_request_context", {}), ("complete_analysis", {})]])
        with self.assertRaises(ServiceError) as error:
            run_agent(model, ToolSession(bundle()), lambda: None, lambda _name: None)
        self.assertEqual(error.exception.code, "INVALID_AGENT_OUTPUT")

    def test_invalid_arguments_cannot_spin_forever(self):
        model = ScriptedModel([[('get_request_context', {'person_id': 'unexpected'})]] * 12)
        call_budget, tool_budget = MagicMock(), MagicMock()
        with self.assertRaises(ServiceError) as error:
            run_agent(model, ToolSession(bundle()), call_budget, tool_budget)
        self.assertEqual(error.exception.code, "AGENT_BUDGET_EXCEEDED")
        self.assertEqual(call_budget.call_count, 6)
        self.assertEqual(tool_budget.call_count, 6)


def actor(person_id="P-010", role="POD_CAPTAIN", scope="FULL"):
    return Actor("verified-subject", person_id, frozenset({role}),
                 (Permission(role, "AGENT_EXECUTION", scope, frozenset({"view", "create"})),))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.store, self.auth = MagicMock(), MagicMock()
        self.auth.resolve.return_value = actor()
        settings = Settings(backend_env="test", backend_auth_mode="local", backend_local_token="x" * 32,
                            backend_local_subject="verified-subject")
        self.client = TestClient(create_app(settings, MagicMock(), authorization=self.auth, executions=self.store))
        self.headers = {"Authorization": "Bearer " + "x" * 32}

    def test_enqueue_uses_verified_identity_only(self):
        self.store.enqueue.return_value = {"execution_id": "RUN-1", "status": "QUEUED"}
        response = self.client.post("/v1/requests/REQ-1/executions", headers=self.headers, json={"idempotency_key": "attempt-0001"})
        self.assertEqual(response.status_code, 202)
        self.store.enqueue.assert_called_once_with("REQ-1", "verified-subject", "P-010", "attempt-0001")

    def test_cannot_send_actor_or_policy_override(self):
        for change in ({"person_id": "P-OTHER"}, {"policy_version": "bypass"}, {"idempotency_key": "   "}):
            response = self.client.post("/v1/requests/REQ-1/executions", headers=self.headers,
                                        json={"idempotency_key": "attempt-0001", **change})
            self.assertEqual(response.status_code, 422)
        self.store.enqueue.assert_not_called()

    def test_header_role_cannot_authenticate(self):
        response = self.client.post("/v1/requests/REQ-1/executions", headers={"x-staffing-role": "POD Captain"},
                                    json={"idempotency_key": "attempt-0001"})
        self.assertEqual(response.status_code, 401)
        self.store.enqueue.assert_not_called()

    def test_admin_cannot_start_captain_run(self):
        self.auth.resolve.return_value = actor(role="SYSTEM_ADMINISTRATOR")
        response = self.client.post("/v1/requests/REQ-1/executions", headers=self.headers, json={"idempotency_key": "attempt-0001"})
        self.assertEqual(response.status_code, 403)
        self.store.enqueue.assert_not_called()

    def test_read_scope_is_own_captain_or_explicit_full_admin(self):
        ExecutionStore.authorize_read(actor(), "P-010")
        ExecutionStore.authorize_read(actor(role="SYSTEM_ADMINISTRATOR"), "P-OTHER")
        for user in (actor(), actor(role="POD_LEAD"), actor(role="SYSTEM_ADMINISTRATOR", scope="OWN")):
            with self.subTest(user=user), self.assertRaises(ServiceError):
                ExecutionStore.authorize_read(user, "P-OTHER")

    def test_negative_event_cursor_rejected(self):
        response = self.client.get("/v1/executions/RUN-1?after=-1", headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.store.get_execution.assert_not_called()

    def test_execution_read_does_not_select_lease_or_candidate_evidence(self):
        db = MagicMock()
        record = {"execution_id": "RUN-1", "responsible_captain_id": "P-010", "checkpoint_json": None}
        with patch("app.execution_store.rows", side_effect=[[record], [], []]) as read:
            result = ExecutionStore(db, SimpleNamespace()).get_execution("RUN-1", actor())
        sql = read.call_args_list[0].args[1].lower()
        self.assertNotIn("lease_token", sql)
        self.assertNotIn("evidence_snapshot_json", sql)
        self.assertNotIn("checkpoint_json", result)
        self.assertEqual(result["clarification_questions"], [])


if __name__ == "__main__":
    unittest.main()
