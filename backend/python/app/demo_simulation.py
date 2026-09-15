"""Read-only preflight of demonstration inputs through the real staffing rules.

No database mutation, model call or worker is used here. All candidate evidence,
proposals, assignments and capacity changes exist only in local Python objects.
"""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from app.capacity import CapacityLedger, DailyHours, calculate_capacity, spread_hours
from app.capacity_admin import build_days
from app.contracts import Candidate, Proposal, ProposedMember, RequestSnapshot, Requirement
from app.demo_dataset import DemoProject
from app.errors import ServiceError
from app.policy import DEFAULT_POLICY
from app.rules import validate_pod
from app.storage import calendar_day, rows


BASELINE_POLICY = "staffing-baseline-v1"
EVENT_CLASSIFICATION = {
    "ooo": "NON_AVAILABILITY",
    "leave": "NON_AVAILABILITY",
    "travel": "NON_AVAILABILITY",
    "commitment": "EXTERNAL_WORK",
}


def _require(condition, message, code="DEMO_SIMULATION_FAILED"):
    if not condition:
        raise ServiceError(code, message, 409)


def classify_event(event):
    """Copy/normalize a retained event without changing its stored record."""
    item = dict(event)
    kind = item.get("capacity_kind")
    if kind in (None, "UNKNOWN"):
        kind = EVENT_CLASSIFICATION.get(str(item.get("event_type", "")).strip().lower())
    _require(
        kind in {"NON_AVAILABILITY", "EXTERNAL_WORK"},
        "An existing availability event needs manual classification.",
        "EVENT_CLASSIFICATION",
    )
    item["capacity_kind"] = kind
    item["starts_on"] = calendar_day(item["starts_on"])
    item["ends_on"] = calendar_day(item["ends_on"])
    return item


def resolve_project(project: DemoProject, events) -> DemoProject:
    """Fit a *new* baseline project's end before its first retained absence.

    The unchanged total effort must subsequently pass validate_pod on the shorter
    period. No hours, absence or existing request are silently discarded. This is
    data preparation only; it is not a change to the runtime planner.
    """
    members = {member.person_id for member in project.members}
    absences = [classify_event(event) for event in events if event.get("person_id") in members]
    overlap = [
        event
        for event in absences
        if event["capacity_kind"] == "NON_AVAILABILITY"
        and event["starts_on"] <= project.ends_on
        and event["ends_on"] >= project.starts_on
    ]
    if not overlap:
        return project
    cutoff = min(event["starts_on"] for event in overlap) - timedelta(days=1)
    while cutoff.weekday() >= 5:
        cutoff -= timedelta(days=1)
    _require(
        cutoff >= project.starts_on,
        f"Baseline {project.request_id} starts during retained absence; review the prepared schedule.",
        "DEMO_BASELINE_SCHEDULE",
    )
    return replace(project, ends_on=min(project.ends_on, cutoff))


