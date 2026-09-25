"""Exact-team previews and distinct, conditional replacements. No writes/models.

The selected team is always pinned. Replacement searches change one slot at a
time and validate the entire POD using the existing scheduling/scoring engine.
"""
from decimal import Decimal
from pydantic import Field

from app.contracts import Contract, EntityId, PodRole, ProposedMember
from app.errors import ServiceError
from app.planning import EvidenceBundle, PlanOption, find_options
from app.rules import eligible_for_slot


class Replacement(Contract):
    person_id: EntityId
    role: PodRole
    replaces: EntityId
    member: ProposedMember
    factors: dict
    team_score: Decimal


class Alternatives(Contract):
    replacements: tuple[Replacement, ...] = ()
    examined: int = Field(ge=0)
    exhaustive: bool
    notes: tuple[str, ...] = ()


def selected_ids(option):
    return (tuple(m.person_id for m in option.proposal.members if m.role == PodRole.LEAD),
            tuple(m.person_id for m in option.proposal.members if m.role == PodRole.MEMBER))


def exact_team(bundle: EvidenceBundle, leads, members) -> PlanOption:
    # Restrict computation, not evidence: people retain all their real roles.
    ids = set((*leads, *members))
    scoped = bundle.model_copy(update={"candidates": tuple(p for p in bundle.candidates if p.person_id in ids)})
    result = find_options(scoped, limit=1, keep=1, selected_leads=tuple(leads), selected_members=tuple(members))
    if not result.options:
        raise ServiceError("SELECTION_NOT_FEASIBLE",
            "The selected POD cannot meet the current role, capability, effort or utilization rules. Choose another option.", 409)
    return result.options[0]


def replacement_options(bundle: EvidenceBundle, selected: PlanOption, limit: int = 2000) -> Alternatives:
    leads, members = selected_ids(selected)
    chosen = set((*leads, *members))
    examined, exhaustive, result, notes = 0, True, [], []
    for role, slots in ((PodRole.LEAD, leads), (PodRole.MEMBER, members)):
        if not slots:
            continue
        candidates = []
        for person in sorted(bundle.candidates, key=lambda p: p.person_id):
            if (person.person_id in chosen or not person.active
                or not eligible_for_slot(person, role, bundle.request)):
                continue
            viable = []
            for old in slots:
                if examined >= limit:
                    exhaustive = False
                    break
                examined += 1
                new_slots = tuple(person.person_id if pid == old else pid for pid in slots)
                try:
                    option = exact_team(bundle, new_slots if role == PodRole.LEAD else leads,
                                        new_slots if role == PodRole.MEMBER else members)
                except ServiceError as error:
                    if error.code != "SELECTION_NOT_FEASIBLE":
                        raise
                    continue
                member = next(m for m in option.proposal.members if m.person_id == person.person_id)
                viable.append(Replacement(person_id=person.person_id, role=role, replaces=old,
                    member=member, factors=option.scores[person.person_id], team_score=option.average_score))
            if viable:
                viable.sort(key=lambda row: (-row.team_score, row.replaces))
                candidates.append(viable)
            if not exhaustive:
                break
        candidates.sort(key=lambda group: (-group[0].team_score, group[0].person_id))
        # Two additional *people*, not two complete teams with the same person.
        for group in candidates[:2]:
            result.extend(group)
        if len(candidates) < 2:
            notes.append(f"{len(candidates)} additional {role.value.replace('_', ' ').lower()} option(s) fit this selected team. "
                         + ("The bounded search ended; more may exist." if not exhaustive else
                            "Other candidates do not satisfy the current team and capacity rules."))
    return Alternatives(replacements=tuple(result), examined=examined, exhaustive=exhaustive, notes=tuple(notes))
