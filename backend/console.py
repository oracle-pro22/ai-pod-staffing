"""Console diagnostics without prompts, credentials, or personnel records."""
import logging
import os
import sys
import traceback
from contextvars import ContextVar
from pathlib import Path

run_context = ContextVar("staffing_log_run", default="-")


class RunContextFilter(logging.Filter):
    def filter(self, record):
        record.run_id = run_context.get()
        return True


def configure_logging():
    # Configure only our namespace. DEBUG must not enable OCI/HTTP wire logging.
    level = os.getenv("APP_LOG_LEVEL", "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("APP_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL.")
    logger = logging.getLogger("backend")
    logger.setLevel(level)
    handler = next((h for h in logger.handlers if h.get_name() == "staffing-console"), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler.set_name("staffing-console")
        handler.addFilter(RunContextFilter())
        logger.addHandler(handler)
    handler.stream = sys.stderr
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] [run=%(run_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S%z",
    ))
    return level


def log_failure(logger, message, error):
    # Exception messages/locals/source lines can contain model or request data.
    logger.error("%s error_type=%s", message, type(error).__name__)
    if logger.isEnabledFor(logging.DEBUG):
        frames = " -> ".join(f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in traceback.extract_tb(error.__traceback__))
        logger.debug("Failure locations (payloads omitted): %s", frames)
