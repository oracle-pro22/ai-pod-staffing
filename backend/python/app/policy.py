from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.contracts import Contract
from app.errors import ServiceError


class Weights(Contract):
    skill: int = Field(default=50, ge=0, le=100)
    deliverable: int = Field(default=30, ge=0, le=100)
    capacity: int = Field(default=15, ge=0, le=100)
    interest: int = Field(default=5, ge=0, le=100)

    @model_validator(mode="after")
    def total_is_100(self):
        if sum((self.skill, self.deliverable, self.capacity, self.interest)) != 100:
            raise ValueError("Scoring weights must total 100")
        return self


class SchedulingRules(Contract):
    """Versioned effort/schedule rules; absent means the frozen legacy policy."""

    algorithm: Literal["available-days-v2"] = "available-days-v2"
    minimum_member_hours: Decimal = Field(default=Decimal("1"), gt=0, le=100000,
                                          decimal_places=2, allow_inf_nan=False)
    minimum_equal_share_pct: Decimal = Field(default=Decimal("50"), gt=0, le=100,
                                             decimal_places=2, allow_inf_nan=False)


class StaffingPolicy(Contract):
    version: str = "staffing-v1-draft"
    status: Literal["DRAFT", "APPROVED"] = "DRAFT"
    approved_by: str | None = None
    approved_at: str | None = None
    default_weekly_hours: Decimal = Field(default=Decimal("40"), gt=0, le=80, allow_inf_nan=False)
    scheduling_timezone: str = "Asia/Kolkata"
    minimum_strength: Decimal = Field(default=Decimal("3"), ge=1, le=5, allow_inf_nan=False)
    maximum_allocation_pct: Decimal = Field(default=Decimal("100"), gt=0, le=100, allow_inf_nan=False)
    weights: Weights = Field(default_factory=Weights)
    lead_role_code: str = "POD_LEAD"
    member_role_codes: tuple[str, ...] = ("POD_MEMBER", "POD_LEAD")
    maximum_agent_steps: int = Field(default=12, ge=1, le=30)
    scheduling: SchedulingRules | None = None

    @model_validator(mode="after")
    def approval_metadata(self):
        if self.status == "APPROVED" and (not self.approved_by or not self.approved_at):
            raise ValueError("Approved policy must identify its business approval")
        return self

    def require_published(self):
        if self.status != "APPROVED":
            raise ServiceError("POLICY_NOT_APPROVED", "Staffing rules require business approval before live assignment.", 409)


DEFAULT_POLICY = StaffingPolicy()
