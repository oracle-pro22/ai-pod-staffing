"""Deterministic staffing search. No LLM, SQL, assignment or email side effects."""
import hashlib
import json
from itertools import combinations
from decimal import ROUND_HALF_UP, Decimal

from pydantic import Field

from app.capacity import (CapacityLedger, available_day_caps, calculate_capacity, dates_between,
                          distribute_cents, schedule_available_hours, spread_hours)
from app.contracts import Candidate, Contract, Proposal, ProposedMember, RequestSnapshot
from app.policy import StaffingPolicy
from app.errors import ServiceError
from app.rules import (covers, effective_role, has_relevant_evidence, member_schedule,
                       minimum_member_contribution, score_candidate, validate_pod)


class EvidenceBundle(Contract):
    request: RequestSnapshot
    policy: StaffingPolicy
    candidates: tuple[Candidate, ...]
    ledgers: dict[str, CapacityLedger]
    versions: dict[str, dict[str, int]]
    names: dict[str, str]
    context: dict[str, str]
    catalogue: dict[str, dict]
    feedback: tuple[dict, ...] = ()
    exclusions: dict[str, str] = Field(default_factory=dict)

    def reference_ids(self):
        return {f"request:{self.request.request_id}", f"policy:{self.policy.version}",
                *(f"person:{p.person_id}" for p in self.candidates),
                *(f"capacity:{person_id}" for person_id in self.ledgers),
                *(f"deliverable:{key}" for key in self.catalogue),
                *(f"decision:{item['decision_id']}" for item in self.feedback)}


class PlanOption(Contract):
    plan_id: str
    proposal: Proposal
    scores: dict[str, dict]
    average_score: Decimal | None


class SearchResult(Contract):
    options: tuple[PlanOption, ...]
    examined: int
    exhaustive: bool
    exclusions: dict[str, str]


def max_hours(bundle: EvidenceBundle, person_id: str) -> int:
    """Maximum cents that fit the policy's scheduling algorithm."""
    req = bundle.request
    ledger = bundle.ledgers.get(person_id)
    if ledger is None:
        return 0
    if bundle.policy.scheduling:
        return min(int(req.total_hours * 100), sum(available_day_caps(
            ledger, req.starts_on, req.ends_on, bundle.policy.maximum_allocation_pct).values()))
    low, high = 0, int(req.total_hours * 100)
    while low < high:
        middle = (low + high + 1) // 2
        try:
            feasible = calculate_capacity(ledger, req.starts_on, req.ends_on,
                spread_hours(Decimal(middle) / 100, req.starts_on, req.ends_on),
                bundle.policy.maximum_allocation_pct).feasible
        except ValueError:
            feasible = False
        if feasible:
            low = middle
        else:
            high = middle - 1
    return low


def divide_hours(total_cents: int, caps: list[int], minimum_cents: int = 1) -> list[int] | None:
    """Meaningful, balanced slots; exact conserved total and individual headroom."""
    return distribute_cents(total_cents, caps, minimum_cents)


