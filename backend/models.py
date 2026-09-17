"""HTTP contracts; field names intentionally match the existing Next.js UI."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt

Database = dict[str, list[dict[str, Any]]]


class RequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    work_type: str = Field(min_length=1, max_length=200)
    owner_name: str = Field(min_length=1, max_length=200)
    starts_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    needed_by: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    estimated_hours: StrictInt | StrictFloat = Field(gt=0, le=10000, allow_inf_nan=False)
    contributor_count: StrictInt = Field(ge=1, le=3)
    priority: Literal["Normal", "High", "Urgent"]
    business_context: str = Field(min_length=1, max_length=5000)
    skill_ids: list[str] = Field(min_length=1, max_length=30)
    project_type_id: str = Field(default="", max_length=200)
    deliverable_id: str = Field(default="", max_length=200)
    submission_key: str = Field(min_length=1, max_length=200)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["approve", "adjust", "decline"]
    reason: str = Field(min_length=1, max_length=2000)
    selected_ids: list[str] = Field(max_length=4)
    revision: StrictInt = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=200)


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skills_weight: StrictInt | StrictFloat = Field(allow_inf_nan=False)
    allocation_weight: StrictInt | StrictFloat = Field(allow_inf_nan=False)
    future_weight: StrictInt | StrictFloat = Field(allow_inf_nan=False)
    interests_weight: StrictInt | StrictFloat = Field(allow_inf_nan=False)
    max_allocation_pct: StrictInt | StrictFloat = Field(allow_inf_nan=False)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)
    request_id: str | None = None
