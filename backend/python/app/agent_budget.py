"""Shared hard limits for the two tool-calling stages of a staffing execution."""
from app.errors import ServiceError

MAX_MODEL_CALLS = 12
MAX_ANALYST_MODEL_CALLS = 6
MIN_PLANNER_MODEL_CALLS = 2
MIN_EXECUTION_MODEL_CALLS = 6
MAX_TOOL_CALLS = 40
COUNTERS = ("model_calls", "tool_calls", "analyst_model_calls", "planner_model_calls")


def model_call_limits(maximum_agent_steps: int) -> tuple[int, int]:
    """Return total/analyst limits without increasing the configured total cap."""
    if type(maximum_agent_steps) is not int or maximum_agent_steps < MIN_EXECUTION_MODEL_CALLS:
        raise ServiceError("AGENT_BUDGET_CONFIGURATION",
                           "The two-stage workflow requires a model-call budget of at least six.", 409)
    total = min(maximum_agent_steps, MAX_MODEL_CALLS)
    return total, min(MAX_ANALYST_MODEL_CALLS, total - MIN_PLANNER_MODEL_CALLS)


def budget_counters(checkpoint: dict) -> dict[str, int]:
    """Reject legacy, malformed or inconsistent counters; never infer stage usage."""
    if not isinstance(checkpoint, dict):
        raise ValueError("Invalid budget checkpoint")
    if any(type(checkpoint.get(key)) is not int or checkpoint[key] < 0 for key in COUNTERS):
        raise ValueError("Invalid budget counters")
    result = {key: checkpoint[key] for key in COUNTERS}
    if (result["model_calls"] != result["analyst_model_calls"] + result["planner_model_calls"]
        or result["model_calls"] > MAX_MODEL_CALLS
        or result["analyst_model_calls"] > MAX_ANALYST_MODEL_CALLS
        or result["tool_calls"] > MAX_TOOL_CALLS):
        raise ValueError("Inconsistent budget counters")
    return result


def model_call_limit(maximum_steps: int, stage: str) -> int:
    total, analyst = model_call_limits(maximum_steps)
    if stage not in ("analyst", "planner"):
        raise ServiceError("INVALID_AGENT_BUDGET", "Unknown agent stage.", 409)
    return analyst if stage == "analyst" else total


def remaining_model_calls(checkpoint: dict, maximum_steps: int, stage: str) -> int:
    """Stage loop bound; the database reservation remains the authoritative gate."""
    stage_limit = model_call_limit(maximum_steps, stage)
    total_limit, analyst_limit = model_call_limits(maximum_steps)
    counters = budget_counters(checkpoint)
    if counters["model_calls"] > total_limit or counters["analyst_model_calls"] > analyst_limit:
        raise ValueError("Budget counters exceed the execution policy")
    remaining = total_limit - counters["model_calls"]
    return min(remaining, stage_limit - counters["analyst_model_calls"]) if stage == "analyst" else remaining


def reserve_call(checkpoint: dict, stage: str, counter: str, maximum_agent_steps: int) -> dict[str, int]:
    """Compute one reservation; callers persist it before invoking a model/tool.

    Planner calls may consume unused analyst capacity. Analyst calls can never
    consume the final two calls reserved for planning, even across worker retries.
    The input is never mutated, including when a reservation is rejected.
    """
    total_limit, analyst_limit = model_call_limits(maximum_agent_steps)
    result = budget_counters(checkpoint)
    if stage not in ("analyst", "planner") or counter not in ("model_calls", "tool_calls"):
        raise ServiceError("INVALID_AGENT_BUDGET", "Unknown agent stage or reservation type.", 409)
    if result["model_calls"] > total_limit or result["analyst_model_calls"] > analyst_limit:
        raise ValueError("Budget counters exceed the execution policy")
    if counter == "model_calls":
        if result["model_calls"] >= total_limit or (
            stage == "analyst" and result["analyst_model_calls"] >= analyst_limit
        ):
            raise ServiceError("AGENT_BUDGET_EXCEEDED",
                               "Execution exhausted its persisted model or stage budget.", 409)
        result["model_calls"] += 1
        result[f"{stage}_model_calls"] += 1
    else:
        if result["tool_calls"] >= MAX_TOOL_CALLS:
            raise ServiceError("AGENT_BUDGET_EXCEEDED", "Execution exhausted its persisted tool budget.", 409)
        result["tool_calls"] += 1
    return result
