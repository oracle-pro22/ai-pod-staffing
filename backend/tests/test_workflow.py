import asyncio
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from zipfile import ZipFile

import pytest

from backend.agents.supervisor import process_next
from backend.config import ROOT
from backend.repository import ExcelRepository
from backend.service import decide, rerun, save_request
from backend.tools.model import DemoModel
from backend.tools.scoring import business_days, data_hash, score_candidates, weights


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "demo")
    file = tmp_path / "staffing.xlsx"
    shutil.copyfile(ROOT / "data/agentic-staffing.xlsx", file)
    repository = ExcelRepository(file)
    # Retain the eight-person golden regression fixture even when the seed grows.
    def historical_fixture(db):
        for key in ("people", "personSkills", "preferences", "availability"):
            db[key] = [r for r in db[key] if not r["person_id"].startswith("SYN-")]
    repository.transaction(historical_fixture)
    return repository


def request_input(**overrides):
    return {"title": "New launch communications", "work_type": "Communication", "owner_name": "Test Request Lead",
            "starts_on": "2026-10-05", "needed_by": "2026-10-16", "estimated_hours": 30, "contributor_count": 2,
            "priority": "High", "business_context": "Create customer launch communications and review the plan.",
            "skill_ids": ["SK-002", "SK-003", "SK-004"], "submission_key": str(uuid4()), **overrides}


def run_for(repo, run_id):
    return next(r for r in repo.read()["runs"] if r["run_id"] == run_id)


def pending(repo):
    created = save_request(request_input(), repo)
    asyncio.run(process_next(repo, DemoModel()))
    run = run_for(repo, created["run"]["run_id"])
    assert run["status"] == "Pending Approval", run["error"]
    return run


def decision_input(run, **overrides):
    return {"action": "approve", "reason": "Reviewed all four factors", "selected_ids": json.loads(run["proposed_ids_json"]),
            "revision": run["revision"], "idempotency_key": str(uuid4()), **overrides}


def test_save_pause_approval_idempotency_and_preservation(repo):
    created = save_request(request_input(), repo)
    run_id = created["run"]["run_id"]
    assert created["run"]["status"] == "Queued"
    assert repo.read()["assignments"] == []
    with pytest.raises(ValueError, match="cannot be approved"):
        decide(run_id, decision_input(created["run"]), repo)
    asyncio.run(process_next(repo, DemoModel()))
    reopened = ExcelRepository(repo.file)
    run = run_for(reopened, run_id)
    assert run["status"] == "Pending Approval"
    assert len(json.loads(run["proposed_ids_json"])) == 3
    assert reopened.read()["assignments"] == []
    action = decision_input(run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda r: decide(run_id, action, r), [repo, reopened]))
    assert all(r["status"] == "Approved" for r in results)
    approved = reopened.read()
    assert len(approved["assignments"]) == 3
    assert len(approved["decisions"]) == 1
    assert sum(a["allocated_hours"] for a in approved["assignments"]) == 30
    assert asyncio.run(process_next(repo, DemoModel())) is False
    with ZipFile(ROOT / "data/agentic-staffing.xlsx") as original, ZipFile(repo.file) as updated:
        for i in range(2, 12):
            name = f"xl/worksheets/sheet{i}.xml"
            assert original.read(name) == updated.read(name), name


def test_adjust_decline_and_duplicate_save(repo):
    data = request_input()
    a, b = save_request(data, repo), save_request(data, repo)
    assert a["request"]["request_id"] == b["request"]["request_id"]
    asyncio.run(process_next(repo, DemoModel()))
    run = run_for(repo, a["run"]["run_id"])
    decide(run["run_id"], decision_input(run, action="adjust"), repo)
    run = run_for(repo, run["run_id"])
    assert run["status"] == "Pending Approval"
    assert not repo.read()["assignments"]
    decide(run["run_id"], decision_input(run, action="decline", selected_ids=[]), repo)
    assert run_for(repo, run["run_id"])["status"] == "Declined"
    assert not repo.read()["assignments"]


