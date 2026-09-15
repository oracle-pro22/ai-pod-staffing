"""Operator-only demonstration data loader. No model calls, service startup or email.

Plan/verify are read-only. Apply requires stopped writers and verified Oracle
backups; all business DML commits together. No setup.sql, trigger disabling,
TRUNCATE or destructive history reset is used.
"""

import argparse
import json
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from datetime import datetime

from app.capacity import calculate_capacity, spread_hours
from app.capacity_admin import build_days
from app.contracts import Proposal, ProposedMember
from app.demo_dataset import BATCH_ID, build_demo_dataset
from app.demo_backup import (
    MUTABLE_TABLES,
    fingerprints,
    owned_metadata,
    prepare,
    read_state,
    save_state,
    verify_backups,
)
from app.demo_simulation import distribute_external
from app.errors import ServiceError
from app.evidence import collect_evidence
from app.execution_store import execute
from app.planning import json_text
from app.rules import score_candidate, validate_pod
from app.storage import calendar_day, document, load_capacity_ledger, rows

BATCH = BATCH_ID
POLICY = "staffing-baseline-v1"
ADMIN_ID = "P-012"
HISTORY_TABLES = (
    "AGENT_EXECUTIONS",
    "AGENT_EXECUTION_EVENTS",
    "POD_PROPOSALS",
    "POD_PROPOSAL_MEMBERS",
    "APPROVAL_DECISIONS",
    "POD_ASSIGNMENTS",
    "ASSIGNMENT_DAYS",
    "AUDIT_EVENTS",
    "NOTIFICATION_OUTBOX",
)


def demand(ok, message, code="DEMO_DATA_CONFLICT"):
    if not ok:
        raise ServiceError(code, message, 409)


def scalar(c, sql, **binds):
    return rows(c, sql, **binds)[0]["n"]


def read_catalog(c, dataset):
    skills = {
        r["interest_name"]: r
        for r in rows(c, "SELECT interest_id,interest_name,assessment_type,derived_role_code FROM interests")
    }
    ds = rows(
        c,
        """SELECT d.deliverable_id,d.deliverable_name,d.project_type_id,d.source_version,
        p.project_name,p.project_description FROM deliverables d JOIN project_types p ON p.project_type_id=d.project_type_id
        WHERE d.active_flag='Y' """,
    )
    deliverables = {}
    for r in ds:
        key = (r["project_name"], r["deliverable_name"])
        demand(key not in deliverables, f"Ambiguous active catalogue entry: {key}.")
        deliverables[key] = r
    for person in dataset.people:
        for skill in person.skills:
            demand(
                skill.name in skills and skills[skill.name]["assessment_type"] == "SELF_RATED",
                f"Unknown or role-derived self-skill: {skill.name}.",
            )
        for exp in person.deliverables:
            demand(
                (exp.project_type, exp.deliverable_name) in deliverables,
                f"Missing active deliverable: {exp.deliverable_name}.",
            )
    for project in dataset.projects:
        demand(
            (project.project_type, project.deliverable_name) in deliverables,
            f"Missing project deliverable: {project.deliverable_name}.",
        )
    pm = skills.get("Project Manager (GTM SME)")
    demand(
        pm and pm["assessment_type"] == "ROLE_DERIVED" and pm["derived_role_code"] in (None, "POD_LEAD"),
        "Project Manager mapping differs from the agreed POD Lead demonstration mapping.",
    )
    return skills, deliverables


def preflight(c, dataset):
    skills, catalogue = read_catalog(c, dataset)
    existing = rows(c, "SELECT person_id,full_name,external_identity_subject FROM people ORDER BY person_id")
    expected = {p.person_id: p.full_name for p in dataset.people if p.person_id != ADMIN_ID}
    demand(
        {p["person_id"]: p["full_name"] for p in existing} == expected,
        "The existing roster changed. Review the dataset; no people will be silently replaced.",
    )
    demand(
        all(
            not p["external_identity_subject"]
            or p["external_identity_subject"].startswith(("seed:", "demo:"))
            for p in existing
        ),
        "A real identity subject exists; this demonstration loader will not replace it.",
    )
    demand(
        scalar(c, "SELECT COUNT(*) n FROM pod_assignments") == 0,
        "Final assignments already exist. Review their ownership and capacity before reseeding.",
    )
    demand(
        scalar(
            c,
            "SELECT COUNT(*) n FROM app_user_roles WHERE identity_subject NOT LIKE 'seed:%' AND active_flag='Y'",
        )
        == 0,
        "Non-fixture active role mappings exist. Review them before changing personas.",
    )
    demand(
        scalar(
            c,
            "SELECT COUNT(*) n FROM staffing_policies WHERE policy_version=:policyVersion",
            policyVersion=POLICY,
        )
        == 0,
        "Reserved baseline policy already exists without an applied migration.",
    )
    for p in dataset.projects:
        demand(
            scalar(c, "SELECT COUNT(*) n FROM requests WHERE request_id=:requestId", requestId=p.request_id)
            == 0,
            f"Reserved request {p.request_id} is already in use.",
        )
    for role in ("POD_CAPTAIN", "POD_LEAD", "POD_MEMBER", "SYSTEM_ADMINISTRATOR"):
        demand(
            scalar(
                c,
                "SELECT COUNT(*) n FROM app_roles WHERE role_code=:roleCode AND active_flag='Y'",
                roleCode=role,
            )
            == 1,
            f"Active profile missing: {role}.",
        )
    demand(
        scalar(c, "SELECT COUNT(*) n FROM user_sequences WHERE sequence_name='PERSON_ID_SEQ'") == 1,
        "Person ID sequence is missing.",
    )
    return skills, catalogue


def stopped(c):
    r = rows(c, "SELECT agents_enabled,notifications_enabled FROM staffing_runtime WHERE runtime_id=1")
    demand(
        len(r) == 1 and r[0] == {"agents_enabled": "N", "notifications_enabled": "N"},
        "Stop all three services, disable agents/email in SQL Developer, then retry.",
        "DEMO_SERVICES_RUNNING",
    )
    demand(
        scalar(c, "SELECT COUNT(*) n FROM agent_executions WHERE status IN ('QUEUED','RUNNING')") == 0,
        "Queued/running jobs must be completed or explicitly cancelled before loading data.",
    )


