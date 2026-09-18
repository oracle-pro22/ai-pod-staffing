"""Explicit Captain exceptions; no model, invented skill or changed source ledger.

Only named manual slots ignore leave/external work and use 100% of contracted
Mon-Fri hours. Counted POD assignment days are ALWAYS retained. Other slots keep
the normal policy, including its configured utilization ceiling.
"""
import hashlib
from decimal import Decimal, ROUND_HALF_UP
from pydantic import StrictBool

from app.capacity import CapacityLedger, available_day_caps, calculate_capacity, dates_between, schedule_available_hours
from app.contracts import Contract, EntityId, PodRole, Proposal, ProposedMember
from app.errors import ServiceError
from app.planning import PlanOption, divide_hours, max_hours, score_plan_member, _member_deliverables, _responsibilities
from app.rules import effective_role, minimum_member_contribution, validate_pod


class ManualSlot(Contract):
    person_id: EntityId
    role: PodRole
    manual: StrictBool


def pod_only(ledger):
    return CapacityLedger(weekly_hours=ledger.weekly_hours, confirmed_work=ledger.confirmed_work)


def load_metrics(ledger, request, schedule):
    result = calculate_capacity(ledger, request.starts_on, request.ends_on, schedule, Decimal(100), allow_empty_weeks=True)
    def pct(hours, capacity):
        return (hours / capacity * 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) if capacity else None
    days = set(dates_between(request.starts_on, request.ends_on))
    absence = {d.day: d.hours for d in ledger.absences}
    capacity = sum((max(Decimal(0), ledger.weekly_hours / 5 - absence.get(d, Decimal(0)))
                    for d in days if d.weekday() < 5), Decimal(0))
    committed = sum((d.hours for d in (*ledger.confirmed_work, *ledger.external_work) if d.day in days), Decimal(0))
    hours = sum((d.hours for d in schedule), Decimal(0))
    nonempty = [week for week in result.weeks if week.allocation_pct is not None]
    peak = max(nonempty, key=lambda w: w.allocation_pct) if nonempty else None
    return {'current_window_allocation_pct': pct(committed, capacity), 'window_allocation_pct': pct(committed + hours, capacity),
            'window_available_hours': capacity, 'window_committed_hours': committed,
            'projected_allocation_pct': peak.allocation_pct if peak else None,
            'peak_week_start': peak.week_start.isoformat() if peak else None,
            'weekly_capacity': [w.model_dump(mode='json') for w in result.weeks],
            'no_available_capacity': any(w.available_hours == 0 for w in result.weeks),
            'feasible': result.feasible}