def distribute_external(days, weekly_hours):
    """Allocate additional weekly commitments only into available daily headroom.

    Retained external work is counted separately and reduces the room for this
    additional baseline. All calculations use hundredths of an hour. A completely
    absent week has no recurring operational work scheduled.
    """
    weekly = Decimal(str(weekly_hours))
    _require(
        weekly.is_finite() and weekly >= 0 and weekly == weekly.quantize(Decimal("0.01")),
        "External weekly hours must be nonnegative with at most two decimal places.",
    )
    working = sorted(day for day, value in days.items() if value["available"] > 0)
    if not working or not weekly:
        return {}
    caps = {
        day: max(0, int((days[day]["available"] - days[day].get("external", Decimal(0))) * 100))
        for day in working
    }
    remaining = int(weekly * 100)
    _require(
        sum(caps.values()) >= remaining,
        "External work does not fit this person's retained absence and commitment schedule.",
        "DEMO_EXTERNAL_CAPACITY",
    )
    assigned = dict.fromkeys(working, 0)
    while remaining:
        eligible = [day for day in working if assigned[day] < caps[day]]
        portion = max(1, remaining // len(eligible))
        for day in eligible:
            value = min(portion, caps[day] - assigned[day], remaining)
            assigned[day] += value
            remaining -= value
    return {day: Decimal(cents) / 100 for day, cents in assigned.items() if cents}


def _event_key(event):
    return (
        event["person_id"],
        event.get("title"),
        calendar_day(event["starts_on"]),
        calendar_day(event["ends_on"]),
        event.get("event_type"),
    )


def retained_events(connection, dataset):
    return [
        classify_event(event)
        for event in rows(
            connection,
            """SELECT person_id,availability_id,event_type,
        capacity_kind,starts_on,ends_on,allocated_hours,title FROM availability
        WHERE starts_on<=:endDay AND ends_on>=:startDay""",
            startDay=dataset.anchor,
            endDay=dataset.capacity_end,
        )
    ]


def _all_events(connection, dataset):
    existing = retained_events(connection, dataset)
    seen = {_event_key(event) for event in existing}
    events = list(existing)
    for index, item in enumerate(dataset.availability):
        event = {
            "person_id": item.person_id,
            "availability_id": f"new-demo-{index}",
            "event_type": item.event_type,
            "capacity_kind": item.capacity_kind,
            "starts_on": item.starts_on,
            "ends_on": item.ends_on,
            "allocated_hours": item.hours,
            "title": item.title,
        }
        if _event_key(event) not in seen:
            events.append(classify_event(event))
            seen.add(_event_key(event))
    return existing, events


def _candidates(dataset, skills, catalogue):
    return tuple(
        Candidate(
            person_id=person.person_id,
            active=True,
            roles=({"code": person.role_code, "starts_on": dataset.anchor},),
            skills=tuple(
                {
                    "skill_id": skills[item.name]["interest_id"],
                    "strength": item.strength,
                    "interested": item.interested,
                    "evidence": item.evidence,
                }
                for item in person.skills
            ),
            deliverables=tuple(
                {
                    "deliverable_id": catalogue[item.project_type, item.deliverable_name]["deliverable_id"],
                    "experience_level": item.experience_level,
                    "contribution_scope": item.contribution_scope,
                    "interested": item.interested,
                    "experience": item.experience,
                }
                for item in person.deliverables
            ),
        )
        for person in dataset.people
        if person.staffing_eligible
    )


def simulate(connection, dataset, skills, catalogue):
    """Read retained inputs, then validate the entire proposed dataset in memory.

    ``skills``/``catalogue`` are the exact-name dictionaries returned by the
    loader's read_catalog. The result is JSON-safe for the operator's plan output.
    """
    existing, events = _all_events(connection, dataset)
    candidates = _candidates(dataset, skills, catalogue)
    skill_by_id = {item["interest_id"]: item for item in skills.values()}
    ledgers = {}
    for person in dataset.people:
        person_events = [event for event in events if event["person_id"] == person.person_id]
        days = build_days(person.weekly_hours, dataset.anchor, dataset.capacity_end, person_events)
        start = dataset.anchor
        while start <= dataset.capacity_end:
            week = {day: value for day, value in days.items() if start <= day <= start + timedelta(days=6)}
            for day, hours in distribute_external(week, person.external_weekly_hours).items():
                days[day]["external"] += hours
            start += timedelta(days=7)
        ledgers[person.person_id] = CapacityLedger(
            weekly_hours=person.weekly_hours,
            absences=tuple(
                DailyHours(day=day, hours=person.weekly_hours / 5 - value["available"])
                for day, value in days.items()
                if day.weekday() < 5 and value["available"] < person.weekly_hours / 5
            ),
            external_work=tuple(
                DailyHours(day=day, hours=value["external"])
                for day, value in days.items()
                if value["external"]
            ),
        )
    policy = DEFAULT_POLICY.model_copy(update={"version": BASELINE_POLICY})
    schedules = []
    assignment_count = assignment_day_count = 0
    planned_hours = Decimal(0)
    for original in dataset.projects:
        project = resolve_project(original, events)
        item = catalogue[project.project_type, project.deliverable_name]
        mapped = rows(
            connection,
            "SELECT skill_id FROM deliverable_skills WHERE deliverable_id=:deliverableId",
            deliverableId=item["deliverable_id"],
        )
        requirements = []
        for entry in mapped:
            skill = skill_by_id[entry["skill_id"]]
            derived = skill["assessment_type"] == "ROLE_DERIVED"
            requirements.append(
                Requirement(
                    skill_id=entry["skill_id"],
                    mandatory=True,
                    assessment_type=skill["assessment_type"],
                    minimum_strength=None if derived else Decimal(3),
                    derived_role_code=(skill.get("derived_role_code") or "POD_LEAD") if derived else None,
                )
            )
        request = RequestSnapshot(
            request_id=project.request_id,
            revision=1,
            responsible_captain_id=project.captain_id,
            title=project.title,
            starts_on=project.starts_on,
            ends_on=project.ends_on,
            total_hours=project.total_hours,
            lead_count=1,
            member_count=len(project.members) - 1,
            deliverable_ids=(item["deliverable_id"],),
            requirements=tuple(requirements),
        )
        proposal = Proposal(
            request_id=project.request_id,
            request_revision=1,
            policy_version=BASELINE_POLICY,
            members=tuple(
                ProposedMember(
                    person_id=member.person_id,
                    role=member.role,
                    hours=member.hours,
                    responsibilities=member.responsibilities,
                    deliverable_ids=(item["deliverable_id"],),
                )
                for member in project.members
            ),
            rationale="Existing delivery plan with named owners and scheduled contributions.",
            evidence_refs=(f"request:{project.request_id}",),
        )
        issues = validate_pod(request, proposal, candidates, ledgers, policy)
        _require(
            not issues,
            f"Baseline {project.request_id} failed simulation: "
            + ", ".join(
                f"{issue.code}:{issue.person_id or issue.reference_id or 'request'}" for issue in issues
            ),
        )
        for member in project.members:
            ledger = ledgers[member.person_id]
            committed = {work.day: work.hours for work in ledger.confirmed_work}
            for work in spread_hours(member.hours, project.starts_on, project.ends_on):
                committed[work.day] = committed.get(work.day, Decimal(0)) + work.hours
                assignment_day_count += bool(work.hours)
            ledgers[member.person_id] = ledger.model_copy(
                update={
                    "confirmed_work": tuple(
                        DailyHours(day=day, hours=hours) for day, hours in sorted(committed.items())
                    )
                }
            )
            assignment_count += 1
            planned_hours += member.hours
        schedules.append(
            {
                "request_id": project.request_id,
                "starts_on": project.starts_on.isoformat(),
                "ends_on": project.ends_on.isoformat(),
                "original_ends_on": original.ends_on.isoformat(),
                "date_adjusted": project.ends_on != original.ends_on,
                "person_hours": str(project.total_hours),
                "people": len(project.members),
            }
        )
    allocation = []
    for person in dataset.people:
        ledger = ledgers[person.person_id]
        result = calculate_capacity(ledger, dataset.anchor, dataset.capacity_end, ())
        # Fully absent weeks with zero workload are valid capacity inputs. They
        # cannot receive staffing, but need not make this data-load preflight fail.
        _require(
            not result.overloaded_days
            and all(week.committed_hours <= week.available_hours for week in result.weeks),
            f"Retained commitments or baseline assignments overbook {person.person_id} during the capacity window.",
        )
        if person.role_code == "SYSTEM_ADMINISTRATOR":
            continue
        first = result.weeks[0]
        allocation.append(
            {
                "person_id": person.person_id,
                "full_name": person.full_name,
                "role_code": person.role_code,
                "available_hours": str(first.available_hours),
                "committed_hours": str(first.committed_hours),
                "allocation_pct": str(first.allocation_pct) if first.allocation_pct is not None else None,
                "active_pods_in_week": sum(
                    any(member.person_id == person.person_id for member in project.members)
                    and project.starts_on <= dataset.anchor + timedelta(days=6)
                    and project.ends_on >= dataset.anchor
                    for project in dataset.projects
                ),
            }
        )
    return {
        "status": "PASS",
        "writes": 0,
        "weeks_validated": (dataset.capacity_end - dataset.anchor).days // 7 + 1,
        "people_validated": len(ledgers),
        "retained_availability_events": len(existing),
        "projects": schedules,
        "assignments": assignment_count,
        "assignment_days": assignment_day_count,
        "planned_hours": str(planned_hours),
        "first_week_allocation": allocation,
    }
