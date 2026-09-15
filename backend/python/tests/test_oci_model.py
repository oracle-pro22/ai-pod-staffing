"""Offline OCI request construction checks: no credentials or model calls."""
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from oci.generative_ai_inference.models import FunctionCall, TextContent

from app.agents.oci_model import _ToolAwareGenericProvider, build_model
from app.agents.smoke import calculate_weekly_percentage
from app.config import Settings


class OciModelTests(unittest.TestCase):
    @staticmethod
    def reply(calls=(), text=None):
        message = SimpleNamespace(
            content=[] if text is None else [TextContent(text=text)], tool_calls=list(calls),
        )
        return SimpleNamespace(
            data=SimpleNamespace(
                model_id="test-model", model_version="1",
                chat_response=SimpleNamespace(
                    choices=[SimpleNamespace(message=message, finish_reason="stop")],
                    time_created="2026-09-13T00:00:00Z",
                ),
            ),
            request_id="test-request", headers={"content-length": "1"},
        )

    @staticmethod
    def call(arguments='{"committed_hours":16,"available_hours":40}', call_id="call-1",
             name="calculate_weekly_percentage"):
        return FunctionCall(id=call_id, name=name, arguments=arguments)

    def build(self, provider):
        settings = Settings(
            _env_file=None,
            oci_genai_endpoint="https://inference.generativeai.us-chicago-1.oci.oraclecloud.com",
            oci_genai_compartment_id="test-compartment",
            oci_genai_model_id="test-model",
            oci_genai_provider=provider,
            oci_max_output_tokens=2048,
        )
        client = MagicMock()
        with patch("oci.config.from_file", return_value={}), patch(
            "oci.generative_ai_inference.GenerativeAiInferenceClient", return_value=client
        ):
            model = build_model(settings)
        return model, client

    def test_generic_tool_request_disables_reasoning(self):
        model, client = self.build("generic")
        bound = model.bind_tools([calculate_weekly_percentage])
        request = model._prepare_request(
            [HumanMessage(content="Calculate 16 out of 40.")],
            stop=None, stream=False, **bound.kwargs,
        )
        self.assertEqual(request.chat_request.reasoning_effort, "NONE")
        self.assertIs(request.chat_request.is_parallel_tool_calls, False)
        self.assertEqual(request.chat_request.max_completion_tokens, 2048)
        self.assertEqual(len(request.chat_request.tools), 1)
        self.assertIsNone(request.chat_request.max_tokens)
        client.chat.assert_not_called()

    def test_required_tools_survive_tool_results_in_oci_request(self):
        model, client = self.build("generic")
        bound = model.bind_tools([calculate_weekly_percentage], tool_choice="required")
        messages = [HumanMessage(content="Use tools.")]
        # Beyond the provider's default eight-call stop heuristic. Our worker
        # owns the durable call budgets and still requires a completion tool.
        for i in range(8):
            messages.extend([
                AIMessage(content="", tool_calls=[{"name": "calculate_weekly_percentage",
                    "args": {"committed_hours": 16, "available_hours": 40}, "id": f"call-{i}"}]),
                ToolMessage(content='{"allocation_pct":40}', tool_call_id=f"call-{i}"),
            ])
        request = model._prepare_request(messages, stop=None, stream=False, **bound.kwargs)
        self.assertEqual(request.chat_request.tool_choice.type, "REQUIRED")
        self.assertEqual(request.chat_request.reasoning_effort, "NONE")
        self.assertIs(request.chat_request.is_parallel_tool_calls, False)
        client.chat.assert_not_called()

    def test_other_provider_keeps_existing_parameters(self):
        model, client = self.build("cohere")
        self.assertEqual(model.model_kwargs, {"max_tokens": 2048})
        self.assertNotIsInstance(model._provider, _ToolAwareGenericProvider)
        client.chat.assert_not_called()

    def test_native_tool_only_reply_keeps_calls_without_false_text_warning(self):
        model, client = self.build("generic")
        client.chat.return_value = self.reply([self.call()])
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            message = model.invoke([HumanMessage(content="Use the tool.")])
        self.assertEqual(recorded, [])
        self.assertEqual(message.content, "")
        self.assertEqual(message.tool_calls, [{
            "name": "calculate_weekly_percentage", "args": {"committed_hours": 16, "available_hours": 40},
            "id": "call-1", "type": "tool_call",
        }])
        self.assertEqual(calculate_weekly_percentage.invoke(message.tool_calls[0]["args"]), {"allocation_pct": 40})
        client.chat.assert_called_once()

    def test_text_with_tools_and_ordinary_text_remain_unchanged(self):
        model, client = self.build("generic")
        for calls in ([], [self.call()]):
            with self.subTest(calls=bool(calls)):
                client.chat.return_value = self.reply(calls, text="Recorded evidence.")
                with warnings.catch_warnings(record=True) as recorded:
                    warnings.simplefilter("always")
                    message = model.invoke([HumanMessage(content="Read the evidence.")])
                self.assertEqual(recorded, [])
                self.assertEqual(message.content, "Recorded evidence.")
                self.assertEqual(len(message.tool_calls), len(calls))

    def test_genuinely_empty_reply_keeps_upstream_warning(self):
        model, client = self.build("generic")
        client.chat.return_value = self.reply()
        with self.assertWarnsRegex(UserWarning, "GenericProvider could not extract text"):
            message = model.invoke([HumanMessage(content="Use the tool.")])
        self.assertEqual(message.content, "")
        self.assertEqual(message.tool_calls, [])

    def test_malformed_json_keeps_upstream_warning_and_raw_arguments(self):
        model, client = self.build("generic")
        client.chat.return_value = self.reply([self.call(arguments="not-json")])
        with self.assertWarnsRegex(UserWarning, "GenericProvider could not extract text"):
            message = model.invoke([HumanMessage(content="Use the tool.")])
        self.assertEqual(message.tool_calls[0]["args"], {"_raw_arguments": "not-json"})

    def test_missing_ids_duplicate_ids_and_non_object_arguments_are_not_silenced(self):
        model, client = self.build("generic")
        for calls in ([self.call(call_id=None)], [self.call(), self.call()],
                      [self.call(arguments="[]")], [self.call(name="")]):
            with self.subTest(calls=calls):
                response = self.reply(calls)
                with self.assertWarnsRegex(UserWarning, "GenericProvider could not extract text"):
                    self.assertEqual(model._provider.chat_response_to_text(response), "")
        # The adapter does not swallow the normal model validation error either.
        client.chat.return_value = self.reply([self.call(arguments="[]")])
        with self.assertWarnsRegex(UserWarning, "GenericProvider could not extract text"):
            with self.assertRaises(ValueError):
                model.invoke([HumanMessage(content="Use the tool.")])

    def test_unrelated_warnings_are_not_filtered(self):
        model, client = self.build("generic")

        def chat(*_args, **_kwargs):
            warnings.warn("Unrelated provider diagnostic", UserWarning)
            return self.reply([self.call()])

        client.chat.side_effect = chat
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            model.invoke([HumanMessage(content="Use the tool.")])
        self.assertEqual([str(item.message) for item in recorded], ["Unrelated provider diagnostic"])

    def test_adapter_is_instance_local_and_does_not_change_upstream_provider(self):
        from langchain_oci.chat_models.providers.generic import GenericProvider

        first, _ = self.build("generic")
        second, _ = self.build("generic")
        self.assertIsInstance(first._provider, _ToolAwareGenericProvider)
        self.assertIsNot(first._provider, second._provider)
        self.assertIsNot(first._provider._delegate, second._provider._delegate)
        with self.assertWarnsRegex(UserWarning, "GenericProvider could not extract text"):
            self.assertEqual(GenericProvider().chat_response_to_text(self.reply([self.call()])), "")
