import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from backend.agents.supervisor import process_next
from backend.console import configure_logging, run_context
from backend.main import create_app
from backend.service import save_request
from backend.tests.test_workflow import repo, request_input
from backend.tools.model import DemoModel, OciModel


def test_logging_configuration_is_idempotent_and_scoped(monkeypatch):
    app_logger = logging.getLogger("backend")
    monkeypatch.setattr(app_logger, "handlers", [])
    monkeypatch.setattr(app_logger, "level", app_logger.level)
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")
    sdk_level = logging.getLogger("oci").level
    assert configure_logging() == "DEBUG"
    configure_logging()
    assert len(app_logger.handlers) == 1
    assert app_logger.level == logging.DEBUG
    assert logging.getLogger("oci").level == sdk_level
    monkeypatch.setenv("APP_LOG_LEVEL", "INVALID")
    with pytest.raises(ValueError, match="APP_LOG_LEVEL"):
        configure_logging()


def test_http_logs_status_and_safe_template_not_payloads(repo, caplog, monkeypatch):
    monkeypatch.setenv("APP_LOG_LEVEL", "INFO")
    with TestClient(create_app(repo, DemoModel(), worker_enabled=False)) as client:
        client.get("/api/staffing?token=PRIVATE_QUERY")
        assert "HTTP GET /api/staffing" not in caplog.text
        result = client.post("/api/requests?token=PRIVATE_QUERY", json=request_input(title="PRIVATE_TITLE"))
        assert result.status_code == 202
        assert "Save request completed" in caplog.text
        assert "HTTP POST /api/requests status=202" in caplog.text
        assert client.post("/api/requests/PRIVATE_PATH/run", content="PRIVATE_BODY").status_code == 400
        assert "HTTP POST /api/requests/{request_id}/run status=400" in caplog.text
        assert client.get("/PRIVATE_UNKNOWN_PATH").status_code == 404
        assert "HTTP GET <unmatched> status=404" in caplog.text
        with caplog.at_level(logging.DEBUG, logger="backend"):
            client.get("/api/health")
        assert "HTTP GET /api/health status=200" in caplog.text
    app_messages = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("backend."))
    assert "PRIVATE_" not in app_messages


def test_workflow_logs_stages_and_approval_pause_without_content(repo, caplog):
    result = save_request(request_input(title="PRIVATE_TITLE", business_context="PRIVATE_CONTEXT"), repo)
    with caplog.at_level(logging.INFO, logger="backend"):
        asyncio.run(process_next(repo, DemoModel()))
    for message in ("Worker=Request analyst", "Worker=Fitment analyst", "Scoring saved: candidates=8", "Worker=Recommendation writer", "status=Pending Approval", "assignments_created=0", "Supervisor paused"):
        assert message in caplog.text
    assert "PRIVATE_" not in caplog.text
    assert not repo.read()["assignments"]
    assert run_context.get() == "-"
    # The handler decorates every stage with the same run identifier.
    if any(hasattr(r, "run_id") for r in caplog.records):
        assert all(r.run_id == result["run"]["run_id"] for r in caplog.records if r.name == "backend.agents.supervisor")


def test_model_timing_and_failures_never_log_payloads(monkeypatch, caplog):
    model = OciModel()
    monkeypatch.setattr(model, "_complete", lambda *args: "PRIVATE_RESPONSE")
    with caplog.at_level(logging.DEBUG, logger="backend"):
        assert asyncio.run(model.complete("PRIVATE_PROMPT", {"secret": "PRIVATE_CONTEXT"})) == "PRIVATE_RESPONSE"
        def fail(*args):
            raise ValueError("PRIVATE_ERROR_PAYLOAD")
        monkeypatch.setattr(model, "_complete", fail)
        with pytest.raises(ValueError):
            asyncio.run(model.complete("PRIVATE_PROMPT", {}))
    assert "OCI inference started" in caplog.text
    assert "OCI inference completed: elapsed_s=" in caplog.text
    assert "OCI inference failed after" in caplog.text
    assert "error_type=ValueError" in caplog.text
    assert "Failure locations" in caplog.text
    assert "PRIVATE_" not in caplog.text