def lock_tables(c):
    # Fixed allowlist; NOWAIT prevents hanging behind a live application writer.
    for table in (
        *MUTABLE_TABLES,
        *HISTORY_TABLES,
        "STAFFING_POLICIES",
        "ELIGIBILITY_RULES",
        "LOAD_GUARDRAILS",
        "SCORING_WEIGHTS",
    ):
        execute(c, f"LOCK TABLE {table} IN EXCLUSIVE MODE NOWAIT", {})
    stopped(c)


def provision_people(c, dataset, skills, catalogue):
    # Consume the reserved numeric ID through the SAME sequence used by Add People.
    # Rollbacks may leave harmless sequence gaps; never rewind a shared sequence.
    number = scalar(c, "SELECT person_id_seq.NEXTVAL n FROM dual")
    demand(number >= 12, "Person ID sequence is behind the existing numeric roster.")
    for person in dataset.people:
        exp = [
            {
                "deliverableId": catalogue[(e.project_type, e.deliverable_name)]["deliverable_id"],
                "experienceLevel": e.experience_level,
                "contributionScope": e.contribution_scope,
                "interested": e.interested,
                "experience": e.experience,
            }
            for e in person.deliverables
        ]
        initials = "".join(n[0] for n in person.full_name.split()[:2])
        binds = dict(
            personId=person.person_id,
            fullName=person.full_name,
            jobTitle=person.job_title,
            locationName=person.location,
            weeklyHours=person.weekly_hours,
            emailAddress=person.email,
            initialsText=initials,
            batch=BATCH,
            experienceJson=json_text(exp),
        )
        execute(
            c,
            """MERGE INTO people p USING (SELECT :personId person_id FROM dual) s ON (p.person_id=s.person_id)
            WHEN MATCHED THEN UPDATE SET job_title=:jobTitle,location=:locationName,weekly_work_hours=:weeklyHours,
                email_address=NVL(p.email_address,:emailAddress),deliverable_experience_json=:experienceJson,
                skills_version=p.skills_version+1,staffing_seed_batch=:batch,updated_at=SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT(person_id,full_name,initials,job_title,location,weekly_work_hours,email_address,
                allocation_pct,active_pods,active_flag,skills_version,deliverable_experience_json,staffing_seed_batch)
                VALUES(:personId,:fullName,:initialsText,:jobTitle,:locationName,:weeklyHours,:emailAddress,
                    0,0,'Y',1,:experienceJson,:batch)""",
            binds,
            ("experienceJson",),
        )
        execute(
            c,
            "UPDATE app_user_roles SET active_flag='N' WHERE person_id=:personId AND active_flag='Y'",
            {"personId": person.person_id},
        )
        execute(
            c,
            """INSERT INTO app_user_roles(identity_subject,role_code,person_id,active_flag,effective_from,assigned_by)
            VALUES(:subjectText,:roleCode,:personId,'Y',:startDay,:batch)""",
            dict(
                subjectText="demo:d1:" + person.person_id,
                roleCode=person.role_code,
                personId=person.person_id,
                startDay=dataset.anchor,
                batch=BATCH,
            ),
        )
        for skill in person.skills:
            execute(
                c,
                """MERGE INTO person_interests p USING (SELECT :personId person_id,:skillId interest_id FROM dual) s
                ON (p.person_id=s.person_id AND p.interest_id=s.interest_id)
                WHEN MATCHED THEN UPDATE SET strength=:rating,evidence_note=:evidenceText,source=:batch,
                    interested_flag=:interestedFlag,updated_at=SYSTIMESTAMP,updated_by=:batch
                WHEN NOT MATCHED THEN INSERT(person_id,interest_id,strength,evidence_note,source,interested_flag,updated_at,updated_by)
                    VALUES(:personId,:skillId,:rating,:evidenceText,:batch,:interestedFlag,SYSTIMESTAMP,:batch)""",
                dict(
                    personId=person.person_id,
                    skillId=skills[skill.name]["interest_id"],
                    rating=skill.strength,
                    evidenceText=skill.evidence,
                    batch=BATCH,
                    interestedFlag="Y" if skill.interested else "N",
                ),
            )
    execute(
        c,
        "UPDATE interests SET derived_role_code='POD_LEAD' WHERE interest_id=:skillId",
        {"skillId": skills["Project Manager (GTM SME)"]["interest_id"]},
    )
    # Role-derived capabilities are never employee self-ratings. The original
    # Elena PM rating is preserved in the verified PERSON_INTERESTS backup.
    execute(
        c,
        """DELETE FROM person_interests WHERE interest_id IN
        (SELECT interest_id FROM interests WHERE assessment_type='ROLE_DERIVED')""",
        {},
    )


def add_event(c, person_id, title, start, end, hours, event_type, kind):
    execute(
        c,
        """MERGE INTO availability a USING (SELECT :personId person_id,:eventTitle title,:startDay starts_on,
        :endDay ends_on,:eventType event_type FROM dual) s
        ON (a.person_id=s.person_id AND a.title=s.title AND a.starts_on=s.starts_on AND a.ends_on=s.ends_on AND a.event_type=s.event_type)
        WHEN NOT MATCHED THEN INSERT(person_id,event_type,starts_on,ends_on,title,allocated_hours,capacity_kind,created_by)
            VALUES(:personId,:eventType,:startDay,:endDay,:eventTitle,:hoursValue,:capacityKind,:batch)""",
        dict(
            personId=person_id,
            eventTitle=title,
            startDay=start,
            endDay=end,
            eventType=event_type,
            hoursValue=hours,
            capacityKind=kind,
            batch=BATCH,
        ),
    )


