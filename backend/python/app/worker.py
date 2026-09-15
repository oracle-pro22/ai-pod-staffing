"""Separate worker process; never started by FastAPI or Next.js implicitly."""
import argparse
import logging
import os
import signal
from threading import Event
from uuid import uuid4

# Employee evidence must not be exported by ambient tracing configuration.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from app.errors import ServiceError
from app.agents.staffing import AGENT_OUTPUT_MESSAGES
from app.execution_store import ExecutionStore, LeaseLost
from app.workflow import StaffingWorkflow

log = logging.getLogger("staffing.worker")


def process_job(store, job, model_factory):
    try:
        return StaffingWorkflow(store, job, model_factory).run()
    except LeaseLost:
        return {"outcome": "LEASE_LOST"}
    except ServiceError as error:
        if error.code in ("AGENTS_DISABLED", "DATABASE_UNAVAILABLE"):
            # Leave durable state for lease recovery. Do not guess whether an uncertain commit succeeded.
            raise
        if error.code == "STALE_INPUTS":
            status = "SUPERSEDED"
        elif error.code in ("NEEDS_INFORMATION", "INVALID_EVIDENCE", "CAPACITY_UNKNOWN", "CAPACITY_STALE"):
            status = "NEEDS_INFORMATION"
        else:
            status = "FAILED"
        try:
            summary = error.message if status in ("NEEDS_INFORMATION", "SUPERSEDED") else "Execution stopped; review its error code and request evidence before retrying."
            if error.code == "INVALID_AGENT_OUTPUT" and error.message in AGENT_OUTPUT_MESSAGES:
                # Only our fixed diagnostics; never persist raw model output or arguments.
                summary = error.message
            store.finish(job, status, error.code, summary)
        except LeaseLost:
            return {"outcome": "LEASE_LOST"}
        return {"outcome": status}
    except Exception as error:
        # Only operational metadata is logged, never provider payloads or employee text.
        log.error("Execution error: execution_id=%s type=%s", job.execution_id, type(error).__name__)
        transient = isinstance(error, (TimeoutError, ConnectionError)) or getattr(error, "status", None) in (429, 500, 502, 503, 504)
        try:
            if transient:
                store.retry(job)
            else:
                store.finish(job, "FAILED", "EXECUTION_ERROR", "Execution failed; check the worker dependency/configuration and correlated logs.")
        except LeaseLost:
            return {"outcome": "LEASE_LOST"}
        return {"outcome": "RETRY_SCHEDULED" if transient else "FAILED"}


def main():
    from app.config import Settings
    from app.database import OracleDatabase
    from app.agents.oci_model import build_model
    parser = argparse.ArgumentParser(description="Run the phase-3 staffing worker")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--once", action="store_true", help="Discover eligible requests and process at most one queued job")
    args = parser.parse_args()
    settings = Settings(_env_file=args.env_file)
    if not settings.staffing_worker_enabled:
        parser.error("STAFFING_WORKER_ENABLED is false; review docs/backend-phase3.md before enabling it.")
    logging.basicConfig(level=logging.WARNING)
    database = OracleDatabase(settings)
    store = ExecutionStore(database, settings)
    stopped = Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    owner = "worker-" + uuid4().hex
    try:
        while not stopped.is_set():
            try:
                store.discover()
                job = store.claim(owner)
                if job:
                    result = process_job(store, job, lambda: build_model(settings))
                    print(f"{job.execution_id}: {result['outcome']}", flush=True)
                elif args.once:
                    print("No eligible job is currently available.", flush=True)
            except ServiceError as error:
                log.error("Worker operation stopped: code=%s", error.code)
                if args.once or error.code == "AGENTS_DISABLED":
                    raise SystemExit(1) from None
            if args.once:
                break
            stopped.wait(settings.staffing_poll_seconds)
    finally:
        database.close()


if __name__ == "__main__":
    main()
