import asyncio
import copy
import itertools
import json
import random

from backend.agents.supervisor import process_next
from backend.agents.workers import explain_recommendation, rationale_shortlist
from backend.audit_fitment import audit, scenarios
from backend.sample_data import append_sample, generate_sample
from backend.service import save_request
from backend.tests.test_workflow import repo, request_input, run_for
from backend.tools.model import DemoModel
from backend.tools.scoring import (recommendation_shortlists, recommend_pod, recommend_shortlisted_pod,
                                   score_candidates, validate_pod)


def test_synthetic_integrity_and_append_only(repo):
    db = repo.read()
    original = copy.deepcopy(db)
    added = generate_sample()
    append_sample(db, added)
    once = copy.deepcopy(db)
    append_sample(db, added)
    assert db == once
    assert len(db["people"]) == 72
    assert len({p["person_id"] for p in db["people"]}) == 72
    assert db["people"][:8] == original["people"]
    person_ids = {p["person_id"] for p in db["people"]}
    skills = {s["skill_id"] for s in db["skills"]}
    for table in ("personSkills", "preferences"):
        assert len({(r["person_id"], r["skill_id"]) for r in db[table]}) == len(db[table])
        assert all(r["person_id"] in person_ids and r["skill_id"] in skills for r in db[table])
    assert all(a["person_id"] in person_ids and a["starts_on"] <= a["ends_on"] for a in db["availability"])
    assert len({a["event_id"] for a in db["availability"]}) == len(db["availability"])
    assert all(sum(s["skill_id"] == skill and s["proficiency"] >= 3 for s in db["personSkills"]) >= 9 for skill in skills)
    for key in set(db) - set(added):
        assert db[key] == original[key]
    # Independent learning interests are present without a proficiency record.
    proficiency_keys = {(s["person_id"], s["skill_id"]) for s in db["personSkills"]}
    assert any((p["person_id"], p["skill_id"]) not in proficiency_keys for p in added["preferences"])


def test_deliverable_catalog_coverage_without_relaxing_guardrails(repo):
    db = append_sample(repo.read())
    report = audit(db, scenarios(repo.file))
    assert report["cases"] == 165
    assert report["feasible_by_scenario"] == {"Standard": 53, "Short sprint": 52, "Extended": 53}
    assert report["feasible"] == 158  # Role shortlist limits intentionally exclude lower-ranked specialists.
    request = request_input(estimated_hours=10000, starts_on="2026-10-05", needed_by="2026-10-06")
    reqs = [{"skill_id": "SK-002", "mandatory": True, "min_proficiency": 3}]
    candidates = score_candidates(db, request, reqs, "stress")
    assert not recommend_pod(candidates, reqs, 3)


def test_optimizer_exceeds_40_and_keeps_low_rank_rare_skills():
    reqs = [{"skill_id": "common", "mandatory": True, "min_proficiency": 3}, {"skill_id": "rare", "mandatory": True, "min_proficiency": 3}]
    candidates = [dict(person_id=f"C-{i:03d}", eligible=True, can_lead=i % 2 == 0, total_score=100 - i,
                       evidence_json=json.dumps([{"skill_id": "rare" if i == 59 else "common", "proficiency": 4}])) for i in range(60)]
    pod = recommend_pod(candidates, reqs, 3)
    assert pod == ["C-000", "C-001", "C-059"]
    validate_pod(pod, candidates, reqs, 3)


def test_role_shortlists_and_pod_selection_obey_3_and_5_limits():
    reqs = [{"skill_id": "common", "mandatory": True, "min_proficiency": 3},
            {"skill_id": "rare", "mandatory": True, "min_proficiency": 3}]
    candidates = [dict(person_id=f"C-{i}", rank=i + 1, eligible=i != 2, can_lead=i in {0, 1, 3, 4}, total_score=100 - i,
                       evidence_json=json.dumps([{"skill_id": "rare" if i == 5 else "common", "proficiency": 4}])) for i in range(8)]
    pools = recommendation_shortlists(candidates)
    assert [c["person_id"] for c in pools["leads"]] == ["C-0", "C-1", "C-3"]
    assert [c["person_id"] for c in pools["contributors"]] == ["C-0", "C-1", "C-3", "C-4", "C-5"]
    assert recommend_shortlisted_pod(candidates, reqs, 3) == ["C-0", "C-1", "C-5"]
    candidates[5]["eligible"] = False
    candidates[7]["evidence_json"] = json.dumps([{"skill_id": "rare", "proficiency": 4}])
    assert recommend_pod(candidates, reqs, 3)  # The unrestricted evidence pool can form a pod.
    assert not recommend_shortlisted_pod(candidates, reqs, 3)  # Rank 7 is outside the top-five contributor pool.


def test_optimizer_matches_exhaustive_reference():
    rng = random.Random(124)
    reqs = [{"skill_id": str(i), "mandatory": True, "min_proficiency": 3} for i in range(4)]
    for _ in range(30):
        candidates = [dict(person_id=str(i), eligible=rng.random() > .1, can_lead=rng.random() > .55, total_score=rng.randint(10, 90),
                           evidence_json=json.dumps([{"skill_id": str(s), "proficiency": rng.randint(0, 5)} for s in range(4)])) for i in range(11)]
        candidates.sort(key=lambda c: (-c["total_score"], c["person_id"]))
        count, best = rng.choice([2, 3, 4]), None
        for combination in itertools.combinations([c for c in candidates if c["eligible"]], count):
            lead = next((c for c in combination if c["can_lead"]), None)
            if not lead:
                continue
            ids = [lead["person_id"]] + [c["person_id"] for c in combination if c is not lead]
            try:
                validate_pod(ids, candidates, reqs, count)
            except ValueError:
                continue
            score = sum(c["total_score"] for c in combination)
            if best is None or score > best[0]:
                best = score, ids
        assert recommend_pod(candidates, reqs, count) == (best[1] if best else [])


def test_large_workflow_pauses_and_model_shortlist_is_complete(repo):
    repo.transaction(append_sample)
    created = save_request(request_input(), repo)
    asyncio.run(process_next(repo, DemoModel()))
    db = repo.read()
    run = run_for(repo, created["run"]["run_id"])
    assert run["status"] == "Pending Approval", run["error"]
    assert len(db["candidates"]) == 72
    assert not db["assignments"]
    assert not db["decisions"]
    proposed = json.loads(run["proposed_ids_json"])
    shortlist = rationale_shortlist(db["candidates"], proposed)
    assert len(shortlist) <= 8
    pools = recommendation_shortlists(db["candidates"])
    assert set(c["person_id"] for c in shortlist) == set(c["person_id"] for c in pools["leads"] + pools["contributors"])
    assert set(proposed) <= {c["person_id"] for c in shortlist}

    class StructuredModel:
        provider, name = "oci", "mock-structured"

        async def complete(self, system, context):
            assert context["scored_pool_size"] == 72
            assert len(context["candidates"]) == len(shortlist)
            assert context["recommendation_limits"] == {"pod_leads": 3, "contributors": 5}
            return json.dumps({"summary": "Model explanation of the supplied proposed pod.", "rationales": [{"person_id": c["person_id"], "text": "Model shortlist rationale."} for c in context["candidates"]]})

    result = asyncio.run(explain_recommendation(db, created["request"], db["candidates"], proposed, StructuredModel()))
    assert len(result["rationales"]) == 72
    assert sum(r["text"].startswith("Scoring-tool evidence:") for r in result["rationales"]) == 72 - len(shortlist)