def capacity_inputs(c, dataset, *, initial=False):
    if initial:
        for event in rows(
            c, "SELECT availability_id,event_type FROM availability WHERE capacity_kind='UNKNOWN'"
        ):
            kind = {
                "OOO": "NON_AVAILABILITY",
                "Leave": "NON_AVAILABILITY",
                "Travel": "NON_AVAILABILITY",
                "Commitment": "EXTERNAL_WORK",
            }.get(event["event_type"])
            demand(kind is not None, "An existing availability event needs manual classification.")
            execute(
                c,
                "UPDATE availability SET capacity_kind=:kindText WHERE availability_id=:eventId",
                dict(kindText=kind, eventId=event["availability_id"]),
            )
        for e in dataset.availability:
            add_event(
                c, e.person_id, e.title, e.starts_on, e.ends_on, e.hours, e.event_type, "NON_AVAILABILITY"
            )
    for person in dataset.people:
        if not initial:
            # Rebuild only this loader's recurring operational work in the new
            # window. Retained/user-entered commitments and absences are untouched.
            # This avoids stale hours or duplicate recurring work after leave edits.
            execute(
                c,
                """DELETE FROM availability WHERE person_id=:personId AND created_by=:batch
                AND title='Customer support and operational commitments' AND event_type='Commitment'
                AND capacity_kind='EXTERNAL_WORK' AND starts_on=ends_on
                AND starts_on BETWEEN :startDay AND :endDay""",
                dict(
                    personId=person.person_id,
                    batch=BATCH,
                    startDay=dataset.anchor,
                    endDay=dataset.capacity_end,
                ),
            )
        existing = rows(
            c,
            """SELECT availability_id,capacity_kind,starts_on,ends_on,allocated_hours FROM availability
            WHERE person_id=:personId AND starts_on<=:endDay AND ends_on>=:startDay""",
            personId=person.person_id,
            startDay=dataset.anchor,
            endDay=dataset.capacity_end,
        )
        base = build_days(person.weekly_hours, dataset.anchor, dataset.capacity_end, existing)
        for start in (dataset.anchor + timedelta(days=7 * i) for i in range(9)):
            week = {d: v for d, v in base.items() if start <= d <= start + timedelta(days=6)}
            for day, hours in distribute_external(week, person.external_weekly_hours).items():
                add_event(
                    c,
                    person.person_id,
                    "Customer support and operational commitments",
                    day,
                    day,
                    hours,
                    "Commitment",
                    "EXTERNAL_WORK",
                )
        events = rows(
            c,
            """SELECT availability_id,capacity_kind,starts_on,ends_on,allocated_hours FROM availability
            WHERE person_id=:personId AND starts_on<=:endDay AND ends_on>=:startDay""",
            personId=person.person_id,
            startDay=dataset.anchor,
            endDay=dataset.capacity_end,
        )
        days = build_days(person.weekly_hours, dataset.anchor, dataset.capacity_end, events)
        version = rows(
            c, "SELECT availability_version FROM people WHERE person_id=:personId", personId=person.person_id
        )[0]["availability_version"]
        refs = json_text(
            {
                "batch": BATCH,
                "synthetic": True,
                "method": "weekly_work_hours / 5 on Mon-Fri; explicit absence/external event IDs; excludes POD assignments",
                "availability_ids": [e["availability_id"] for e in events],
            }
        )
        for day, value in days.items():
            execute(
                c,
                """MERGE INTO person_capacity_days p USING (SELECT :personId person_id,:workDay work_date FROM dual) s
                ON (p.person_id=s.person_id AND p.work_date=s.work_date)
                WHEN MATCHED THEN UPDATE SET available_hours=:availableHours,external_committed_hours=:externalHours,
                    availability_version=:versionNumber,input_refs_json=:refsJson,source_version=:batch,verified_by=:batch,verified_at=SYSTIMESTAMP
                WHEN NOT MATCHED THEN INSERT(person_id,work_date,available_hours,external_committed_hours,availability_version,
                    input_refs_json,source_version,verified_by,verified_at)
                    VALUES(:personId,:workDay,:availableHours,:externalHours,:versionNumber,:refsJson,:batch,:batch,SYSTIMESTAMP)""",
                dict(
                    personId=person.person_id,
                    workDay=day,
                    availableHours=value["available"],
                    externalHours=value["external"],
                    versionNumber=version,
                    refsJson=refs,
                    batch=BATCH,
                ),
                ("refsJson",),
            )


def reconcile_requests(c, dataset):
    # Published evidence/history remains frozen. Changed ownership invalidates old pending proposals.
    execute(c, "UPDATE pod_proposals SET status='SUPERSEDED' WHERE status='READY_FOR_REVIEW'", {})
    names = {p.person_id: p.full_name for p in dataset.people}
    for i, req in enumerate(rows(c, "SELECT * FROM requests ORDER BY request_id")):
        captain = "P-009" if i % 2 == 0 else "P-010"
        source = req["request_source_person_id"] or captain
        start = (
            calendar_day(req["estimated_start_date"])
            if req["estimated_start_date"]
            else dataset.anchor + timedelta(days=7)
        )
        end = (
            calendar_day(req["estimated_completion_date"])
            if req["estimated_completion_date"]
            else start + timedelta(days=11)
        )
        if end < dataset.anchor:
            start, end = dataset.anchor + timedelta(days=7), dataset.anchor + timedelta(days=18)

        def text(value):
            return value.read() if hasattr(value, "read") else value

        objectives = (
            text(req["business_objectives"])
            or text(req.get("business_context"))
            or f"Prepare {req['deliverable'] or 'the requested materials'} to support customer understanding and sales readiness."
        )
        outcomes = (
            text(req["expected_outcomes"])
            or f"Deliver reviewed {req['deliverable'] or 'project materials'} with clear messaging and stakeholder sign-off by the agreed date."
        )
        execute(
            c,
            """UPDATE requests SET responsible_captain_id=:captainId,owner_name=:ownerName,
            request_source_person_id=:sourceId,request_source=:sourceName,estimated_start_date=:startDay,
            estimated_completion_date=:endDay,needed_by=:endDay,requested_lead_count=NVL(requested_lead_count,1),
            requested_contributor_count=NVL(requested_contributor_count,2),business_objectives=:objectivesText,
            expected_outcomes=:outcomesText,status=CASE WHEN status='STAFFED' THEN 'NEEDS_RECOMMENDATION' ELSE status END,
            updated_by=:batch,updated_at=SYSTIMESTAMP WHERE request_id=:requestId""",
            dict(
                captainId=captain,
                ownerName=names[captain],
                sourceId=source,
                sourceName=names[source],
                startDay=start,
                endDay=end,
                objectivesText=objectives,
                outcomesText=outcomes,
                batch=BATCH,
                requestId=req["request_id"],
            ),
            ("objectivesText", "outcomesText"),
        )


