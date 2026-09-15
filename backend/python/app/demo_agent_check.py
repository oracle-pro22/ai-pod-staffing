"""Read-only staffing calculation check against Oracle evidence; never runs an agent job."""
import argparse
import json
import re
import sys
from time import monotonic

from app.errors import ServiceError
from app.evidence import collect_evidence
from app.planning import find_options, json_text
from app.policy import SchedulingRules, StaffingPolicy

DEMO_POLICY_VERSION = "staffing-demo-v2"
PREVIEW_SOURCE_POLICY = "staffing-v1-draft"
INFORMATION_ERRORS = {"NEEDS_INFORMATION", "INVALID_EVIDENCE", "CAPACITY_UNKNOWN", "CAPACITY_STALE"}


def preview_bundle(bundle):
    """Explicitly preview new scheduling rules without publishing or approving them."""
    policy = StaffingPolicy.model_validate({**bundle.policy.model_dump(),
        "version": DEMO_POLICY_VERSION, "status": "DRAFT", "approved_by": None, "approved_at": None,
        "scheduling": SchedulingRules().model_dump()})
    return bundle.model_copy(update={"policy": policy})


def report_options(bundle, search):
    options = []
    for option in search.options:
        members = []
        for member in option.proposal.members:
            facts = option.scores[member.person_id]
            members.append({"person_id": member.person_id,
                "name": bundle.names.get(member.person_id, member.person_id), "role": member.role.value,
                "planned_hours": member.hours, "deliverable_ids": list(member.deliverable_ids),
                "responsibilities": member.responsibilities,
                "daily_schedule": facts["daily_schedule"],
                "minimum_member_hours": facts["minimum_member_hours"],
                "current_window_allocation_pct": facts["current_window_allocation_pct"],
                "projected_window_allocation_pct": facts["window_allocation_pct"],
                "window_available_hours": facts["window_available_hours"],
                "window_committed_hours": facts["window_committed_hours"],
                "projected_peak_week_start": facts["peak_week_start"],
                "current_allocation_in_peak_week_pct": facts["current_allocation_pct"],
                "projected_peak_week_allocation_pct": facts["projected_allocation_pct"],
                "peak_week_available_hours": facts["available_hours"],
                "peak_week_committed_hours": facts["committed_hours"],
                "peak_week_proposed_hours": facts["peak_week_proposed_hours"],
                "weekly_capacity": facts["weekly_capacity"], "score": facts["score"]})
        options.append({"plan_id": option.plan_id, "ranking_score": option.average_score,
                        "total_planned_hours": sum(member.hours for member in option.proposal.members),
                        "members": members})
    if options:
        status, code = "OPTIONS_AVAILABLE", None
    elif not search.exhaustive:
        status, code = "FAILED", "SEARCH_LIMIT"
    elif any(reason in ("CAPACITY_UNKNOWN", "CAPACITY_STALE") for reason in search.exclusions.values()):
        status, code = "NEEDS_INFORMATION", "CAPACITY_INFORMATION"
    else:
        status, code = "NO_FEASIBLE_POD", "NO_FEASIBLE_POD"
    return {"status": status, "code": code, "options": options,
            "search_exhaustive": search.exhaustive, "search_limit_reached": not search.exhaustive,
            "teams_examined": search.examined,
            "exclusions": [{"person_id": person_id, "name": bundle.names.get(person_id, person_id), "reason": reason}
                           for person_id, reason in sorted(search.exclusions.items())]}


def evaluate(database, settings, request_id, *, preview_policy=False, policy_version=DEMO_POLICY_VERSION):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", request_id):
        raise ServiceError("INVALID_REQUEST_ID", "Provide a valid staffing request ID.", 422)
    start = monotonic()
    source = PREVIEW_SOURCE_POLICY if preview_policy else policy_version
    with database.read() as connection:
        bundle = collect_evidence(connection, request_id, source, settings.staffing_max_candidates)
        if preview_policy:
            bundle = preview_bundle(bundle)
        try:
            search = find_options(bundle, limit=settings.staffing_search_limit)
            outcome = report_options(bundle, search)
        except ServiceError as error:
            if error.code not in INFORMATION_ERRORS:
                raise
            outcome = {"status": "NEEDS_INFORMATION", "code": error.code, "message": error.message,
                       "options": [], "search_exhaustive": False, "teams_examined": 0}
    return {"check": "deterministic-staffing-calculation", "request_id": request_id,
            "request_title": bundle.request.title, "request_revision": bundle.request.revision,
            "starts_on": bundle.request.starts_on.isoformat(), "ends_on": bundle.request.ends_on.isoformat(),
            "total_person_hours": bundle.request.total_hours,
            "policy_version": bundle.policy.version, "policy_status": bundle.policy.status,
            "policy_source": "in-memory-preview" if preview_policy else "database",
            "source_policy_version": source,
            "scheduling_algorithm": bundle.policy.scheduling.algorithm if bundle.policy.scheduling else "equal-workdays-v1",
            **outcome, "elapsed_seconds": round(monotonic() - start, 2),
            "model_calls": 0, "writes": 0, "queued_jobs": 0, "emails_sent": 0,
            "note": "Only Oracle evidence and deterministic staffing calculations were checked. "
                    "No model, agent execution, policy approval, proposal publication or assignment was performed. "
                    "Request-window and busiest-full-week percentages are separate measures."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="Python configuration file; values are never printed.")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--policy-version", default=DEMO_POLICY_VERSION,
                        help="Existing Oracle policy to evaluate; defaults to staffing-demo-v2.")
    parser.add_argument("--preview-policy", action="store_true",
                        help="Read staffing-v1-draft and preview staffing-demo-v2 rules in memory, without approval or writes.")
    args = parser.parse_args(argv)
    database = None
    try:
        from app.config import Settings
        from app.database import OracleDatabase
        settings = Settings(_env_file=args.env_file)
        database = OracleDatabase(settings)
        print("Reading Oracle evidence and checking staffing calculations (read-only)...", file=sys.stderr, flush=True)
        result = evaluate(database, settings, args.request_id, preview_policy=args.preview_policy,
                          policy_version=args.policy_version)
        print(json.dumps(json.loads(json_text(result)), indent=2, ensure_ascii=False), flush=True)
        return 0 if result["status"] == "OPTIONS_AVAILABLE" else 2
    except ServiceError as error:
        print(json.dumps({"status": "NEEDS_INFORMATION" if error.code in INFORMATION_ERRORS else "CHECK_FAILED",
                          "error": error.code, "message": error.message, "model_calls": 0, "writes": 0}), flush=True)
        return 2 if error.code in INFORMATION_ERRORS else 1
    except Exception as error:
        print(json.dumps({"status": "CHECK_FAILED", "type": type(error).__name__,
                          "message": "Check the request evidence, database connection and installed policy. No writes were attempted.",
                          "model_calls": 0, "writes": 0}), flush=True)
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