def manual_plan(bundle, slots):
    req, policy = bundle.request, bundle.policy
    ids = [s.person_id for s in slots]
    manual_ids = {s.person_id for s in slots if s.manual}
    if (not manual_ids or len(set(ids)) != len(ids)
        or sum(s.role == PodRole.LEAD for s in slots) != req.lead_count
        or sum(s.role == PodRole.MEMBER for s in slots) != req.member_count):
        raise ServiceError('INVALID_MANUAL_TEAM', 'Select the exact POD size, unique people and at least one explicit manual override.', 422)
    people = {p.person_id: p for p in bundle.candidates}
    # Stable ordering preserves deterministic rounding independently of client order.
    slots = sorted(slots, key=lambda s: (s.role != PodRole.LEAD, s.person_id))
    ledgers, caps = {}, []
    for slot in slots:
        person = people.get(slot.person_id)
        role_codes = (policy.lead_role_code,) if slot.role == PodRole.LEAD else policy.member_role_codes
        if person is None or not person.active or not any(effective_role(person, role, req) for role in role_codes):
            raise ServiceError('ROLE_INELIGIBLE', 'Manual choices still require an active person and an eligible role for the entire request.', 409)
        original = bundle.ledgers.get(slot.person_id)
        if original is None:
            raise ServiceError('CAPACITY_UNKNOWN', 'Retrieve current working hours and assignment history before manual scheduling.', 409)
        ledgers[slot.person_id] = pod_only(original) if slot.manual else original
        if slot.manual:
            caps.append(min(int(req.total_hours * 100), sum(available_day_caps(ledgers[slot.person_id], req.starts_on, req.ends_on, Decimal(100)).values())))
        else:
            caps.append(max_hours(bundle, slot.person_id))
    minimum = int(minimum_member_contribution(req, policy) * 100)
    allocation = divide_hours(int(req.total_hours * 100), caps, minimum)
    if allocation is None:
        raise ServiceError('MANUAL_CAPACITY_EXCEEDED', 'This exact team cannot fit the effort. Manual people remain capped at 100% including existing POD work; other people retain normal rules. Change people, dates or effort.', 409)
    proposed = []
    for slot, cents in zip(slots, allocation, strict=True):
        hours = Decimal(cents) / 100
        dids = req.deliverable_ids if slot.manual else _member_deliverables(bundle, people[slot.person_id], slot.role == PodRole.LEAD)
        schedule = schedule_available_hours(ledgers[slot.person_id], hours, req.starts_on, req.ends_on,
                                            Decimal(100) if slot.manual else policy.maximum_allocation_pct)
        responsibility = ('Captain-assigned work on ' + ', '.join(bundle.catalogue[d].get('deliverable_name', d) for d in dids)
                          + f'; {hours} planned hours. Skill and experience suitability overridden by the Captain.') if slot.manual else _responsibilities(bundle, people[slot.person_id], slot.role == PodRole.LEAD, hours, dids)
        proposed.append(ProposedMember(person_id=slot.person_id, role=slot.role, hours=hours,
                                      daily_schedule=schedule, deliverable_ids=dids, responsibilities=responsibility[:2000]))
    proposal = Proposal(request_id=req.request_id, request_revision=req.revision, policy_version=policy.version,
        members=tuple(proposed), rationale='Captain-selected team. Explicit manual exceptions; no AI recommendation for manual choices.',
        evidence_refs=(f'request:{req.request_id}', *(f'person:{pid}' for pid in ids)))
    issues = validate_pod(req, proposal, bundle.candidates, bundle.ledgers, policy, catalogue=bundle.catalogue)
    waived = []
    for issue in issues:
        personal = issue.person_id in manual_ids and issue.code in {'IRRELEVANT_MEMBER', 'CAPACITY_EXCEEDED', 'SUPPORT_REQUIRED'}
        # Manual slots explicitly take responsibility for all requested deliverables.
        shared = issue.person_id is None and issue.code in {'CAPABILITY_GAP', 'ROLE_MAPPING_MISSING', 'DELIVERABLE_COVERAGE_GAP'}
        if personal or shared:
            waived.append(issue.model_dump(mode='json'))
        else:
            raise ServiceError('MANUAL_TEAM_INVALID', f'Non-bypassable staffing check: {issue.code}. Normal selections must still satisfy all normal rules.', 409)
    scores = {}
    for member in proposed:
        if member.person_id not in manual_ids:
            scores[member.person_id] = score_plan_member(bundle, member)
            continue
        ledger = bundle.ledgers[member.person_id]
        facts = load_metrics(pod_only(ledger), req, member.daily_schedule)
        if not facts['feasible']:
            raise ServiceError('MANUAL_CAPACITY_EXCEEDED', 'Existing and proposed POD hours exceed 100% of contracted daily, request-window or weekly hours.', 409)
        period = set(dates_between(req.starts_on, req.ends_on))
        scores[member.person_id] = {**facts, 'score': None, 'factors': {}, 'allocation_basis': 'POD_ONLY_CONTRACTED',
            'maximum_allocation_pct': Decimal(100), 'scheduling_algorithm': 'available-days-v2',
            'daily_schedule': [d.model_dump(mode='json') for d in member.daily_schedule],
            'reported_workload': load_metrics(ledger, req, member.daily_schedule),
            'ignored_leave_hours': sum((d.hours for d in ledger.absences if d.day in period), Decimal(0)),
            'ignored_external_hours': sum((d.hours for d in ledger.external_work if d.day in period), Decimal(0)),
            'bypassed_checks': ['SKILL_AND_EXPERIENCE', 'NORMAL_UTILIZATION_CEILING', 'LEAVE', 'EXTERNAL_COMMITMENTS'],
            'recorded_gaps': [i for i in waived if i['person_id'] in (None, member.person_id)]}
    digest = hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()[:20]
    return PlanOption(plan_id=f'MANUAL-{digest}', proposal=proposal, scores=scores, average_score=None)