def baseline_policy(c, operator):
    execute(
        c,
        """INSERT INTO staffing_policies(policy_version,status,description,created_by)
        VALUES(:versionText,'DRAFT','Operator-imported synthetic baseline only; not production policy approval.',:operatorName)""",
        dict(versionText=POLICY, operatorName=operator),
    )
    for code, value in {
        "MINIMUM_STRENGTH": 3,
        "LEAD_ROLE": "POD_LEAD",
        "MEMBER_ROLES": ["POD_MEMBER", "POD_LEAD"],
        "MAX_AGENT_STEPS": 12,
    }.items():
        execute(
            c,
            "INSERT INTO eligibility_rules(policy_version,rule_code,rule_value_json) VALUES(:versionText,:ruleCode,:valueJson)",
            dict(versionText=POLICY, ruleCode=code, valueJson=json_text({"value": value})),
            ("valueJson",),
        )
    execute(
        c,
        "INSERT INTO load_guardrails(policy_version,default_weekly_hours,maximum_allocation_pct,scheduling_timezone) VALUES(:versionText,40,100,'Asia/Kolkata')",
        {"versionText": POLICY},
    )
    execute(
        c,
        "INSERT INTO scoring_weights(policy_version,skill_weight,deliverable_weight,capacity_weight,interest_weight) VALUES(:versionText,50,30,15,5)",
        {"versionText": POLICY},
    )
    execute(
        c,
        "UPDATE staffing_policies SET status='APPROVED',approved_by=:operatorName,approved_at=SYSTIMESTAMP WHERE policy_version=:versionText",
        dict(versionText=POLICY, operatorName="demo-import:" + operator),
    )


