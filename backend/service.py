"""Request commands and human-only approval coordinator.

This module owns the only assignment-write capability. Model workers cannot call
decide; the HTTP decision endpoint is the human review boundary.
"""
import re
from datetime import datetime, timezone
from uuid import uuid4

from .config import config
from .models import DecisionInput, RequestInput
from .repository import json_string
from .tools.scoring import business_days, data_hash, score_candidates, validate_pod, weights


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event(db, run_id, component, component_type, tool, detail, status="Done"):
    db["events"].append(dict(event_id=str(uuid4()), run_id=run_id, occurred_at=now_iso(), component=component,
                             component_type=component_type, tool=tool, status=status, detail=detail))


def notify(db, run_id, recipient, message):
    db["notifications"].append(dict(notification_id=str(uuid4()), run_id=run_id, recipient=recipient,
                                    message=message, created_at=now_iso(), delivery_status="In-app"))


def queue(db, request, feedback=""):
    c, now = config(), now_iso()
    previous = next((r for r in db["runs"] if r["run_id"] == request["latest_run_id"]), None)
    if previous and previous["status"] in {"Queued", "Running", "Pending Approval", "Needs Adjustment", "Failed"}:
        previous["status"] = "Superseded"
    run = dict(run_id=str(uuid4()), request_id=request["request_id"], status="Queued", stage="Request saved",
               created_at=now, updated_at=now, lease_until="", lease_owner="", revision=1,
               provider=c.provider, model="Deterministic demo (no model call)" if c.provider == "demo" else c.model,
               weights_json=json_string(weights(db)), proposed_ids_json="[]", summary="", error="", feedback=feedback, master_hash="")
    db["runs"].append(run)
    request.update(latest_run_id=run["run_id"], status="Recommendation running")
    event(db, run["run_id"], "Staffing supervisor", "Supervisor agent", "queue_workflow", "Request saved. Workflow queued automatically.")
    return run


def save_request(input_data, repo, existing_id=None):
    data = RequestInput.model_validate(input_data).model_dump()
    business_days(data["starts_on"], data["needed_by"])

    def save(db):
        if len(set(data["skill_ids"])) != len(data["skill_ids"]) or any(s not in {row["skill_id"] for row in db["skills"]} for s in data["skill_ids"]):
            raise ValueError("Select valid, distinct skills from the master catalog.")
        duplicate = next((r for r in db["requests"] if r["submission_key"] == data["submission_key"]), None)
        if duplicate:
            if existing_id and duplicate["request_id"] != existing_id:
                raise ValueError("Submission key belongs to a different request.")
            return {"request": duplicate, "run": next((r for r in db["runs"] if r["run_id"] == duplicate["latest_run_id"]), None)}
        request = next((r for r in db["requests"] if r["request_id"] == existing_id), None)
        if existing_id and not request:
            raise ValueError("Request not found.")
        if request and any(a["request_id"] == existing_id for a in db["assignments"]):
            raise ValueError("An approved request cannot be edited in this prototype. Create a new request.")
        sequence = [int(r["request_id"][4:]) for r in db["requests"] if re.fullmatch(r"REQ-\d+", r["request_id"])]
        request_id = existing_id or f"REQ-{max([1042] + sequence) + 1}"
        values = {k: v for k, v in data.items() if k != "skill_ids"}
        values.update(request_id=request_id, status="Recommendation running", created_at=request["created_at"] if request else now_iso(), latest_run_id=request["latest_run_id"] if request else "")
        if request:
            request.update(values)
        else:
            request = values
            db["requests"].append(request)
        db["requirements"] = [r for r in db["requirements"] if r["request_id"] != request_id]
        db["requirements"].extend(dict(request_id=request_id, skill_id=s, min_proficiency=3, mandatory=True) for s in data["skill_ids"])
        return {"request": request, "run": queue(db, request)}
    return repo.transaction(save)


def rerun(request_id, repo):
    def restart(db):
        request = next((r for r in db["requests"] if r["request_id"] == request_id), None)
        if not request:
            raise ValueError("Request not found.")
        if any(a["request_id"] == request_id for a in db["assignments"]):
            raise ValueError("This request is already approved.")
        previous = next((r for r in db["runs"] if r["run_id"] == request["latest_run_id"]), None)
        if previous and previous["status"] in {"Queued", "Running"}:
            return previous
        return queue(db, request, previous["feedback"] if previous else "")
    return repo.transaction(restart)


