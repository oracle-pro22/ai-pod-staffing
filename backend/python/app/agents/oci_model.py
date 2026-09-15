from pathlib import Path

from app.config import Settings
from app.errors import ServiceError


class _ToolAwareGenericProvider:
    """Keep OCI's parser, except its false warning for a valid tool-only reply.

    ChatOCIGenAI extracts text before extracting native tool calls. GenericProvider
    warns on empty text even when those calls are the entire intended response.
    Wrap only this model's cached provider: no global warning filters or SDK edits.
    All request building, tool conversion and other response paths stay upstream.
    """

    def __init__(self, provider):
        self._delegate = provider

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def _valid_tool_only_response(self, response):
        from langchain_oci.common.utils import OCIUtils

        choices = response.data.chat_response.choices
        if not choices or choices[0].message is None:
            return False
        message = choices[0].message
        if any(getattr(part, "text", None) for part in (message.content or [])):
            return False
        calls = message.tool_calls
        if not isinstance(calls, (list, tuple)) or not calls:
            return False
        ids = set()
        for call in calls:
            # Do not let the SDK's generated-ID or malformed-JSON fallbacks hide
            # an incomplete response. The normal parser will still report it.
            if not isinstance(call.id, str) or not call.id.strip() or call.id in ids:
                return False
            if not isinstance(call.name, str) or not call.name.strip():
                return False
            converted = OCIUtils.convert_oci_tool_call_to_langchain(call)
            if not isinstance(converted["args"], dict) or "_raw_arguments" in converted["args"]:
                return False
            ids.add(call.id)
        return True

    def chat_response_to_text(self, response):
        try:
            if self._valid_tool_only_response(response):
                return ""
        except (AttributeError, IndexError, TypeError, ValueError):
            # Preserve upstream warnings/errors for unexpected or malformed data.
            pass
        return self._delegate.chat_response_to_text(response)


def build_model(settings: Settings):
    """Use the OCI SDK's own auth/signing rather than porting the TypeScript signer."""
    import oci
    from langchain_oci import ChatOCIGenAI

    if not all((settings.oci_genai_endpoint, settings.oci_genai_compartment_id, settings.oci_genai_model_id)):
        raise ServiceError("OCI_NOT_CONFIGURED", "Set the OCI endpoint, compartment and model before testing.", 503)
    if not settings.oci_genai_provider:
        raise ServiceError("OCI_PROVIDER_REQUIRED", "Configure the model's confirmed provider (for example generic, meta or cohere).", 503)
    config = oci.config.from_file(str(Path(settings.oci_config_file).expanduser()), settings.oci_config_profile)
    client = oci.generative_ai_inference.GenerativeAiInferenceClient(
        config=config, service_endpoint=settings.oci_genai_endpoint,
        timeout=(5, settings.oci_timeout_seconds), retry_strategy=oci.retry.NoneRetryStrategy(),
    )
    # Generic OpenAI-family models use max_completion_tokens. Do not blindly pass temperature
    # or legacy max_tokens parameters unsupported by reasoning models.
    provider = settings.oci_genai_provider
    token_parameter = "max_completion_tokens" if provider == "generic" else "max_tokens"
    model_kwargs = {token_parameter: settings.oci_max_output_tokens}
    if provider == "generic":
        # This agent uses OCI's chat endpoint with function tools. The configured
        # OpenAI-family model requires reasoning disabled for that combination.
        # OCI's SDK enum is uppercase, unlike the underlying model API value.
        model_kwargs["reasoning_effort"] = "NONE"
        model_kwargs["is_parallel_tool_calls"] = False
    model = ChatOCIGenAI(client=client, model_id=settings.oci_genai_model_id, provider=provider,
                        compartment_id=settings.oci_genai_compartment_id,
                        service_endpoint=settings.oci_genai_endpoint,
                        model_kwargs=model_kwargs, disable_streaming=True)
    if provider == "generic":
        model._cached_provider_instance = _ToolAwareGenericProvider(model._provider)
    return model