def baseline_project(c, project, catalogue, names, operator):
    from app.demo_simulation import resolve_project

    events = rows(
        c,
        "SELECT person_id,starts_on,ends_on,capacity_kind,allocated_hours FROM availability WHERE capacity_kind='NON_AVAILABILITY'",
    )
    project = resolve_project(project, events)
    d = catalogue[(project.project_type, project.deliverable_name)]
    total = sum(Decimal(str(m.hours)) for m in project.members)
    execute(
        c,
        """INSERT INTO requests(request_id,title,project_type_id,project_type,deliverable_id,deliverable,deliverables_json,
        owner_name,request_source,request_source_person_id,project_description,needed_by,estimated_start_date,estimated_completion_date,
        estimated_effort_value,estimated_effort_unit,estimated_hours,requested_lead_count,requested_contributor_count,priority,status,
        business_objectives,expected_outcomes,mapping_version,responsible_captain_id,agent_enabled,staffing_seed_batch,created_by,updated_by)
        VALUES(:requestId,:titleText,:projectTypeId,:projectName,:deliverableId,:deliverableName,:deliverablesJson,
        :captainName,:sourceName,:sourceId,:descriptionText,:endDay,:startDay,:endDay,:totalHours,'HOURS',:totalHours,1,:membersCount,:priorityText,
        'NEEDS_RECOMMENDATION',:objectivesText,:outcomesText,:mappingVersion,:captainId,'N',:batch,:batch,:batch)""",
        dict(
            requestId=project.request_id,
            titleText=project.title,
            projectTypeId=d["project_type_id"],
            projectName=d["project_name"],
            deliverableId=d["deliverable_id"],
            deliverableName=d["deliverable_name"],
            deliverablesJson=json_text(
                [{"id": d["deliverable_id"], "name": d["deliverable_name"], "note": "", "custom": False}]
            ),
            captainName=names[project.captain_id],
            sourceName=names[project.source_person_id],
            sourceId=project.source_person_id,
            descriptionText=d["project_description"],
            endDay=project.ends_on,
            startDay=project.starts_on,
            totalHours=total,
            membersCount=len(project.members) - 1,
            objectivesText=project.business_objectives,
            outcomesText=project.expected_outcomes,
            mappingVersion=d["source_version"],
            captainId=project.captain_id,
            priorityText=project.priority,
            batch=BATCH,
        ),
        ("deliverablesJson", "objectivesText", "outcomesText"),
    )
    for s in rows(
        c,
        "SELECT skill_id,skill_name FROM deliverable_skills WHERE deliverable_id=:deliverableId",
        deliverableId=d["deliverable_id"],
    ):
        execute(
            c,
            """INSERT INTO requirements(request_id,deliverable_id,interest_id,skill_name,capability_source,required_strength,
            requirement_source,source_version,mandatory_flag,created_by) VALUES(:requestId,:deliverableId,:skillId,:skillName,'MAPPED',3,:batch,:versionText,'Y',:batch)""",
            dict(
                requestId=project.request_id,
                deliverableId=d["deliverable_id"],
                skillId=s["skill_id"],
                skillName=s["skill_name"],
                batch=BATCH,
                versionText=d["source_version"],
            ),
        )
    bundle = collect_evidence(c, project.request_id, POLICY)
    pod = Proposal(
        request_id=project.request_id,
        request_revision=bundle.request.revision,
        policy_version=POLICY,
        members=tuple(
            ProposedMember(
                person_id=m.person_id,
                role=m.role,
                hours=m.hours,
                responsibilities=m.responsibilities,
                deliverable_ids=(d["deliverable_id"],),
            )
            for m in project.members
        ),
        rationale="Existing delivery plan with named owners and scheduled contributions.",
        evidence_refs=(f"request:{project.request_id}",),
    )
    issues = validate_pod(bundle.request, pod, bundle.candidates, bundle.ledgers, bundle.policy)
    demand(
        not issues, f"Baseline {project.request_id} failed validation: " + ", ".join(i.code for i in issues)
    )
    suffix = project.request_id.replace("REQ-", "")
    eid, pid, did = "BASELINE-D1-" + suffix, "D1P-" + suffix, "D1D-" + suffix
    provenance = {
        "batch": BATCH,
        "synthetic": True,
        "source": "operator_baseline_import",
        "operator": operator,
        "model_calls": 0,
    }
    execute(
        c,
        """INSERT INTO agent_executions(execution_id,request_id,request_revision,policy_version,idempotency_key,status,
        request_snapshot_json,evidence_snapshot_json,checkpoint_json,model_id,prompt_version,created_by,finished_at)
        VALUES(:executionId,:requestId,:revisionNumber,:policyVersion,:executionId,'READY_FOR_REVIEW',:requestJson,:evidenceJson,
        :checkpointJson,'NO_MODEL_BASELINE_IMPORT','baseline-import-v1',:actorText,SYSTIMESTAMP)""",
        dict(
            executionId=eid,
            requestId=project.request_id,
            revisionNumber=pod.request_revision,
            policyVersion=POLICY,
            requestJson=json_text(bundle.request),
            evidenceJson=json_text(bundle),
            checkpointJson=json_text(provenance),
            actorText="demo-import:" + operator,
        ),
        ("requestJson", "evidenceJson", "checkpointJson"),
    )
    execute(
        c,
        """INSERT INTO pod_proposals(proposal_id,request_id,proposal_version,request_revision,execution_id,policy_version,
        responsible_captain_id,starts_on,ends_on,total_hours,lead_count,member_count,rationale,evidence_refs_json,validation_json)
        VALUES(:proposalId,:requestId,1,:revisionNumber,:executionId,:policyVersion,:captainId,:startDay,:endDay,:hoursValue,1,
        :memberCount,:rationaleText,:refsJson,:validationJson)""",
        dict(
            proposalId=pid,
            requestId=project.request_id,
            revisionNumber=pod.request_revision,
            executionId=eid,
            policyVersion=POLICY,
            captainId=project.captain_id,
            startDay=project.starts_on,
            endDay=project.ends_on,
            hoursValue=total,
            memberCount=len(pod.members) - 1,
            rationaleText=pod.rationale,
            refsJson=json_text(list(pod.evidence_refs)),
            validationJson=json_text({**provenance, "issues": []}),
        ),
        ("rationaleText", "refsJson", "validationJson"),
    )
    for rank, member in enumerate(pod.members, 1):
        person = next(p for p in bundle.candidates if p.person_id == member.person_id)
        load = calculate_capacity(
            bundle.ledgers[member.person_id],
            project.starts_on,
            project.ends_on,
            spread_hours(member.hours, project.starts_on, project.ends_on),
        )
        percent = max(w.allocation_pct for w in load.weeks)
        scores = {
            **score_candidate(person, bundle.request, percent, bundle.policy),
            "projected_allocation_pct": percent,
        }
        execute(
            c,
            """INSERT INTO pod_proposal_members(proposal_id,person_id,role_in_pod,selected_flag,planned_hours,score,rank_position,
            responsibilities,deliverable_ids_json,evidence_json,factors_json,person_skills_version,person_workload_version)
            VALUES(:proposalId,:personId,:roleCode,'Y',:hoursValue,:scoreValue,:rankValue,:responsibilityText,:deliverableJson,:evidenceJson,
            :factorsJson,:skillsVersion,:workloadVersion)""",
            dict(
                proposalId=pid,
                personId=member.person_id,
                roleCode=member.role.value,
                hoursValue=member.hours,
                scoreValue=scores["score"],
                rankValue=rank,
                responsibilityText=member.responsibilities,
                deliverableJson=json_text(list(member.deliverable_ids)),
                evidenceJson=json_text(person),
                factorsJson=json_text(scores),
                skillsVersion=bundle.versions[member.person_id]["skills_version"],
                workloadVersion=bundle.versions[member.person_id]["workload_version"],
            ),
            ("deliverableJson", "evidenceJson", "factorsJson"),
        )
    execute(
        c,
        "UPDATE pod_proposals SET status='READY_FOR_REVIEW' WHERE proposal_id=:proposalId",
        {"proposalId": pid},
    )
    execute(
        c,
        """INSERT INTO approval_decisions(decision_id,proposal_id,request_id,captain_person_id,actor_subject,action_type,reason,idempotency_key)
        VALUES(:decisionId,:proposalId,:requestId,:captainId,:actorText,'APPROVED',:reasonText,:decisionId)""",
        dict(
            decisionId=did,
            proposalId=pid,
            requestId=project.request_id,
            captainId=project.captain_id,
            actorText="demo-import:" + operator,
            reasonText="Synthetic existing-project approval imported by the named operator; not an employee or LLM decision.",
        ),
    )
    execute(
        c, "UPDATE pod_proposals SET status='APPROVED' WHERE proposal_id=:proposalId", {"proposalId": pid}
    )
    for member in pod.members:
        aid = "D1A-" + suffix + "-" + member.person_id.removeprefix("P-")
        execute(
            c,
            """INSERT INTO pod_assignments(assignment_id,request_id,proposal_id,person_id,role_in_pod,decision_id,policy_version,
            starts_on,ends_on,assigned_hours) VALUES(:assignmentId,:requestId,:proposalId,:personId,:roleCode,:decisionId,:policyVersion,
            :startDay,:endDay,:hoursValue)""",
            dict(
                assignmentId=aid,
                requestId=project.request_id,
                proposalId=pid,
                personId=member.person_id,
                roleCode=member.role.value,
                decisionId=did,
                policyVersion=POLICY,
                startDay=project.starts_on,
                endDay=project.ends_on,
                hoursValue=member.hours,
            ),
        )
        for day in spread_hours(member.hours, project.starts_on, project.ends_on):
            if day.hours:
                execute(
                    c,
                    "INSERT INTO assignment_days(assignment_id,person_id,work_date,assigned_hours) VALUES(:assignmentId,:personId,:workDay,:hoursValue)",
                    dict(assignmentId=aid, personId=member.person_id, workDay=day.day, hoursValue=day.hours),
                )
    execute(
        c,
        "UPDATE requests SET status='STAFFED' WHERE request_id=:requestId",
        {"requestId": project.request_id},
    )
    execute(
        c,
        """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,correlation_id,after_state_json)
        VALUES(:auditId,'BASELINE_IMPORT',:requestId,'IMPORTED',:actorText,:batch,:afterJson)""",
        dict(
            auditId="D1-AUDIT-" + suffix,
            requestId=project.request_id,
            actorText="demo-import:" + operator,
            batch=BATCH,
            afterJson=json_text(provenance),
        ),
        ("afterJson",),
    )