def decide(run_id, input_data, repo):
    data = DecisionInput.model_validate(input_data).model_dump()

    def record(db):
        duplicate = next((d for d in db["decisions"] if d["idempotency_key"] == data["idempotency_key"]), None)
        if duplicate:
            if duplicate["run_id"] != run_id:
                raise ValueError("Decision key belongs to a different run.")
            return next(r for r in db["runs"] if r["run_id"] == run_id)
        run = next((r for r in db["runs"] if r["run_id"] == run_id), None)
        request = next((r for r in db["requests"] if r["latest_run_id"] == run_id), None)
        if not run or not request:
            raise ValueError("This recommendation has been replaced. Reload the latest run.")
        if run["status"] != "Pending Approval":
            raise ValueError(f'The recommendation is {run["status"]}; it cannot be approved or changed.')
        if run["revision"] != data["revision"]:
            raise ValueError("Another reviewer updated this recommendation. Reload before deciding.")
        requirements = [r for r in db["requirements"] if r["request_id"] == request["request_id"]]
        if data["action"] != "decline":
            current = score_candidates(db, request, requirements, run_id)
            validate_pod(data["selected_ids"], current, requirements, request["contributor_count"] + 1)
            if data_hash(db) != run["master_hash"]:
                raise ValueError("Master data or assignments changed since scoring. Re-run fitment to review fresh evidence before approval.")
        now, reviewer = now_iso(), config().reviewer
        db["decisions"].append(dict(decision_id=str(uuid4()), run_id=run_id, request_id=request["request_id"],
                                    action=data["action"], reviewer=reviewer, reason=data["reason"], selected_ids_json=json_string(data["selected_ids"]),
                                    occurred_at=now, idempotency_key=data["idempotency_key"]))
        run.update(revision=run["revision"] + 1, updated_at=now, feedback=data["reason"])
        if data["action"] == "approve":
            if any(a["request_id"] == request["request_id"] for a in db["assignments"]):
                raise ValueError("Assignments already exist for this request.")
            run.update(proposed_ids_json=json_string(data["selected_ids"]), status="Approved", stage="Assignments saved")
            request["status"] = "Staffed"
            effort = request["estimated_hours"] / (request["contributor_count"] + 1)
            days = len(business_days(request["starts_on"], request["needed_by"]))
            for i, person_id in enumerate(data["selected_ids"]):
                role = "Pod lead" if i == 0 else "Contributor"
                db["assignments"].append(dict(assignment_id=str(uuid4()), request_id=request["request_id"], run_id=run_id,
                                              person_id=person_id, role_in_pod=role, starts_on=request["starts_on"], ends_on=request["needed_by"],
                                              allocated_hours=effort, per_day_hours=effort / days, approved_by=reviewer, approved_at=now))
                name = next(p["full_name"] for p in db["people"] if p["person_id"] == person_id)
                notify(db, run_id, name, f'{request["request_id"]}: your {role} assignment was approved.')
            event(db, run_id, "Approval coordinator", "Worker agent", "write_assignments", f'{len(data["selected_ids"])} approved assignments saved atomically with the human decision.')
        elif data["action"] == "decline":
            run.update(status="Declined", stage="Declined by reviewer")
            request["status"] = "Declined"
        else:
            run.update(proposed_ids_json=json_string(data["selected_ids"]), stage="Adjusted; awaiting approval")
            request["status"] = "Pending Approval"
        notify(db, run_id, request["owner_name"], f'{request["request_id"]}: {data["action"]} decision recorded by {reviewer}.')
        event(db, run_id, "Approval coordinator", "Worker agent", "persist_decision", f'{reviewer}: {data["action"]}. {data["reason"]}')
        event(db, run_id, "Staffing supervisor", "Supervisor agent", "record_outcome", "Adjusted proposal saved. Still waiting for human approval." if data["action"] == "adjust" else "Outcome retained for future evaluation. No automatic model retraining.")
        return run
    return repo.transaction(record)
