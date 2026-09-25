from decimal import ROUND_CEILING, Decimal

from app.capacity import CapacityLedger, calculate_capacity, spread_hours
from app.contracts import Candidate, ExperienceLevel, PodRole, Proposal, ProposedMember, RequestSnapshot, Requirement, RuleIssue
from app.policy import DEFAULT_POLICY, StaffingPolicy


def effective_role(candidate: Candidate, code: str, request: RequestSnapshot) -> bool:
    return any(role.code == code and role.starts_on <= request.starts_on
               and (role.ends_on is None or role.ends_on >= request.ends_on) for role in candidate.roles)


def eligible_for_slot(candidate: Candidate, role: PodRole, request: RequestSnapshot) -> bool:
    """Live authorization is explicit, never inherited from an advisory policy.

    Frozen policies may still describe the former Lead-as-Member behavior. Keep
    those historical documents intact, but they cannot grant a person an absent
    role when making a new recommendation, preview or assignment.
    """
    return candidate.active and effective_role(candidate, PodRole(role).value, request)


def capability_strength(candidate: Candidate, requirement: Requirement, request: RequestSnapshot) -> Decimal | None:
    if requirement.assessment_type == "ROLE_DERIVED":
        return Decimal(5) if requirement.derived_role_code and effective_role(candidate, requirement.derived_role_code, request) else None
    return next((row.strength for row in candidate.skills if row.skill_id == requirement.skill_id), None)


def covers(candidate: Candidate, requirement: Requirement, request: RequestSnapshot, policy: StaffingPolicy) -> bool:
    if policy.scheduling and requirement.assessment_type == "SELF_RATED" and not any(
        skill.skill_id == requirement.skill_id and skill.evidence for skill in candidate.skills
    ):
        return False
    strength = capability_strength(candidate, requirement, request)
    return strength is not None and strength >= (requirement.minimum_strength or policy.minimum_strength)


def minimum_member_contribution(request: RequestSnapshot, policy: StaffingPolicy) -> Decimal:
    if not policy.scheduling:
        return Decimal("0.01")
    slots = request.lead_count + request.member_count
    fair_share = request.total_hours / slots * policy.scheduling.minimum_equal_share_pct / 100
    return max(policy.scheduling.minimum_member_hours, fair_share).quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def has_relevant_evidence(person: Candidate, request: RequestSnapshot, policy: StaffingPolicy) -> bool:
    if any(covers(person, item, request, policy) for item in request.requirements):
        return True
    return any(item.deliverable_id in request.deliverable_ids and item.experience
               and (item.experience_level != ExperienceLevel.LEARNING or item.interested)
               for item in person.deliverables)


def member_schedule(member: ProposedMember, request: RequestSnapshot, policy: StaffingPolicy):
    """Approval checks the published schedule; it must never silently re-plan it."""
    if not policy.scheduling:
        legacy = spread_hours(member.hours, request.starts_on, request.ends_on)
        if member.daily_schedule and member.daily_schedule != legacy:
            raise ValueError("Legacy proposal schedule differs from its policy")
        return legacy
    schedule = member.daily_schedule
    if not schedule or len({item.day for item in schedule}) != len(schedule):
        raise ValueError("Availability-aware proposals require unique scheduled dates")
    if any(item.hours <= 0 or item.day.weekday() >= 5
           or not request.starts_on <= item.day <= request.ends_on for item in schedule):
        raise ValueError("Proposal includes unavailable calendar dates or nonpositive hours")
    if sum((item.hours for item in schedule), Decimal(0)) != member.hours:
        raise ValueError("Published schedule and planned hours disagree")
    return tuple(sorted(schedule, key=lambda item: item.day))


