from typing import Protocol, TypedDict

from pydantic import Field

from app.contracts import Candidate, Contract, Proposal, RequestSnapshot, RuleIssue


class StaffingBrief(Contract):
    request_id: str
    request_revision: int = Field(ge=1)
    summary: str = Field(min_length=1, max_length=4000)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=200)
    gaps: tuple[RuleIssue, ...] = ()


class Analyst(Protocol):
    """Retrieves/understands evidence; cannot edit requirements, people, roles or assignments."""
    def analyze(self, request: RequestSnapshot) -> StaffingBrief: ...


class Planner(Protocol):
    """Uses calculation tools to propose people/hours. Cannot approve, assign, or send mail."""
    def propose(self, request: RequestSnapshot, brief: StaffingBrief, candidates: tuple[Candidate, ...]) -> Proposal: ...


class StaffingGraphState(TypedDict, total=False):
    execution_id: str
    request: RequestSnapshot
    brief: StaffingBrief
    candidate_ids: list[str]
    proposal: Proposal
    issues: list[RuleIssue]
    steps_used: int
    status: str


READ_TOOLS = (
    "get_request_snapshot", "get_catalogue_mapping", "get_rejection_feedback", "search_candidate_people",
    "get_person_evidence", "get_effective_role_capabilities", "get_availability", "get_existing_commitments",
)
CALCULATION_TOOLS = ("evaluate_eligibility", "calculate_capacity", "score_candidates", "evaluate_pod")
# This is a future interface inventory, not a fabricated operational tool registry.
# Retained phase-1 design interfaces. Operational phase-3 tools/results are in staffing.py;
# Oracle adapters and the LangGraph workflow are in evidence.py and workflow.py.
# Approval APIs, final assignment writes and notifications remain outside phase 3.
