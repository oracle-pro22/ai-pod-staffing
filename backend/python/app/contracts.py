from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

EntityId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,30}$")]
Hours = Annotated[Decimal, Field(ge=0, le=100000, decimal_places=2, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True, hide_input_in_errors=True)


class DailyHours(Contract):
    day: date
    hours: Hours


class PodRole(StrEnum):
    LEAD = "POD_LEAD"
    MEMBER = "POD_MEMBER"


class ExperienceLevel(StrEnum):
    LEARNING = "LEARNING"
    SUPPORTED = "SUPPORTED"
    INDEPENDENT = "INDEPENDENT"
    MENTOR = "MENTOR"


class Requirement(Contract):
    skill_id: EntityId
    mandatory: StrictBool = True
    assessment_type: Literal["SELF_RATED", "ROLE_DERIVED"] = "SELF_RATED"
    minimum_strength: Annotated[Decimal, Field(ge=1, le=5, allow_inf_nan=False)] | None = None
    derived_role_code: str | None = None

    @model_validator(mode="after")
    def consistent_type(self):
        if self.assessment_type == "ROLE_DERIVED" and self.minimum_strength is not None:
            raise ValueError("Role-derived capabilities cannot use a proficiency rating")
        if self.assessment_type == "SELF_RATED" and self.derived_role_code is not None:
            raise ValueError("Self-rated requirements cannot grant role capabilities")
        return self


class RequestSnapshot(Contract):
    request_id: EntityId
    revision: int = Field(ge=1, strict=True)
    responsible_captain_id: EntityId
    title: str = Field(min_length=1, max_length=500)
    starts_on: date
    ends_on: date
    total_hours: Annotated[Decimal, Field(gt=0, le=100000, decimal_places=2, allow_inf_nan=False)]
    lead_count: int = Field(default=1, ge=1, le=5, strict=True)
    member_count: int = Field(default=2, ge=0, le=20, strict=True)
    deliverable_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=100)
    requirements: tuple[Requirement, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.ends_on < self.starts_on or (self.ends_on - self.starts_on).days > 366:
            raise ValueError("Provide an ordered schedule of at most 366 days")
        if len(set(self.deliverable_ids)) != len(self.deliverable_ids):
            raise ValueError("Deliverable IDs must be unique")
        if len({row.skill_id for row in self.requirements}) != len(self.requirements):
            raise ValueError("Normalize duplicate capabilities before creating the snapshot")
        return self


class SkillEvidence(Contract):
    skill_id: EntityId
    strength: Annotated[Decimal, Field(ge=1, le=5, allow_inf_nan=False)] | None = None
    interested: StrictBool = False
    evidence: str = Field(default="", max_length=2000)


class DeliverableEvidence(Contract):
    deliverable_id: EntityId
    experience_level: ExperienceLevel
    contribution_scope: Literal["CONTRIBUTOR", "END_TO_END"]
    interested: StrictBool = False
    experience: str = Field(default="", max_length=8000)


class EffectiveRole(Contract):
    code: str = Field(min_length=1, max_length=40)
    starts_on: date
    ends_on: date | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.ends_on is not None and self.ends_on < self.starts_on:
            raise ValueError("Role dates are reversed")
        return self


class Candidate(Contract):
    person_id: EntityId
    active: StrictBool
    roles: tuple[EffectiveRole, ...] = ()
    skills: tuple[SkillEvidence, ...] = ()
    deliverables: tuple[DeliverableEvidence, ...] = ()

    @model_validator(mode="after")
    def unique_evidence(self):
        if len({item.skill_id for item in self.skills}) != len(self.skills):
            raise ValueError("Duplicate skill evidence")
        if len({item.deliverable_id for item in self.deliverables}) != len(self.deliverables):
            raise ValueError("Duplicate deliverable evidence")
        return self


class ProposedMember(Contract):
    person_id: EntityId
    role: PodRole
    hours: Annotated[Decimal, Field(gt=0, le=100000, decimal_places=2, allow_inf_nan=False)]
    responsibilities: str = Field(min_length=1, max_length=2000)
    deliverable_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=100)
    # Empty is supported only for historical equal-workday policies. New plans
    # carry the exact dates that are frozen at publication and rechecked at approval.
    daily_schedule: tuple[DailyHours, ...] = Field(default=(), max_length=380)

    @model_validator(mode="after")
    def unique_deliverables(self):
        if len(set(self.deliverable_ids)) != len(self.deliverable_ids):
            raise ValueError("Duplicate responsibility deliverable")
        if self.daily_schedule:
            if len({row.day for row in self.daily_schedule}) != len(self.daily_schedule):
                raise ValueError("Duplicate scheduled dates")
            if any(row.hours <= 0 for row in self.daily_schedule):
                raise ValueError("Proposed schedule entries must contain positive hours")
            if sum((row.hours for row in self.daily_schedule), Decimal(0)) != self.hours:
                raise ValueError("Scheduled day hours must equal the member's planned hours")
        return self


class Proposal(Contract):
    request_id: EntityId
    request_revision: int = Field(ge=1, strict=True)
    policy_version: str
    members: tuple[ProposedMember, ...] = Field(min_length=1, max_length=25)
    rationale: str = Field(min_length=1, max_length=8000)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=200)


class CaptainDecision(Contract):
    proposal_id: EntityId
    proposal_version: int = Field(ge=1, strict=True)
    action: Literal["APPROVED", "REJECTED"]
    reason: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")

    @model_validator(mode="after")
    def required_rejection_reason(self):
        if self.action == "REJECTED" and not self.reason:
            raise ValueError("A rejection reason is required")
        return self


class RuleIssue(Contract):
    code: str
    message: str
    person_id: str | None = None
    reference_id: str | None = None


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    NO_FEASIBLE_POD = "NO_FEASIBLE_POD"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class RunReceipt(Contract):
    execution_id: str
    request_id: EntityId
    request_revision: int = Field(ge=1, strict=True)
    status: RunStatus


class ProgressEvent(Contract):
    execution_id: str
    sequence: int = Field(ge=1, strict=True)
    stage: str
    status: str
    summary: str = Field(max_length=2000)
