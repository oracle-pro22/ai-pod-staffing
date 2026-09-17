import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
import requests
import oci.config
import oci.signer

from backend import check_dependencies
from backend.config import config
from backend.tools import model as adapter


@pytest.fixture
def transport(monkeypatch):
    calls = []
    monkeypatch.setattr(oci.config, "from_file", lambda *a: {"tenancy": "qa", "user": "qa", "fingerprint": "qa", "key_file": "/unused/qa.pem"})
    monkeypatch.setattr(oci.signer, "Signer", lambda **kw: "mock-signer")

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(ok=True, is_redirect=False, json=lambda: {"chatResponse": {"choices": [{"message": {"content": [{"text": "OK"}]}}]}})
    monkeypatch.setattr(requests, "post", post)
    original = config()
    monkeypatch.setattr(adapter, "config", lambda: replace(original, api_format="native", compartment_id="qa", model="openai.gpt-5.5"))
    return calls


def test_python_oci_payload_and_signing_contract(transport):
    assert asyncio.run(adapter.OciModel().complete("Return OK", {"test": "fictional"})) == "OK"
    url, request = transport[0]
    assert url.endswith("/20231130/actions/chat")
    body = json.loads(request["data"])
    assert body["chatRequest"]["maxCompletionTokens"] == 6000
    assert "maxTokens" not in body["chatRequest"]
    assert request["auth"] == "mock-signer"
    assert request["allow_redirects"] is False
    assert request["timeout"][1] <= 90


def test_oci_error_does_not_leak_response_or_credentials(transport, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: SimpleNamespace(ok=False, is_redirect=False, status_code=401, text="secret server response"))
    with pytest.raises(ValueError, match="HTTP 401") as error:
        asyncio.run(adapter.OciModel().complete("test", {}))
    assert "secret" not in str(error.value)
    assert ".pem" not in str(error.value)


def test_responses_requires_project_and_untrusted_endpoint_rejected(transport, monkeypatch):
    c = adapter.config()
    monkeypatch.setattr(adapter, "config", lambda: replace(c, api_format="responses", project_id=""))
    with pytest.raises(ValueError, match="PROJECT_OCID"):
        asyncio.run(adapter.OciModel().complete("test", {}))
    monkeypatch.setattr(adapter, "config", lambda: replace(c, endpoint="https://untrusted.example"))
    with pytest.raises(ValueError, match="HTTPS OCI inference"):
        asyncio.run(adapter.OciModel().complete("test", {}))
    assert not transport


def test_pinned_environment_is_ready():
    assert check_dependencies.main() == 0