def score_plan_member(bundle: EvidenceBundle, member: ProposedMember) -> dict:
    """Recompute factual metrics from the exact plan, also used at publication.

    projected_allocation_pct remains the busiest full-week figure for API
    compatibility. Period figures are separately labelled and never mixed with
    current-calendar-week allocation shown elsewhere in the application.
    """
    request, policy = bundle.request, bundle.policy
    candidate = next(p for p in bundle.candidates if p.person_id == member.person_id)
    ledger = bundle.ledgers[member.person_id]
    schedule = member_schedule(member, request, policy)
    result = calculate_capacity(ledger, request.starts_on, request.ends_on, schedule,
                                policy.maximum_allocation_pct, allow_empty_weeks=policy.scheduling is not None)
    if not result.feasible:
        raise ValueError("Only a feasible published schedule can be scored")
    nonempty = [week for week in result.weeks if week.allocation_pct is not None]
    peak = max(nonempty, key=lambda week: week.allocation_pct)
    def pct(used, available):
        return (used / available * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if available else None
    weeks = [{**week.model_dump(mode='json'),
              'current_allocation_pct': pct(week.committed_hours, week.available_hours)} for week in result.weeks]
    absence = {row.day: row.hours for row in ledger.absences}
    work = {}
    for row in (*ledger.confirmed_work, *ledger.external_work):
        work[row.day] = work.get(row.day, Decimal(0)) + row.hours
    days = list(dates_between(request.starts_on, request.ends_on))
    window_available = sum((max(Decimal(0), ledger.weekly_hours / 5 - absence.get(day, Decimal(0)))
                            for day in days if day.weekday() < 5), Decimal(0))
    window_committed = sum((work.get(day, Decimal(0)) for day in days), Decimal(0))
    score = score_candidate(candidate, request, peak.allocation_pct, policy)
    return {**score, 'projected_allocation_pct': peak.allocation_pct,
            'current_allocation_pct': pct(peak.committed_hours, peak.available_hours),
            'peak_week_start': peak.week_start.isoformat(),
            'available_hours': peak.available_hours, 'committed_hours': peak.committed_hours,
            'proposed_hours': member.hours, 'peak_week_proposed_hours': peak.proposed_hours,
            'window_available_hours': window_available, 'window_committed_hours': window_committed,
            'window_allocation_pct': pct(window_committed + member.hours, window_available),
            'current_window_allocation_pct': pct(window_committed, window_available),
            'weekly_capacity': weeks, 'minimum_member_hours': minimum_member_contribution(request, policy),
            'daily_schedule': [row.model_dump(mode='json') for row in schedule],
            'scheduling_algorithm': policy.scheduling.algorithm if policy.scheduling else 'equal-workdays-v1'}


def _member_deliverables(bundle, person, is_lead):
    if not bundle.policy.scheduling or is_lead:
        return bundle.request.deliverable_ids
    experienced = {item.deliverable_id for item in person.deliverables if item.experience}
    covered = {item.skill_id for item in bundle.request.requirements if covers(person, item, bundle.request, bundle.policy)}
    selected = tuple(did for did in bundle.request.deliverable_ids if did in experienced or any(
        item.get('skill_id') in covered for item in bundle.catalogue.get(did, {}).get('mapped_capabilities', ())))
    # Request-specific capabilities may legitimately apply beyond catalogue defaults.
    return selected or bundle.request.deliverable_ids


def _responsibilities(bundle, person, is_lead, hours, deliverables):
    if not bundle.policy.scheduling:
        return 'Coordinate delivery and guide contributors.' if is_lead else 'Contribute to the requested deliverables with the POD lead.'
    labels = [bundle.catalogue.get(did, {}).get('deliverable_name', did) for did in deliverables]
    names = {item.get('skill_id'): item.get('interest_name', item.get('skill_id'))
             for value in bundle.catalogue.values() for item in value.get('mapped_capabilities', ())}
    covered = [names.get(item.skill_id, item.skill_id) for item in bundle.request.requirements
               if covers(person, item, bundle.request, bundle.policy)]
    role_text = 'Coordinate the POD and contribute to' if is_lead else 'Contribute to'
    text = f"{role_text} {', '.join(labels)}; {hours} planned hours."
    if covered:
        text += f" Recorded capability coverage: {', '.join(covered)}."
    recorded = [item for item in person.deliverables if item.deliverable_id in deliverables and item.experience]
    if recorded:
        text += ' Deliverable experience: ' + ', '.join(sorted({item.experience_level.value.lower() for item in recorded})) + '.'
    if any(item.experience_level.value in ('LEARNING', 'SUPPORTED') for item in recorded):
        text += ' Work with the experienced teammate assigned to the same deliverable.'
    return text[:2000]


def find_options(bundle: EvidenceBundle, limit: int = 2000, keep: int = 3, *,
                 selected_leads: tuple[str, ...] | None = None,
                 selected_members: tuple[str, ...] | None = None) -> SearchResult:
    if not 1 <= limit <= 10000 or not 1 <= keep <= 10:
        raise ValueError("Invalid search bounds")
    req, policy = bundle.request, bundle.policy
    minimum_cents = int(minimum_member_contribution(req, policy) * 100)
    slots = req.lead_count + req.member_count
    if policy.scheduling and minimum_cents * slots > int(req.total_hours * 100):
        raise ServiceError('NEEDS_INFORMATION',
            f'The requested {slots}-person POD needs at least {Decimal(minimum_cents * slots)/100} total hours. Reduce the POD size or review the effort estimate.', 422)
    caps, exclusions = {}, dict(bundle.exclusions)
    for person in sorted(bundle.candidates, key=lambda p: p.person_id):
        caps[person.person_id] = max_hours(bundle, person.person_id) if person.active else 0
        if not caps[person.person_id]:
            exclusions.setdefault(person.person_id, "NO_FEASIBLE_HOURS")
        elif policy.scheduling and caps[person.person_id] < minimum_cents:
            exclusions.setdefault(person.person_id, 'INSUFFICIENT_MEANINGFUL_CAPACITY')
            caps[person.person_id] = 0
        elif policy.scheduling and not has_relevant_evidence(person, req, policy):
            exclusions.setdefault(person.person_id, 'NO_RELEVANT_EVIDENCE')
            caps[person.person_id] = 0
    leads = sorted(p.person_id for p in bundle.candidates if caps[p.person_id] and effective_role(p, policy.lead_role_code, req))
    members = sorted(p.person_id for p in bundle.candidates if caps[p.person_id]
                     and any(effective_role(p, role, req) for role in policy.member_role_codes))
    # Pin an exact Captain selection without changing any candidate's actual
    # roles/evidence. Normal eligibility and full-team validation still apply.
    if selected_leads is not None or selected_members is not None:
        if (selected_leads is None or selected_members is None
            or len(selected_leads) != req.lead_count or len(selected_members) != req.member_count
            or len(set((*selected_leads, *selected_members))) != req.lead_count + req.member_count
            or not set(selected_leads) <= set(leads) or not set(selected_members) <= set(members)):
            return SearchResult(options=(), examined=0, exhaustive=True, exclusions=exclusions)
        leads, members = sorted(selected_leads), sorted(selected_members)
    people = {p.person_id: p for p in bundle.candidates}
    if policy.scheduling:
        # The search remains bounded, but strong relevant candidates are considered
        # first rather than favouring the alphabetically earliest employee IDs.
        def order(person_id):
            minimum_schedule = schedule_available_hours(bundle.ledgers[person_id], Decimal(minimum_cents)/100,
                req.starts_on, req.ends_on, policy.maximum_allocation_pct)
            load = calculate_capacity(bundle.ledgers[person_id], req.starts_on, req.ends_on, minimum_schedule,
                policy.maximum_allocation_pct, allow_empty_weeks=True)
            percent = max(week.allocation_pct for week in load.weeks if week.allocation_pct is not None)
            return (-score_candidate(people[person_id], req, percent, policy)['score'], person_id)
        leads.sort(key=order)
        members.sort(key=order)
    options, examined = [], 0
    for lead_ids in combinations(leads, req.lead_count):
        for member_ids in combinations([p for p in members if p not in lead_ids], req.member_count):
            if examined == limit:
                return SearchResult(options=tuple(options), examined=examined, exhaustive=False, exclusions=exclusions)
            examined += 1
            ids = (*lead_ids, *member_ids)
            allocation = divide_hours(int(req.total_hours * 100), [caps[p] for p in ids], minimum_cents)
            if allocation is None:
                continue
            proposed_rows = []
            for p, cents in zip(ids, allocation, strict=True):
                hours = Decimal(cents) / 100
                dids = _member_deliverables(bundle, people[p], p in lead_ids)
                schedule = schedule_available_hours(bundle.ledgers[p], hours, req.starts_on, req.ends_on,
                    policy.maximum_allocation_pct) if policy.scheduling else ()
                proposed_rows.append(ProposedMember(person_id=p, role='POD_LEAD' if p in lead_ids else 'POD_MEMBER',
                    hours=hours, deliverable_ids=dids, daily_schedule=schedule,
                    responsibilities=_responsibilities(bundle, people[p], p in lead_ids, hours, dids)))
            proposed = tuple(proposed_rows)
            proposal = Proposal(request_id=req.request_id, request_revision=req.revision, policy_version=policy.version,
                members=proposed, rationale="Validated against capability, role, availability and effort constraints.",
                evidence_refs=(f"request:{req.request_id}", *(f"person:{p}" for p in ids), *(f"capacity:{p}" for p in ids)))
            if validate_pod(req, proposal, bundle.candidates, bundle.ledgers, policy, catalogue=bundle.catalogue):
                continue
            scores = {row.person_id: score_plan_member(bundle, row) for row in proposed}
            digest = hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()[:20]
            option = PlanOption(plan_id=f"PLAN-{digest}", proposal=proposal, scores=scores,
                                average_score=(sum(scores[row.person_id]['score'] * row.hours for row in proposed) / req.total_hours
                                               if policy.scheduling else sum(s['score'] for s in scores.values()) / len(scores)))
            options.append(option)
            options.sort(key=lambda item: (-item.average_score, item.plan_id))
            options = options[:keep]
    return SearchResult(options=tuple(options), examined=examined, exhaustive=True, exclusions=exclusions)


def json_text(value) -> str:
    """Stable text for Oracle CLOBs and tool results. Never serialize arbitrary Python objects."""
    if isinstance(value, Contract):
        return value.model_dump_json()
    def encode(item):
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError("Unsupported JSON value")
    return json.dumps(value, default=encode, sort_keys=True, ensure_ascii=False, allow_nan=False)