def verification(c, dataset):
    """Verify live records, not the old decorative allocation_pct/active_pods fields."""
    from collections import Counter

    roster = rows(
        c,
        "SELECT person_id,full_name,job_title,location,weekly_work_hours,email_address,deliverable_experience_json FROM people WHERE active_flag='Y'",
    )
    demand(
        {p["person_id"] for p in roster} == {p.person_id for p in dataset.people},
        "Active roster differs from the prepared dataset.",
    )
    roles = rows(
        c,
        "SELECT person_id,role_code FROM app_user_roles WHERE active_flag='Y' AND effective_from<=:startDay AND (effective_to IS NULL OR effective_to>=:endDay)",
        startDay=dataset.anchor,
        endDay=dataset.capacity_end,
    )
    demand(
        Counter(r["role_code"] for r in roles)
        == Counter({"POD_CAPTAIN": 2, "POD_LEAD": 3, "POD_MEMBER": 11, "SYSTEM_ADMINISTRATOR": 1}),
        "Expected two Captains, three Leads, eleven Members and one standalone Administrator.",
    )
    demand(len({r["person_id"] for r in roles}) == 17, "An employee has conflicting active role assignments.")
    known = {p.person_id: p for p in dataset.people}
    allocations = []
    for p in roster:
        demand(
            all(p[k] for k in ("full_name", "job_title", "location", "weekly_work_hours", "email_address")),
            f"Incomplete person profile: {p['person_id']}.",
        )
        if p["person_id"] != ADMIN_ID:
            exp = document(p["deliverable_experience_json"])
            demand(
                len(exp) >= 2 and all(e.get("experience") for e in exp),
                f"Missing deliverable evidence: {p['person_id']}.",
            )
            demand(
                scalar(
                    c,
                    """SELECT COUNT(*) n FROM person_interests pi JOIN interests i ON i.interest_id=pi.interest_id
                WHERE pi.person_id=:personId AND i.assessment_type='SELF_RATED' AND TRIM(pi.evidence_note) IS NOT NULL
                AND pi.strength BETWEEN 1 AND 5""",
                    personId=p["person_id"],
                )
                >= 3,
                f"Incomplete skill evidence: {p['person_id']}.",
            )
        ledger, _ = load_capacity_ledger(c, p["person_id"], dataset.anchor, dataset.capacity_end)
        capacity = calculate_capacity(ledger, dataset.anchor, dataset.capacity_end, ())
        demand(
            not capacity.overloaded_days
            and all(w.committed_hours <= w.available_hours for w in capacity.weeks),
            f"Existing workload exceeds available time: {p['person_id']}.",
        )
        if p["person_id"] != ADMIN_ID:
            allocations.append(
                {
                    "person_id": p["person_id"],
                    "name": p["full_name"],
                    "role": known[p["person_id"]].role_code,
                    "first_week_allocation_pct": str(capacity.weeks[0].allocation_pct),
                    "assigned_projects": scalar(
                        c,
                        "SELECT COUNT(*) n FROM pod_assignments WHERE person_id=:personId AND status='CONFIRMED'",
                        personId=p["person_id"],
                    ),
                }
            )
    demand(
        scalar(c, "SELECT COUNT(*) n FROM availability WHERE capacity_kind='UNKNOWN'") == 0,
        "Unclassified availability remains.",
    )
    demand(
        scalar(
            c,
            "SELECT COUNT(*) n FROM interests WHERE interest_id='SK-001' AND assessment_type='ROLE_DERIVED' AND derived_role_code='POD_LEAD'",
        )
        == 1,
        "Project Manager is not role-derived from POD Lead.",
    )
    demand(
        scalar(
            c,
            "SELECT COUNT(*) n FROM person_interests pi JOIN interests i ON i.interest_id=pi.interest_id WHERE i.assessment_type='ROLE_DERIVED'",
        )
        == 0,
        "Role-derived capabilities must not retain employee self-ratings.",
    )
    assignments = rows(
        c,
        """SELECT a.assignment_id,a.assigned_hours,NVL(SUM(d.assigned_hours),0) day_hours
        FROM pod_assignments a LEFT JOIN assignment_days d ON d.assignment_id=a.assignment_id
        WHERE a.policy_version=:policyVersion GROUP BY a.assignment_id,a.assigned_hours""",
        policyVersion=POLICY,
    )
    demand(
        len(assignments) == sum(len(p.members) for p in dataset.projects),
        "The baseline assignment count is incomplete.",
    )
    demand(
        all(a["assigned_hours"] == a["day_hours"] for a in assignments),
        "Assignment totals and scheduled day hours disagree.",
    )
    for project in dataset.projects:
        req = rows(
            c,
            "SELECT status,business_objectives,expected_outcomes FROM requests WHERE request_id=:requestId",
            requestId=project.request_id,
        )
        demand(
            len(req) == 1 and req[0]["status"] in ("STAFFED", "CLOSED"),
            f"Baseline project {project.request_id} has an unexpected status.",
        )
        demand(
            scalar(
                c,
                "SELECT SUM(assigned_hours) n FROM pod_assignments WHERE request_id=:requestId AND status IN ('CONFIRMED','CLOSED')",
                requestId=project.request_id,
            )
            == project.total_hours,
            f"Baseline effort mismatch: {project.request_id}.",
        )
    demand(
        scalar(c, "SELECT COUNT(*) n FROM pod_assignments WHERE person_id=:personId", personId=ADMIN_ID) == 0,
        "Administrator must never be a staffing candidate.",
    )
    demand(
        scalar(c, "SELECT COUNT(*) n FROM notification_outbox WHERE status<>'DISABLED'") == 0,
        "Notification sending must remain off.",
    )
    demand(
        scalar(
            c,
            "SELECT COUNT(*) n FROM requests WHERE responsible_captain_id IS NULL OR request_source_person_id IS NULL OR estimated_start_date IS NULL OR estimated_completion_date IS NULL",
        )
        == 0,
        "Legacy requests still have missing ownership or dates.",
    )
    return {
        "verified": True,
        "employees": 16,
        "administrator_accounts": 1,
        "roles": dict(Counter(r["role_code"] for r in roles)),
        "baseline_projects": len(dataset.projects),
        "assignments": len(assignments),
        "scheduled_hours": str(sum(p.total_hours for p in dataset.projects)),
        "capacity_start": dataset.anchor.isoformat(),
        "capacity_end": dataset.capacity_end.isoformat(),
        "allocations": allocations,
        "model_calls": 0,
        "emails_sent": 0,
    }


def existing_metadata(c):
    if not scalar(
        c, "SELECT COUNT(*) n FROM user_objects WHERE object_name='AIPS_D1_STATE' AND subobject_name IS NULL"
    ):
        return None
    return owned_metadata(c)


