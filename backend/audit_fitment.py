"""Read-only capacity/coverage audit. No model calls, recommendations or approvals are persisted."""
import argparse
import copy
import json
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

from .excel_file import ExcelFile
from .repository import ExcelRepository
from .sample_data import AS_OF, append_sample, working_start
from .tools.scoring import fitment_gap, recommend_shortlisted_pod, score_candidates


def rows(file, name):
    sheet = ExcelFile(file).read_rows(name)
    return [dict(zip(sheet[0], r)) for r in sheet[1:] if r]


def scenarios(file):
    mappings = rows(file, "Deliverable Skills")
    result = []
    for deliverable in rows(file, "Deliverables"):
        required = [r["skill_id"] for r in mappings if r["deliverable_id"] == deliverable["deliverable_id"]]
        for label, offset, span, hours, size in [("Standard", 3, 11, 72, 3), ("Short sprint", 31, 4, 40, 2), ("Extended", 94, 18, 120, 4)]:
            start = working_start(AS_OF + timedelta(days=offset))
            result.append(dict(request_id=deliverable["deliverable_id"] + "-" + label, title=deliverable["deliverable_name"], scenario=label,
                               starts_on=start.isoformat(), needed_by=(start + timedelta(days=span)).isoformat(), estimated_hours=hours,
                               contributor_count=size - 1, skills=required))
    return result


def assess(db, request, required):
    requirements = [dict(request_id=request["request_id"], skill_id=s, min_proficiency=3, mandatory=True) for s in required]
    candidates = score_candidates(db, request, requirements, "audit-only")
    proposed = recommend_shortlisted_pod(candidates, requirements, request["contributor_count"] + 1)
    return dict(request_id=request["request_id"], title=request["title"], scenario=request.get("scenario", "Saved request"),
                feasible=bool(proposed), eligible=sum(c["eligible"] for c in candidates), selected=proposed,
                gap=None if proposed else fitment_gap(candidates, requirements, request["contributor_count"] + 1, shortlisted=True))


def audit(db, cases):
    started = time.perf_counter()
    results = [assess(db, r, r["skills"]) for r in cases]
    coverage = [dict(skill_id=s["skill_id"], name=s["skill_name"], qualified=sum(p["skill_id"] == s["skill_id"] and p["proficiency"] >= 3 for p in db["personSkills"])) for s in db["skills"]]
    saved = [assess(db, r, [q["skill_id"] for q in db["requirements"] if q["request_id"] == r["request_id"]]) for r in db["requests"] if not any(a["request_id"] == r["request_id"] for a in db["assignments"])]
    return {"counts": {k: len(v) for k, v in db.items()}, "qualified_by_skill": coverage, "cases": len(results), "feasible": sum(r["feasible"] for r in results),
            "feasible_by_scenario": dict(Counter(r["scenario"] for r in results if r["feasible"])), "seconds": round(time.perf_counter() - started, 3),
            "saved_unstaffed_requests": saved, "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--compare-synthetic", action="store_true")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    repo = ExcelRepository(args.workbook)
    db = repo.read()
    cases = scenarios(repo.file)
    result = {"before" if args.compare_synthetic else "current": audit(db, cases)}
    if args.compare_synthetic:
        result["after"] = audit(append_sample(copy.deepcopy(db)), cases)
    if args.output_json:
        args.output_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({name: {key: value for key, value in report.items() if key not in {"results", "qualified_by_skill"}} for name, report in result.items()}, indent=2))
