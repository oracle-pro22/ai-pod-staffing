"""Server-authored staffing facts; never trust model prose as numerical evidence."""
from decimal import Decimal

from app.errors import ServiceError
from app.planning import json_text


def checked_plan_scores(bundle, option):
    """Recheck every saved score/schedule fact against this exact evidence snapshot."""
    from app.planning import score_plan_member
    expected_ids = {member.person_id for member in option.proposal.members}
    if set(option.scores) != expected_ids:
        raise ServiceError("INVALID_CHECKPOINT", "Saved plan metrics do not match its selected people.", 409)
    computed = {member.person_id: score_plan_member(bundle, member) for member in option.proposal.members}
    if json_text(computed) != json_text(option.scores):
        raise ServiceError("INVALID_CHECKPOINT", "Saved plan metrics or daily schedules changed; start a new run.", 409)
    return computed


def number(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f").rstrip("0").rstrip(".")


def grounded_plan_rationale(bundle, proposal, scores):
    """Only deterministic facts are promoted from a selected option to review prose.

    The model's qualitative selection explanation remains in its versioned execution
    checkpoint. It cannot overwrite published hours, percentages or role evidence.
    """
    request = bundle.request
    lines = [f"{number(request.total_hours)} person-hours across {len(proposal.members)} people, "
             f"scheduled from {request.starts_on.isoformat()} to {request.ends_on.isoformat()}."]
    for member in proposal.members:
        facts = scores[member.person_id]
        # Names are resolved only after selection, never provided as model ranking inputs.
        name = str(bundle.names.get(member.person_id, member.person_id))[:100]
        role = "POD Lead" if member.role == "POD_LEAD" else "POD Member"
        lines.append(f"{name} ({role}): {number(member.hours)} planned hours; "
                     f"projected busiest-week allocation {number(facts['projected_allocation_pct'])}% "
                     f"(week of {facts['peak_week_start']}); "
                     f"request-window allocation {number(facts['current_window_allocation_pct'])}% "
                     f"before and {number(facts['window_allocation_pct'])}% after this proposal.")
    lines.append("Allocation includes confirmed assignments and external work, using working capacity after leave. "
                 "The dated work schedule and total effort passed the staffing rules; pending proposals do not reserve hours.")
    return "\n".join(lines)
