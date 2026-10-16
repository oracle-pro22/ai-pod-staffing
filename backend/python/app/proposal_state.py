"""Fence agent recommendations against a later run, under the request lock."""
from app.errors import ServiceError
from app.storage import rows


def current_agent_result(connection, proposal):
    latest = rows(connection, """SELECT execution_id,status FROM agent_executions
        WHERE request_id=:requestId ORDER BY created_at DESC,execution_id DESC FETCH FIRST 1 ROW ONLY""",
        requestId=proposal["request_id"])
    return bool(latest and latest[0]["execution_id"] == proposal["execution_id"]
                and latest[0]["status"] == "READY_FOR_REVIEW")


def require_current_agent_result(connection, proposal):
    if not current_agent_result(connection, proposal):
        raise ServiceError("STALE_PROPOSAL",
            "A newer staffing run replaced this recommendation. Review the latest execution and run fitment again.", 409)