def validate_pod(request: RequestSnapshot, proposal: Proposal, candidates: tuple[Candidate, ...],
                 ledgers: dict[str, CapacityLedger], policy: StaffingPolicy = DEFAULT_POLICY,
                 *, catalogue: dict | None = None) -> tuple[RuleIssue, ...]:
    """Mandatory final gate. Agents cannot bypass it or directly write assignments."""
    issues = []

    def issue(code, message, person_id=None, reference_id=None):
        issues.append(RuleIssue(code=code, message=message, person_id=person_id, reference_id=reference_id))

    if proposal.request_id != request.request_id or proposal.request_revision != request.revision:
        issue("STALE_REQUEST", "Proposal does not match this request revision.")
    if proposal.policy_version != policy.version:
        issue("STALE_POLICY", "Proposal does not match this policy version.")
    if len({row.person_id for row in candidates}) != len(candidates):
        issue("DUPLICATE_EVIDENCE", "Candidate snapshot contains duplicate people.")
        return tuple(issues)
    people = {row.person_id: row for row in candidates}
    ids = [row.person_id for row in proposal.members]
    if len(set(ids)) != len(ids):
        issue("DUPLICATE_PERSON", "A person cannot occupy two slots in the same POD.")
    if sum(row.role == PodRole.LEAD for row in proposal.members) != request.lead_count or sum(row.role == PodRole.MEMBER for row in proposal.members) != request.member_count:
        issue("POD_SIZE", "The proposed lead/member counts do not match the request.")
    if sum((row.hours for row in proposal.members), Decimal(0)) != request.total_hours:
        issue("EFFORT_TOTAL", "Individual assigned hours must equal the request's total person-hours.")
    assigned_deliverables = {item for row in proposal.members for item in row.deliverable_ids}
    if assigned_deliverables != set(request.deliverable_ids):
        issue("DELIVERABLE_SCOPE", "Assign all and only the requested deliverables.")
    eligible = []
    minimum_hours = minimum_member_contribution(request, policy)
    for member in proposal.members:
        person = people.get(member.person_id)
        if person is None or not person.active:
            issue("INACTIVE_OR_UNKNOWN", "Person is missing or inactive.", member.person_id)
            continue
        if not eligible_for_slot(person, member.role, request):
            issue("ROLE_INELIGIBLE", "An effective eligible role is required for the scheduled period.", member.person_id)
            continue
        if policy.scheduling:
            if member.hours < minimum_hours:
                issue("MINIMUM_CONTRIBUTION", f"Each selected person needs at least {minimum_hours} planned hours for this POD size.", person.person_id)
            if not has_relevant_evidence(person, request, policy):
                issue("IRRELEVANT_MEMBER", "Each member needs relevant capability or deliverable evidence; free capacity alone is insufficient.", person.person_id)
        eligible.append(person)
        if person.person_id not in ledgers:
            issue("CAPACITY_UNKNOWN", "Working capacity/commitments have not been retrieved.", person.person_id)
        else:
            try:
                result = calculate_capacity(ledgers[person.person_id], request.starts_on, request.ends_on,
                                            member_schedule(member, request, policy), policy.maximum_allocation_pct,
                                            allow_empty_weeks=policy.scheduling is not None)
                if not result.feasible:
                    issue("CAPACITY_EXCEEDED", "The proposed schedule exceeds capacity or includes unavailable days.", person.person_id)
            except ValueError:
                issue("INVALID_SCHEDULE", "The proposed effort cannot be scheduled in this period.", person.person_id)
    for requirement in request.requirements:
        if not requirement.mandatory:
            continue
        if requirement.assessment_type == "ROLE_DERIVED" and not requirement.derived_role_code:
            issue("ROLE_MAPPING_MISSING", "The required role-derived capability has no approved mapping.", reference_id=requirement.skill_id)
        elif not any(covers(person, requirement, request, policy) for person in eligible):
            issue("CAPABILITY_GAP", "The POD does not meet a mandatory capability threshold.", reference_id=requirement.skill_id)
    # Supported experience cannot be presented as independent ownership. Require a suitable
    # teammate assigned to the SAME deliverable, not an unrelated person elsewhere in the pool.
    assignments = {member.person_id: set(member.deliverable_ids) for member in proposal.members}
    if policy.scheduling:
        mandatory = {item.skill_id: item for item in request.requirements if item.mandatory}
        for deliverable_id in request.deliverable_ids:
            if catalogue is None or deliverable_id not in catalogue:
                issue("CATALOGUE_EVIDENCE_MISSING", "Retrieve catalogue evidence before validating this deliverable.", reference_id=deliverable_id)
                continue
            assignees = [p for p in eligible if deliverable_id in assignments[p.person_id]]
            experienced_owner = any(any(e.deliverable_id == deliverable_id and bool(e.experience)
                and e.experience_level in {ExperienceLevel.INDEPENDENT, ExperienceLevel.MENTOR}
                and e.contribution_scope == "END_TO_END" for e in p.deliverables) for p in assignees)
            mapped = {row.get('skill_id') for row in catalogue[deliverable_id].get('mapped_capabilities', ())} & mandatory.keys()
            # Respect request-specific removal of catalogue defaults. Never treat an
            # empty mapping as proof of coverage, or unrelated POD skills as owners.
            skill_coverage = bool(mapped) and all(any(covers(p, mandatory[skill], request, policy)
                for p in assignees) for skill in mapped)
            if not experienced_owner and not skill_coverage:
                issue("DELIVERABLE_COVERAGE_GAP", "Assign evidenced delivery experience or the matching required capabilities to this deliverable.", reference_id=deliverable_id)
    for person in eligible:
        for evidence in person.deliverables:
            needs_support = evidence.experience_level == ExperienceLevel.SUPPORTED or (
                policy.scheduling is not None and evidence.experience_level == ExperienceLevel.LEARNING)
            if evidence.deliverable_id not in assignments[person.person_id] or not needs_support:
                continue
            supported = any(other.person_id != person.person_id
                and evidence.deliverable_id in assignments[other.person_id]
                and any(item.deliverable_id == evidence.deliverable_id
                        and item.experience_level in {ExperienceLevel.INDEPENDENT, ExperienceLevel.MENTOR}
                        and item.contribution_scope == "END_TO_END" and bool(item.experience)
                        for item in other.deliverables) for other in eligible)
            if not supported:
                issue("SUPPORT_REQUIRED", "Add a capable teammate for this deliverable or revise the plan.", person.person_id, evidence.deliverable_id)
    return tuple(issues)


