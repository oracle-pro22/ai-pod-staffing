"""Load minimum staffing evidence from a single read-consistent Oracle transaction."""
from app.contracts import Candidate
from app.errors import ServiceError
from app.planning import EvidenceBundle, json_text
from app.storage import calendar_day, document, load_capacity_ledger, load_policy, load_request_snapshot, rows


def collect_evidence(connection, request_id, policy_version, max_people=60):
    request = load_request_snapshot(connection, request_id)
    policy = load_policy(connection, policy_version)
    if any(r.mandatory and r.assessment_type == "ROLE_DERIVED" and not r.derived_role_code for r in request.requirements):
        raise ServiceError("NEEDS_INFORMATION", "A mandatory role-derived capability needs an approved role mapping.", 422)
    content = rows(connection, """SELECT project_description,business_objectives,expected_outcomes,project_type_id
        FROM requests WHERE request_id=:requestId""", requestId=request_id)[0]
    context = {}
    for key in ("project_description", "business_objectives", "expected_outcomes"):
        value = content[key]
        context[key] = (value.read() if hasattr(value, "read") else value) or ""
    custom_preferences = rows(connection, """SELECT custom_capability_name FROM requirements
        WHERE request_id=:requestId AND capability_source='CUSTOM' AND mandatory_flag='N'
        ORDER BY display_order,requirement_id""", requestId=request_id)
    context['request_specific_preferences'] = ', '.join(row['custom_capability_name'] for row in custom_preferences)
    catalogue = {}
    for deliverable_id in request.deliverable_ids:
        if deliverable_id in request.custom_deliverables:
            catalogue[deliverable_id] = {
                'deliverable_id': deliverable_id,
                'deliverable_name': request.custom_deliverables[deliverable_id],
                'project_type_id': content['project_type_id'],
                'customer_note': 'Request-specific deliverable; no catalogue delivery history is assumed.',
                'request_scoped': True,
                'mapped_capabilities': [
                    {'skill_id': item.skill_id, 'interest_name': item.skill_id,
                     'assessment_type': item.assessment_type, 'derived_role_code': item.derived_role_code}
                    for item in request.requirements
                ],
            }
            continue
        found = rows(connection, """SELECT deliverable_id,deliverable_name,project_type_id,customer_note
            FROM deliverables WHERE deliverable_id=:deliverableId AND active_flag='Y'""", deliverableId=deliverable_id)
        if len(found) != 1 or found[0]["project_type_id"] != content["project_type_id"]:
            raise ServiceError("NEEDS_INFORMATION", "A deliverable is retired, missing or belongs to another project type.", 422)
        skills = rows(connection, """SELECT ds.skill_id,i.interest_name,i.assessment_type,i.derived_role_code
            FROM deliverable_skills ds JOIN interests i ON i.interest_id=ds.skill_id
            WHERE ds.deliverable_id=:deliverableId ORDER BY ds.skill_id""", deliverableId=deliverable_id)
        catalogue[deliverable_id] = {**found[0], "mapped_capabilities": skills}
    # Project requirements remain authoritative; catalogue defaults are context, not silent request edits.
    found_people = rows(connection, """SELECT p.person_id,p.full_name,p.skills_version,p.workload_version,
        p.availability_version,p.deliverable_experience_json FROM people p
        WHERE p.active_flag='Y'
          AND NOT EXISTS (SELECT 1 FROM roster_onboarding o WHERE o.person_id=p.person_id AND o.status NOT IN ('COMPLETE','REVIEW'))
          AND EXISTS (SELECT 1 FROM app_user_roles ur JOIN app_roles ar ON ar.role_code=ur.role_code
          JOIN app_accounts a ON a.person_id=ur.person_id AND a.identity_subject=ur.identity_subject AND a.active_flag='Y'
          WHERE ur.person_id=p.person_id AND ur.active_flag='Y' AND ar.active_flag='Y'
          AND ur.role_code IN ('POD_LEAD','POD_MEMBER') AND ur.effective_from<=:startDay
          AND (ur.effective_to IS NULL OR ur.effective_to>=:endDay)) ORDER BY p.person_id
    """, startDay=request.starts_on, endDay=request.ends_on)
    if len(found_people) > max_people:
        raise ServiceError("CANDIDATE_LIMIT", "Candidate pool exceeds this release's configured search bound; narrow the approved scope.", 409)
    candidates, ledgers, versions, names, exclusions = [], {}, {}, {}, {}
    requested_skills = {item.skill_id for item in request.requirements}
    for person in found_people:
        person_id = person["person_id"]
        role_rows = rows(connection, """SELECT DISTINCT ur.role_code,ur.effective_from,ur.effective_to
            FROM app_user_roles ur JOIN app_roles ar ON ar.role_code=ur.role_code
            JOIN app_accounts a ON a.person_id=ur.person_id AND a.identity_subject=ur.identity_subject AND a.active_flag='Y'
            WHERE ur.person_id=:personId AND ur.active_flag='Y' AND ar.active_flag='Y'
            ORDER BY ur.role_code,ur.effective_from""", personId=person_id)
        skill_rows = rows(connection, """SELECT pi.interest_id,pi.strength,pi.interested_flag,pi.evidence_note
            FROM person_interests pi JOIN interests i ON i.interest_id=pi.interest_id
            WHERE pi.person_id=:personId AND i.assessment_type='SELF_RATED' ORDER BY pi.interest_id""", personId=person_id)
        try:
            experience = document(person["deliverable_experience_json"]) if person["deliverable_experience_json"] else []
            if not isinstance(experience, list):
                raise ValueError("Malformed deliverable experience")
            candidate = Candidate(person_id=person_id, active=True,
                roles=[{"code": r["role_code"], "starts_on": calendar_day(r["effective_from"]),
                        "ends_on": calendar_day(r["effective_to"]) if r["effective_to"] else None} for r in role_rows],
                skills=[{"skill_id": r["interest_id"], "strength": r["strength"], "interested": r["interested_flag"] == "Y",
                         "evidence": r["evidence_note"] or ""} for r in skill_rows if r["interest_id"] in requested_skills],
                deliverables=[{"deliverable_id": r["deliverableId"], "experience_level": r["experienceLevel"],
                    "contribution_scope": r["contributionScope"], "interested": r["interested"], "experience": r["experience"]}
                    for r in experience if r["deliverableId"] in request.deliverable_ids])
        except (KeyError, TypeError, ValueError) as error:
            raise ServiceError("INVALID_EVIDENCE", "A candidate's saved evidence needs correction before staffing.", 409) from error
        candidates.append(candidate)
        names[person_id] = person["full_name"]
        versions[person_id] = {key: person[key] for key in ("skills_version", "workload_version", "availability_version")}
        try:
            ledgers[person_id], _ = load_capacity_ledger(connection, person_id, request.starts_on, request.ends_on)
        except ServiceError as error:
            if error.code not in ("CAPACITY_UNKNOWN", "CAPACITY_STALE"):
                raise
            exclusions[person_id] = error.code
    feedback = rows(connection, """SELECT decision_id,proposal_id,reason FROM approval_decisions
        WHERE request_id=:requestId AND action_type='REJECTED' ORDER BY decided_at DESC FETCH FIRST 5 ROWS ONLY""", requestId=request_id)
    bundle = EvidenceBundle(request=request, policy=policy, candidates=candidates, ledgers=ledgers,
                            versions=versions, names=names, context=context, catalogue=catalogue,
                            feedback=feedback, exclusions=exclusions)
    if len(json_text(bundle).encode("utf-8")) > 180000:
        raise ServiceError("EVIDENCE_LIMIT", "Evidence exceeds the bounded agent context; review the input scope.", 409)
    return bundle