def plan(database, today):
    from app.demo_simulation import simulate

    with database.read() as c:
        state = existing_metadata(c)
        if state and state.get("status") == "APPLIED":
            ds = build_demo_dataset(date.fromisoformat(state["anchor"]))
            return {**verification(c, ds), "already_applied": True, "writes": 0}
        ds = build_demo_dataset(today)
        skills, catalogue = preflight(c, ds)
        result = simulate(c, ds, skills, catalogue)
        return {
            **result,
            "status": "PLAN_ONLY",
            "writes": 0,
            "anchor": ds.anchor.isoformat(),
            "capacity_end": ds.capacity_end.isoformat(),
            "runtime": rows(
                c, "SELECT agents_enabled,notifications_enabled FROM staffing_runtime WHERE runtime_id=1"
            ),
            "role_mapping": [
                {"person_id": p.person_id, "name": p.full_name, "role": p.role_code} for p in ds.people
            ],
        }


def apply(database, today, operator, commit=False):
    import hashlib
    from dataclasses import asdict
    from app.demo_backup import TRACKED_TABLES
    from app.demo_simulation import simulate

    ds = build_demo_dataset(today)
    with database.read() as c:
        state = existing_metadata(c)
        if state and state.get("status") == "APPLIED":
            return {
                **verification(c, build_demo_dataset(date.fromisoformat(state["anchor"]))),
                "already_applied": True,
                "writes": 0,
            }
        stopped(c)
        skills, catalogue = preflight(c, ds)
        simulate(c, ds, skills, catalogue)  # Fail on data quality BEFORE creating backup DDL.
    signature = hashlib.sha256(
        json.dumps(asdict(ds), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    metadata = prepare(database, ds.anchor, operator, dataset_signature=signature)
    demand(
        metadata["status"] == "PREPARED",
        "This batch is not ready to load. A recovered batch cannot be reapplied.",
    )
    with database.write() as c:
        c.call_timeout = 30000
        lock_tables(c)
        demand(
            fingerprints(c) == verify_backups(c),
            "Database inputs changed after backup; inspect before retrying.",
        )
        skills, catalogue = preflight(c, ds)
        provision_people(c, ds, skills, catalogue)
        capacity_inputs(c, ds, initial=True)
        reconcile_requests(c, ds)
        baseline_policy(c, operator)
        names = {p.person_id: p.full_name for p in ds.people}
        for project in ds.projects:
            baseline_project(c, project, catalogue, names, operator)
        result = verification(c, ds)
        after = fingerprints(c, TRACKED_TABLES)
        save_state(
            c,
            "migration",
            {**metadata, "status": "APPLIED", "after": after, "summary": result, "batch": BATCH},
        )
        if not commit:
            c.rollback()
        return {
            **result,
            "committed": commit,
            "business_dml_rolled_back": not commit,
            "backups_preserved": True,
            "note": "No worker, model call, persona UI or email was enabled.",
        }


def refresh(database, today, operator, commit=False):
    ds = build_demo_dataset(today)
    with database.write() as c:
        lock_tables(c)
        state = existing_metadata(c)
        demand(state and state.get("status") == "APPLIED", "Load Phase 1 before refreshing capacity.")
        # No roster/skill/project reseeding. Future manual edits remain authoritative.
        people = {p["person_id"]: p for p in rows(c, "SELECT person_id,weekly_work_hours FROM people")}
        from dataclasses import replace

        ds = replace(
            ds,
            people=tuple(
                replace(p, weekly_hours=Decimal(str(people[p.person_id]["weekly_work_hours"])))
                for p in ds.people
            ),
        )
        capacity_inputs(c, ds)
        for p in ds.people:
            ledger, _ = load_capacity_ledger(c, p.person_id, ds.anchor, ds.capacity_end)
            capacity = calculate_capacity(ledger, ds.anchor, ds.capacity_end, ())
            demand(
                not capacity.overloaded_days
                and all(w.committed_hours <= w.available_hours for w in capacity.weeks),
                f"Capacity conflicts for {p.person_id}; resolve dated work/absence before refreshing.",
            )
        execute(
            c,
            """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,correlation_id,after_state_json)
            VALUES(:auditId,'CAPACITY_INPUTS',:batch,'REFRESHED',:operatorName,:batch,:afterJson)""",
            dict(
                auditId="D1-REFRESH-" + datetime.now().strftime("%Y%m%d%H%M%S%f"),
                batch=BATCH,
                operatorName=operator,
                afterJson=json_text({"start": ds.anchor.isoformat(), "end": ds.capacity_end.isoformat()}),
            ),
            ("afterJson",),
        )
        # Recovery is deliberately disabled after any committed refresh/user edits.
        # Never reset that boundary over intervening changes.
        save_state(
            c, "last_refresh", {"anchor": ds.anchor.isoformat(), "operator": operator, "committed": commit}
        )
        if not commit:
            c.rollback()
        return {
            "committed": commit,
            "capacity_start": ds.anchor.isoformat(),
            "capacity_end": ds.capacity_end.isoformat(),
            "people": len(ds.people),
            "model_calls": 0,
        }


def recover(database, operator, commit=False):
    """Logical undo before further use. Keep immutable import/decision/audit history."""
    from app.demo_backup import BACKUP_TABLES, TRACKED_TABLES
    from uuid import uuid4

    with database.write() as c:
        lock_tables(c)
        state = existing_metadata(c)
        demand(
            state and state.get("status") == "APPLIED", "No applied Phase-1 dataset is available to recover."
        )
        verify_backups(c)
        demand(
            fingerprints(c, TRACKED_TABLES) == state["after"],
            "The application has changed data after loading. Recovery stopped to preserve it; review a selective recovery plan.",
        )
        execute(
            c,
            "UPDATE pod_assignments SET status='CANCELLED',closed_at=SYSTIMESTAMP,close_reason='Operator recovery of synthetic baseline import' WHERE policy_version=:policyVersion AND status='CONFIRMED'",
            {"policyVersion": POLICY},
        )
        execute(c, "UPDATE requests SET status='CLOSED' WHERE staffing_seed_batch=:batch", {"batch": BATCH})
        keys = {
            "PEOPLE": ("PERSON_ID",),
            "PERSON_INTERESTS": ("PERSON_ID", "INTEREST_ID"),
            "APP_USER_ROLES": ("IDENTITY_SUBJECT", "ROLE_CODE"),
            "AVAILABILITY": ("AVAILABILITY_ID",),
            "REQUESTS": ("REQUEST_ID",),
            "REQUIREMENTS": ("REQUIREMENT_ID",),
            "PERSON_CAPACITY_DAYS": ("PERSON_ID", "WORK_DATE"),
            "STAFFING_RUNTIME": ("RUNTIME_ID",),
            "INTERESTS": ("INTEREST_ID",),
        }
        # Remove only new mutable input rows. Baseline requests and all final history stay.
        for table in ("PERSON_INTERESTS", "APP_USER_ROLES", "AVAILABILITY", "PERSON_CAPACITY_DAYS"):
            match = " AND ".join(f"b.{k}=t.{k}" for k in keys[table])
            execute(
                c,
                f"DELETE FROM {table} t WHERE NOT EXISTS (SELECT 1 FROM {BACKUP_TABLES[table]} b WHERE {match})",
                {},
            )
        for table in (
            "INTERESTS",
            "PEOPLE",
            "PERSON_INTERESTS",
            "APP_USER_ROLES",
            "AVAILABILITY",
            "REQUESTS",
            "PERSON_CAPACITY_DAYS",
            "STAFFING_RUNTIME",
        ):
            columns = [
                r["column_name"]
                for r in rows(
                    c,
                    "SELECT column_name FROM user_tab_columns WHERE table_name=:tableName ORDER BY column_id",
                    tableName=table,
                )
            ]
            if table == "PERSON_INTERESTS":
                # The old role-derived PM self-rating was intentionally removed
                # during apply. UPDATE alone cannot restore a deleted original.
                import re

                demand(
                    all(re.fullmatch(r"[A-Z][A-Z0-9_]*", k) for k in columns), "Unexpected column identifier."
                )
                match = " AND ".join(f"b.{k}=t.{k}" for k in keys[table])
                execute(
                    c,
                    f"INSERT INTO {table} ({','.join(columns)}) SELECT {','.join('b.' + k for k in columns)} FROM {BACKUP_TABLES[table]} b WHERE NOT EXISTS (SELECT 1 FROM {table} t WHERE {match})",
                    {},
                )
            columns = [
                k
                for k in columns
                if k not in keys[table]
                and k
                not in ("SKILLS_VERSION", "AVAILABILITY_VERSION", "WORKLOAD_VERSION", "REQUEST_REVISION")
            ]
            # Names come from a verified fixed-table schema, but validate identifiers too.
            import re

            demand(all(re.fullmatch(r"[A-Z][A-Z0-9_]*", k) for k in columns), "Unexpected column identifier.")
            match = " AND ".join(f"b.{k}=t.{k}" for k in keys[table])
            execute(
                c,
                f"UPDATE {table} t SET ({','.join(columns)})=(SELECT {','.join('b.' + k for k in columns)} FROM {BACKUP_TABLES[table]} b WHERE {match}) WHERE EXISTS (SELECT 1 FROM {BACKUP_TABLES[table]} b WHERE {match})",
                {},
            )
        execute(c, "UPDATE people SET active_flag='N' WHERE person_id=:personId", {"personId": ADMIN_ID})
        execute(c, "UPDATE people SET skills_version=skills_version+1", {})
        execute(
            c,
            "UPDATE person_capacity_days d SET availability_version=(SELECT p.availability_version FROM people p WHERE p.person_id=d.person_id)",
            {},
        )
        execute(
            c,
            """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,correlation_id,reason)
            VALUES(:auditId,'DEMO_DATA',:batch,'RECOVERED',:operatorName,:batch,'Original mutable inputs restored; imported final history retained and cancelled.')""",
            dict(auditId=uuid4().hex, batch=BATCH, operatorName=operator),
        )
        save_state(c, "migration", {**state, "status": "RECOVERED", "recovered_by": operator})
        if not commit:
            c.rollback()
        return {
            "recovered": commit,
            "rehearsal": not commit,
            "history_retained": True,
            "backups_preserved": True,
            "services_remain_disabled": True,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "verify", "refresh", "recover"))
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--operator", default="")
    parser.add_argument(
        "--anchor",
        type=date.fromisoformat,
        help="Date in the desired first week; defaults to today in Asia/Kolkata.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Commit reviewed demonstration DML; without this flag apply/refresh/recover roll back.",
    )
    parser.add_argument(
        "--services-stopped", action="store_true", help="Confirm Next.js, API and worker writers are stopped."
    )
    args = parser.parse_args()
    modifying = args.action in ("apply", "refresh", "recover")
    if modifying and (not args.services_stopped or not args.operator.strip() or len(args.operator) > 100):
        parser.error("Provide --services-stopped and --operator YOUR_NAME after stopping all writers.")
    if args.commit and not modifying:
        parser.error("--commit is only for apply, refresh or recover.")
    from app.config import Settings
    from app.database import OracleDatabase

    settings = Settings(_env_file=args.env_file)
    demand(settings.backend_env != "production", "Demonstration loading is prohibited in production.")
    db = OracleDatabase(settings)
    today = args.anchor or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    try:
        if args.action == "plan":
            result = plan(db, today)
        elif args.action == "verify":
            with db.read() as c:
                state = existing_metadata(c)
                demand(state and state.get("status") == "APPLIED", "Phase 1 has not been applied.")
                last = read_state(c, "last_refresh")
                ds = build_demo_dataset(date.fromisoformat(last["anchor"] if last else state["anchor"]))
                result = {**verification(c, ds), "writes": 0}
        elif args.action == "apply":
            result = apply(db, today, args.operator, args.commit)
        elif args.action == "refresh":
            result = refresh(db, today, args.operator, args.commit)
        else:
            result = recover(db, args.operator, args.commit)
        print(json.dumps(result, default=str, indent=2))
    except ServiceError as error:
        print(
            json.dumps(
                {
                    "error": error.code,
                    "message": error.message,
                    "business_dml_status": "not_confirmed"
                    if error.code == "DATABASE_UNAVAILABLE"
                    else "not_applied_or_rolled_back",
                    "next_step": "Run verify and inspect the migration state before retrying after a connection failure.",
                    "backups_preserved": True,
                }
            )
        )
        raise SystemExit(1) from None
    except Exception as error:
        cause = error.__cause__
        number = getattr(error, "code", None) or (
            getattr(getattr(cause, "args", (None,))[0], "code", None) if cause else None
        )
        print(
            json.dumps(
                {
                    "error": "DEMO_OPERATION_FAILED",
                    "type": type(error).__name__,
                    "oracle_code": number,
                    "message": "Operation did not report success. Keep backup tables, inspect migration state and resolve the error before retrying.",
                }
            )
        )
        raise SystemExit(1) from None
    finally:
        db.close()


if __name__ == "__main__":
    main()
