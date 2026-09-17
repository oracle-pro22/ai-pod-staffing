"""Durable, constrained supervisor. Only Queued/expired Running work is claimed.

Pending Approval is a persisted pause, not a long-lived HTTP/model connection.
The supervisor never creates assignments and has no approval tool.
"""
import asyncio
import copy
import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from ..repository import json_string
from ..console import log_failure, run_context
from ..service import event, notify, now_iso
from ..tools.model import get_model
from ..tools.scoring import data_hash
from .workers import evaluate_fitment, explain_recommendation, interpret_request

logger = logging.getLogger(__name__)


async def process_next(repo, model=None):
    model = model or get_model()
    token = str(uuid4())

    def claim(db):
        now = now_iso()
        run = next((r for r in db["runs"] if r["status"] == "Queued" or (r["status"] == "Running" and r["lease_until"] < now)), None)
        if not run:
            return None
        lease = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        run.update(status="Running", lease_owner=token, lease_until=lease, updated_at=now, stage="Validate and interpret request", provider=model.provider, model=model.name)
        event(db, run["run_id"], "Staffing supervisor", "Supervisor agent", "delegate_request_analyst", "Delegated request interpretation.")
        return copy.deepcopy(run)

    claimed = await asyncio.to_thread(repo.transaction, claim)
    if not claimed:
        return False
    context_token = run_context.set(claimed["run_id"])
    started = time.monotonic()
    logger.info("Supervisor claimed workflow: request=%r provider=%s", claimed["request_id"], model.provider)

    def active(db):
        return next((r for r in db["runs"] if r["run_id"] == claimed["run_id"] and r["lease_owner"] == token and r["status"] == "Running"), None)

    try:
        db = await asyncio.to_thread(repo.read)
        request = next(r for r in db["requests"] if r["request_id"] == claimed["request_id"])
        logger.info("Worker=Request analyst | validate request and extract required capabilities")
        summary = await interpret_request(db, request, model)

        def interpreted(db):
            run = active(db)
            if run:
                run["stage"] = "Check eligibility and score candidates"
                event(db, run["run_id"], "Request analyst", "Worker agent", "validate_request / read_skill_catalog", summary)
        await asyncio.to_thread(repo.transaction, interpreted)
        snapshot = await asyncio.to_thread(repo.read)
        if not active(snapshot):
            logger.info("Workflow no longer active; stopping this execution.")
            return True
        logger.info("Worker=Fitment analyst | tools=read_master_data, check_eligibility, score_candidates, select_pod")
        result = await asyncio.to_thread(evaluate_fitment, snapshot, request, claimed["run_id"])

        def scored(db):
            run = active(db)
            if not run:
                return False
            run["stage"] = "Generate rationale and alternates"
            eligible = sum(c["eligible"] for c in result["candidates"])
            event(db, run["run_id"], "Fitment analyst", "Worker agent", "read_master_data / check_eligibility", f'{eligible} of {len(result["candidates"])} candidates eligible. Leave, travel, skills and daily allocation checked.')
            w = result["weights"]
            detail = f'Skills {w["skills"]:g}%, allocation {w["allocation"]:g}%, future availability {w["future"]:g}%, interests {w["interests"]:g}%. '
            event(db, run["run_id"], "Fitment analyst", "Worker agent", "score_candidates / select_pod", detail + ("Top 3 eligible lead scores and top 5 eligible contributor scores shortlisted. Skill-complete pod selected within those pools." if result["proposed"] else "Top 3 eligible lead scores and top 5 eligible contributor scores shortlisted. No complete pod within those pools."))
            db["candidates"] = [c for c in db["candidates"] if c["run_id"] != run["run_id"]] + result["candidates"]
            return True
        if not await asyncio.to_thread(repo.transaction, scored):
            logger.info("Workflow no longer active; discarding scoring results.")
            return True
        logger.info("Scoring saved: candidates=%s eligible=%s proposed_members=%s", len(result["candidates"]), sum(c["eligible"] for c in result["candidates"]), len(result["proposed"]))
        w = result["weights"]
        logger.debug("Scoring weights: skills=%g allocation=%g future=%g interests=%g", w["skills"], w["allocation"], w["future"], w["interests"])
        if not result["proposed"]:
            logger.warning("No feasible pod; inspect eligibility and skill-coverage evidence in AI Fitment.")
        logger.info("Worker=Recommendation writer | retrieve policies=%s and generate rationale/alternates", len(snapshot["policies"]))
        explanation = await explain_recommendation(snapshot, request, result["candidates"], result["proposed"], model)

        def finish(db):
            run = active(db)
            if not run:
                return
            proposed = result["proposed"]
            run.update(master_hash=data_hash(snapshot), weights_json=json_string(result["weights"]), summary=explanation["summary"],
                       proposed_ids_json=json_string(proposed), status="Pending Approval" if proposed else "Needs Adjustment",
                       stage="Waiting for human decision" if proposed else "No feasible pod", updated_at=now_iso(), lease_owner="", lease_until="", revision=run["revision"] + 1)
            rationale_index = {r["person_id"]: r["text"] for r in explanation["rationales"]}
            for c in db["candidates"]:
                if c["run_id"] == run["run_id"]:
                    c["rationale"] = rationale_index[c["person_id"]]
                    c["recommended_role"] = "Pod lead" if proposed and proposed[0] == c["person_id"] else "Contributor" if c["person_id"] in proposed else "Alternate"
            next(r for r in db["requests"] if r["request_id"] == request["request_id"])["status"] = run["status"]
            detail = "Explicit demo rationale generated." if model.provider == "demo" else "OCI GenAI rationale generated."
            event(db, run["run_id"], "Recommendation writer", "Worker agent", "retrieve_staffing_policies / generate_rationale", f'{len(snapshot["policies"])} policy records retrieved. {detail}')
            event(db, run["run_id"], "Staffing supervisor", "Supervisor agent", "save_recommendation", f'{run["status"]}. Proposed recommendations persisted; no assignments created.')
            notify(db, run["run_id"], request["owner_name"], f'{request["request_id"]}: {run["status"]}. Open AI Fitment to review.')
            event(db, run["run_id"], "Staffing supervisor", "Supervisor agent", "notify_request_lead", f'In-app notification saved for {request["owner_name"]}. Workflow suspended until a human decision.')
            return run["status"]
        status = await asyncio.to_thread(repo.transaction, finish)
        if status:
            logger.info("Recommendation saved: status=%s; Request Lead notification saved; assignments_created=0; elapsed_s=%.2f", status, time.monotonic() - started)
            logger.info("Supervisor paused: waiting for human %s.", "approval / adjustment / decline" if status == "Pending Approval" else "request or master-data adjustment")
        else:
            logger.info("Workflow no longer active; discarding generated explanation.")
    except Exception as error:
        # Known tool errors are actionable; unexpected errors must not leak paths.
        message = str(error) if isinstance(error, ValueError) else "Workflow failed unexpectedly. Check the backend logs and retry."
        log_failure(logger, "Workflow failed; check the saved error in AI Fitment. No assignments created.", error)

        def fail(db):
            run = active(db)
            if not run:
                return
            run.update(status="Failed", error=message, stage="Action required", updated_at=now_iso(), lease_owner="", lease_until="", revision=run["revision"] + 1)
            next(r for r in db["requests"] if r["request_id"] == run["request_id"])["status"] = "Recommendation failed"
            event(db, run["run_id"], "Staffing supervisor", "Supervisor agent", "handle_failure", message, "Failed")
        await asyncio.to_thread(repo.transaction, fail)
    finally:
        run_context.reset(context_token)
    return True


async def supervisor_loop(repo, stop: asyncio.Event, model=None, interval=2):
    logger.info("Staffing supervisor ready. Pending approvals remain suspended.")
    while not stop.is_set():
        try:
            await process_next(repo, model)
        except Exception as error:
            log_failure(logger, "Supervisor polling failed; will retry on the next poll.", error)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    logger.info("Staffing supervisor stopped. Pending approvals remain persisted.")
