"""Explicit live-OCI test with invented QA records; never approves a pod."""
import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from .agents.supervisor import process_next
from .config import ROOT
from .repository import ExcelRepository
from .sample_data import generate_sample
from .service import save_request
from .tools.model import OciModel


async def main(expanded=False):
    file = Path(tempfile.mkdtemp(prefix="staffing-python-live-")) / "staffing.xlsx"
    shutil.copyfile(ROOT / "data/agentic-staffing.xlsx", file)
    repo = ExcelRepository(file)

    def invent(db):
        catalog = db["skills"]
        db["people"] = [dict(person_id=f"QA-{i}", full_name=f"Fictional QA Person {i}", initials="QA", job_title="Test role", location="Test location",
                             allocation_pct=20 + i * 5, active_pods=0, can_lead=i == 1, daily_hours=8) for i in (1, 2, 3)]
        db["skills"] = [dict(skill_id="QA-SKILL", skill_name="Fictional test capability", category="QA", source="Invented for connection test")]
        db["personSkills"] = [dict(person_id=p["person_id"], skill_id="QA-SKILL", proficiency=4, evidence="Invented QA proficiency", source="Invented QA data") for p in db["people"]]
        db["preferences"] = [dict(person_id=p["person_id"], skill_id="QA-SKILL", interest_level=3, source="Invented QA preference") for p in db["people"]]
        for key in ("availability", "requests", "requirements", "runs", "candidates", "events", "decisions", "assignments", "notifications"):
            db[key] = []
        if expanded:
            # Use the 64 fictional profiles only; no original people or requests
            # are included in the OCI payload. Skills are catalog labels only.
            db.update(generate_sample())
            db["skills"] = catalog
        db["policies"] = [dict(policy_id="QA-POLICY", title="QA approval rule", guidance="Wait for human approval before making an assignment.", version="QA")]

    repo.transaction(invent)
    created = save_request(dict(title="Fictional QA request", work_type="Test work", owner_name="Fictional QA reviewer", starts_on="2026-10-05", needed_by="2026-10-16",
                                estimated_hours=30, contributor_count=2, priority="Normal", business_context="Test structured agent responses using invented QA profiles only.",
                                skill_ids=["SK-002", "SK-003", "SK-004"] if expanded else ["QA-SKILL"], submission_key=str(uuid4())), repo)
    await process_next(repo, OciModel())
    db = repo.read()
    run = next(r for r in db["runs"] if r["run_id"] == created["run"]["run_id"])
    print(json.dumps({"workbook": str(file), "status": run["status"], "provider": run["provider"], "model": run["model"], "error": run["error"],
                      "candidateCount": len(db["candidates"]), "assignmentCount": len(db["assignments"])}))
    return 0 if run["status"] == "Pending Approval" and not db["assignments"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expanded-synthetic", action="store_true", help="Test all 64 fictional profiles and the bounded model shortlist")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.expanded_synthetic)))
