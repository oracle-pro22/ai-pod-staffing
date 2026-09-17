import time

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.tools.model import DemoModel
from backend.tests.test_workflow import repo, request_input, decision_input


def test_http_save_starts_internal_worker_and_waits(repo):
    with TestClient(create_app(repo, DemoModel(), worker_interval=0.02)) as client:
        assert client.get("/api/health").json()["worker"] == "running"
        result = client.post("/api/requests", json=request_input(), headers={"Origin": "http://localhost:3001"})
        assert result.status_code == 202, result.text
        run_id = result.json()["run"]["run_id"]
        deadline = time.monotonic() + 15
        run = None
        while time.monotonic() < deadline:
            snapshot = client.get("/api/staffing").json()
            run = next(r for r in snapshot["data"]["runs"] if r["run_id"] == run_id)
            if run["status"] not in {"Queued", "Running"}:
                break
            time.sleep(0.03)
        assert run["status"] == "Pending Approval", run
        assert not snapshot["data"]["assignments"]
        answer = client.post("/api/chat", json={"message": "What is the status?", "request_id": result.json()["request"]["request_id"]})
        assert answer.status_code == 200 and answer.json()["source"] == "demo"
        approved = client.post(f"/api/fitment/{run_id}/decision", json=decision_input(run))
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "Approved"
        assert len(client.get("/api/staffing").json()["data"]["assignments"]) == 3
    # Restart proves the pending/approved state is persisted, not in-memory jobs.
    with TestClient(create_app(repo, DemoModel(), worker_interval=0.02)) as client:
        assert len(client.get("/api/staffing").json()["data"]["assignments"]) == 3


@pytest.mark.parametrize("update", [{"estimated_hours": True}, {"contributor_count": "2"}, {"starts_on": "2026-02-30"}, {"skill_ids": ["invalid"]}, {"priority": "bad"}])
def test_validation_has_existing_error_contract(repo, update):
    with TestClient(create_app(repo, worker_enabled=False)) as client:
        result = client.post("/api/requests", json=request_input(**update))
        assert result.status_code == 400
        assert isinstance(result.json()["error"], str)
        assert not repo.read()["runs"]


def test_origin_content_type_and_settings_rollback(repo):
    with TestClient(create_app(repo, worker_enabled=False)) as client:
        before = repo.file.read_bytes()
        assert client.post("/api/requests", json=request_input(), headers={"Origin": "https://untrusted.example"}).status_code == 403
        assert client.post("/api/requests", content="plain text").status_code == 400
        settings = {"skills_weight": 10, "allocation_weight": 25, "future_weight": 15, "interests_weight": 50, "max_allocation_pct": 85}
        assert client.post("/api/settings", json=settings).status_code == 400
        assert repo.file.read_bytes() == before
