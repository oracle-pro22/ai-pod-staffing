"""OCI Python SDK request signing; credentials stay in the configured profile."""
import asyncio
import json
import logging
import re
import time
from typing import Protocol
from urllib.parse import urlparse

from ..config import config
from ..console import log_failure
from ..repository import json_string

logger = logging.getLogger(__name__)


class Model(Protocol):
    provider: str
    name: str
    async def complete(self, system: str, context) -> str: ...


class OciModel:
    provider = "oci"

    def __init__(self):
        self.name = config().model

    async def complete(self, system, context):
        # Signing/requests are synchronous; keep API and worker event loop free.
        started = time.monotonic()
        logger.info("OCI inference started: model=%r (prompts and responses omitted)", self.name)
        try:
            result = await asyncio.to_thread(self._complete, system, context)
        except Exception as error:
            log_failure(logger, f"OCI inference failed after {time.monotonic() - started:.2f}s.", error)
            raise
        logger.info("OCI inference completed: elapsed_s=%.2f", time.monotonic() - started)
        return result

    def _complete(self, system, context):
        import requests
        from oci.config import from_file
        from oci.signer import Signer

        c = config()
        if not c.compartment_id:
            raise ValueError("OCI_COMPARTMENT_ID is missing in .env.local.")
        endpoint = urlparse(c.endpoint)
        if endpoint.scheme != "https" or not (endpoint.hostname or "").endswith(".oci.oraclecloud.com") or endpoint.username or endpoint.password:
            raise ValueError("OCI_GENAI_ENDPOINT must be an HTTPS OCI inference endpoint.")
        if c.api_format not in {"native", "responses"}:
            raise ValueError("OCI_GENAI_API_FORMAT must be native or responses.")
        native = c.api_format == "native"
        if not native and not c.project_id:
            raise ValueError("OCI_GENAI_PROJECT_OCID is required for the OCI Responses API. Set it in .env.local.")
        origin = f"{endpoint.scheme}://{endpoint.netloc}"
        url = origin + ("/20231130/actions/chat" if native else "/openai/v1/responses")
        text = json_string(context)
        if native:
            body = {"compartmentId": c.compartment_id, "servingMode": {"servingType": "ON_DEMAND", "modelId": c.model},
                    "chatRequest": {"apiFormat": "GENERIC", "isStream": False,
                                    ("maxCompletionTokens" if c.model.startswith("openai.") else "maxTokens"): 6000 if c.model.startswith("openai.") else 4000,
                                    "messages": [{"role": "SYSTEM", "content": [{"type": "TEXT", "text": system}]},
                                                 {"role": "USER", "content": [{"type": "TEXT", "text": text}]}]}}
        else:
            body = {"model": c.model, "instructions": system, "input": text, "max_output_tokens": 6000, "store": False}
        try:
            profile = from_file(c.config_file, c.profile)
            signer = Signer(tenancy=profile["tenancy"], user=profile["user"], fingerprint=profile["fingerprint"],
                            private_key_file_location=profile["key_file"], pass_phrase=profile.get("pass_phrase"))
        except Exception:
            logger.error("Cannot load OCI signing profile; check config/profile settings and key-file permissions. Credentials omitted.")
            raise ValueError("Cannot load the OCI API-signing profile. Check OCI_CONFIG_FILE, OCI_CONFIG_PROFILE and key_file permissions.") from None
        headers = {"Content-Type": "application/json"}
        if not native:
            headers["OpenAI-Project"] = c.project_id
        try:
            response = requests.post(url, data=json_string(body).encode("utf-8"), headers=headers, auth=signer,
                                     timeout=(min(10, c.timeout), c.timeout), allow_redirects=False)
        except requests.RequestException:
            logger.error("OCI network connection failed or timed out; check connectivity and configured region.")
            raise ValueError("OCI inference could not be reached or timed out. Check network access and the configured region.") from None
        if not response.ok or response.is_redirect:
            logger.error("OCI inference HTTP status=%s; verify IAM permission, model, region and API format. Response body omitted.", response.status_code)
            # Never return signed headers, response bodies, paths or data to the UI.
            raise ValueError(f"OCI inference returned HTTP {response.status_code}. Verify IAM permission, model {c.model}, region and API format in .env.local. No assignments were made.")
        try:
            payload = response.json()
            content = payload["chatResponse"]["choices"][0]["message"]["content"] if native else [c for item in payload["output"] for c in item.get("content", [])]
            output = "".join(c.get("text", "") for c in content)
            if not output.strip():
                raise ValueError()
            return output
        except (ValueError, KeyError, TypeError, IndexError):
            raise ValueError("OCI returned no usable text. Confirm the selected model supports the configured API format.") from None


class DemoModel:
    provider = "demo"
    name = "Deterministic demo (no model call)"

    async def complete(self, system, context):
        raise AssertionError("Demo workers must not invoke inference.")


def get_model():
    return DemoModel() if config().provider == "demo" else OciModel()


def json_object(text):
    try:
        value = json.loads(re.sub(r"\s*```$", "", re.sub(r"^```(?:json)?\s*", "", text.strip())))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise ValueError("The model returned invalid structured output. Retry the workflow.") from None