def test_approval_revalidates_capacity_and_revisions(repo):
    run = pending(repo)
    action = decision_input(run)
    with pytest.raises(ValueError, match="distinct"):
        decide(run["run_id"], {**action, "selected_ids": [action["selected_ids"][0]] * 3}, repo)
    with pytest.raises(ValueError, match="Another reviewer"):
        decide(run["run_id"], {**action, "revision": 1}, repo)
    repo.transaction(lambda db: next(p for p in db["people"] if p["person_id"] == action["selected_ids"][0]).update(allocation_pct=99))
    with pytest.raises(ValueError, match="no longer eligible"):
        decide(run["run_id"], action, repo)
    assert not repo.read()["assignments"]
    assert not repo.read()["decisions"]


def test_changed_policy_rejects_stale_approval(repo):
    run = pending(repo)
    repo.transaction(lambda db: db["policies"][0].update(version="changed"))
    with pytest.raises(ValueError, match="Master data or assignments changed"):
        decide(run["run_id"], decision_input(run), repo)
    assert not repo.read()["assignments"]


def test_recovery_failure_and_rerun(repo):
    created = save_request(request_input(), repo)
    repo.transaction(lambda db: db["runs"][0].update(status="Running", lease_until="2000-01-01T00:00:00.000Z", lease_owner="dead"))

    class Unavailable:
        provider, name = "oci", "unavailable"

        async def complete(self, system, context):
            raise ValueError("OCI configuration unavailable")

    asyncio.run(process_next(repo, Unavailable()))
    assert run_for(repo, created["run"]["run_id"])["status"] == "Failed"
    assert not repo.read()["assignments"]
    next_run = rerun(created["request"]["request_id"], repo)
    asyncio.run(process_next(repo, DemoModel()))
    assert run_for(repo, next_run["run_id"])["status"] == "Pending Approval"


def test_scoring_matches_typescript_golden_values(repo):
    db = repo.read()
    # Captured from the prior implementation against the unchanged versioned seed.
    assert data_hash(db) == "156ca4ae45d4d31ebd329e81a6dc13eba0c149c8ff6c0b3e020d322c4222e8ac"
    reqs = [{"request_id": "TEST", "skill_id": s, "min_proficiency": 3, "mandatory": True} for s in ["SK-002", "SK-003", "SK-004"]]
    scored = score_candidates(db, request_input(), reqs, "parity")
    assert [(c["person_id"], c["total_score"], c["eligible"]) for c in scored] == [
        ("P-006", 78.13, True), ("P-001", 48.8, True), ("P-005", 46.27, True), ("P-008", 41.07, True),
        ("P-003", 39.6, False), ("P-004", 35.2, True), ("P-007", 18.4, False), ("P-002", 6.4, False)]
    db["availability"].append(dict(event_id="test", person_id="P-006", event_type="Travel", starts_on="2026-10-05", ends_on="2026-10-05", title="Travel", allocated_hours=8))
    assert next(c for c in score_candidates(db, request_input(), reqs, "test") if c["person_id"] == "P-006")["eligible"] is False
    with pytest.raises(ValueError, match="working day"):
        business_days("2026-10-10", "2026-10-11")
    db["settings"][0]["value"] = 10
    with pytest.raises(ValueError, match="Weights"):
        weights(db)


def test_unfillable_and_untrusted_text(repo):
    data = request_input(title='=SUM(A1:A2) <script>alert(1)</script> \\1', skill_ids=["SK-008", "SK-005"], estimated_hours=9000)
    created = save_request(data, repo)
    asyncio.run(process_next(repo, DemoModel()))
    assert run_for(repo, created["run"]["run_id"])["status"] == "Needs Adjustment"
    db = repo.read()
    assert not db["assignments"]
    assert db["requests"][-1]["title"] == data["title"]


def test_edit_supersedes_run_without_overwriting_other_requests(repo):
    created = save_request(request_input(), repo)
    updated = save_request(request_input(title="Updated launch"), repo, created["request"]["request_id"])
    assert run_for(repo, created["run"]["run_id"])["status"] == "Superseded"
    assert len(repo.read()["requests"]) == 4
    asyncio.run(process_next(repo, DemoModel()))
    assert run_for(repo, updated["run"]["run_id"])["status"] == "Pending Approval"


def test_transaction_rollback_and_initialize_preserve_existing(repo):
    before = repo.file.read_bytes()

    def failed(db):
        db["people"].clear()
        raise ValueError("rollback")

    with pytest.raises(ValueError, match="rollback"):
        repo.transaction(failed)
    repo.initialize()
    assert repo.file.read_bytes() == before