def score_candidate(candidate: Candidate, request: RequestSnapshot, projected_allocation_pct: Decimal,
                    policy: StaffingPolicy = DEFAULT_POLICY) -> dict:
    """Draft ranking formula; eligibility is a separate, mandatory gate. No LLM-generated scores."""
    if not projected_allocation_pct.is_finite() or not Decimal(0) <= projected_allocation_pct <= 100:
        raise ValueError("Score only candidates with known, feasible projected capacity")
    if not candidate.active:
        raise ValueError("Inactive candidates cannot be scored")
    strengths = [None if policy.scheduling and requirement.assessment_type == "SELF_RATED" and not any(
        item.skill_id == requirement.skill_id and item.evidence for item in candidate.skills
    ) else capability_strength(candidate, requirement, request) for requirement in request.requirements]
    skill = sum((strength or Decimal(0)) / 5 for strength in strengths) / len(strengths)
    levels = {ExperienceLevel.LEARNING: Decimal(0), ExperienceLevel.SUPPORTED: Decimal("0.4"),
              ExperienceLevel.INDEPENDENT: Decimal("0.8"), ExperienceLevel.MENTOR: Decimal(1)}
    evidence = {row.deliverable_id: row for row in candidate.deliverables}
    delivery_scores = []
    for deliverable_id in request.deliverable_ids:
        item = evidence.get(deliverable_id)
        delivery_scores.append(levels[item.experience_level] * (Decimal(1) if item.contribution_scope == "END_TO_END" else Decimal("0.5"))
                               if item and item.experience else Decimal(0))
    delivery = sum(delivery_scores) / len(delivery_scores)
    interested = {row.skill_id for row in candidate.skills if row.interested}
    interests = sum(requirement.skill_id in interested for requirement in request.requirements)
    interests += sum(bool(evidence.get(item) and evidence[item].interested) for item in request.deliverable_ids)
    interest = Decimal(interests) / (len(request.requirements) + len(request.deliverable_ids))
    factors = {"skill": skill, "deliverable": delivery, "capacity": 1 - projected_allocation_pct / 100, "interest": interest}
    weighted = {name: value * getattr(policy.weights, name) for name, value in factors.items()}
    return {"person_id": candidate.person_id, "policy_version": policy.version,
            "score": sum(weighted.values()).quantize(Decimal("0.01")),
            "factors": weighted, "unknown_skill_ids": [item.skill_id for item, strength in zip(request.requirements, strengths, strict=True) if strength is None]}
