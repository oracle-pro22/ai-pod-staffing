"""Operational algorithm versions shared by queued work, tools and publication.

Changing scheduling, ranking or completion contracts requires a new engine/prompt
version. Old queued/checkpointed searches must be rerun, not reinterpreted silently.
"""
from app.agent_budget import budget_counters

PROMPT_VERSION = "staffing-tools-v6-explicit-roles"
ENGINE_VERSION = "staffing-engine-v5"
CHECKPOINT_FORMAT_VERSION = 5
VALIDATOR_VERSION = "staffing-validator-v3"


def new_checkpoint() -> dict:
    return {"format_version": CHECKPOINT_FORMAT_VERSION, "engine_version": ENGINE_VERSION,
            "model_calls": 0, "tool_calls": 0, "analyst_model_calls": 0, "planner_model_calls": 0,
            "supervisor_model_calls": 0}


def validate_checkpoint_state(checkpoint):
    if (not isinstance(checkpoint, dict)
        or type(checkpoint.get("format_version")) is not int
        or checkpoint["format_version"] != CHECKPOINT_FORMAT_VERSION
        or checkpoint.get("engine_version") != ENGINE_VERSION):
        raise ValueError("Checkpoint engine version is incompatible")
    budget_counters(checkpoint)


def validate_execution_checkpoint(checkpoint, prompt_version, model_id, configured_model_id):
    validate_checkpoint_state(checkpoint)
    if prompt_version != PROMPT_VERSION or model_id != configured_model_id:
        raise ValueError("Execution configuration changed")
