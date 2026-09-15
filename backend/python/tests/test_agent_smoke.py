# ruff: noqa: E402 -- Skip explicitly before importing uninstalled agent dependencies.
import importlib.util
import unittest

MISSING = [name for name in ("langgraph", "langchain_core") if importlib.util.find_spec(name) is None]
if MISSING:
    raise unittest.SkipTest("Agent dependencies not installed: " + ", ".join(MISSING))

from langchain_core.messages import AIMessage

from app.agents.smoke import run_smoke


class FakeModel:
    """Only tests our graph routing; it does not prove OCI compatibility."""
    def __init__(self, calls=None, repeats=False):
        self.calls = calls if calls is not None else [{"name": "calculate_weekly_percentage",
            "args": {"committed_hours": 16, "available_hours": 40}, "id": "call-1", "type": "tool_call"}]
        self.repeats = repeats
        self.count = 0

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages, config=None):
        self.count += 1
        if self.count == 1 or self.repeats:
            return AIMessage(content="", tool_calls=self.calls)
        return AIMessage(content="40%")


class AgentSmokeTests(unittest.TestCase):
    def test_tool_cycle(self):
        model = FakeModel()
        result = run_smoke(model)
        self.assertEqual(result["tool_result"], {"allocation_pct": 40.0})
        self.assertTrue(result["final_received"])
        self.assertEqual(model.count, 2)

    def test_model_must_actually_call_tool(self):
        with self.assertRaises(ValueError):
            run_smoke(FakeModel(calls=[]))

    def test_extra_tool_loop_is_rejected(self):
        with self.assertRaises(ValueError):
            run_smoke(FakeModel(repeats=True))

    def test_unapproved_tool_rejected(self):
        with self.assertRaises(ValueError):
            run_smoke(FakeModel(calls=[{"name": "execute_sql", "args": {}, "id": "call-1", "type": "tool_call"}]))
