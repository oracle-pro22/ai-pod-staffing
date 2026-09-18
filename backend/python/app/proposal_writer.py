"""Publish a validated snapshot inside a caller-owned, locked transaction."""
from decimal import Decimal
from uuid import uuid4

from app.execution_store import execute
from app.planning import json_text


def write_proposal(connection, bundle, option, execution_id, validation, rationale, *, manual=False):
    from app.storage import rows
    request = bundle.request
    version = rows(connection, "SELECT NVL(MAX(proposal_version),0)+1 AS next_version FROM pod_proposals WHERE request_id=:requestId",
                   requestId=request.request_id)[0]["next_version"]
    proposal_id = "PP" + uuid4().hex[:28]
    execute(connection, "UPDATE pod_proposals SET status='SUPERSEDED' WHERE request_id=:requestId AND status='READY_FOR_REVIEW'",
            {"requestId": request.request_id})
    execute(connection, """INSERT INTO pod_proposals(proposal_id,request_id,proposal_version,request_revision,execution_id,policy_version,
        responsible_captain_id,starts_on,ends_on,total_hours,lead_count,member_count,rationale,evidence_refs_json,validation_json,origin_type)
        VALUES(:proposalId,:requestId,:proposalVersion,:requestRevision,:executionId,:policyVersion,:captainId,
        :startDay,:endDay,:totalHours,:leadCount,:memberCount,:rationaleText,:referencesJson,:validationJson,:originType)""",
        {"proposalId": proposal_id, "requestId": request.request_id, "proposalVersion": version,
         "requestRevision": request.revision, "executionId": execution_id, "policyVersion": bundle.policy.version,
         "captainId": request.responsible_captain_id, "startDay": request.starts_on, "endDay": request.ends_on,
         "totalHours": request.total_hours, "leadCount": request.lead_count, "memberCount": request.member_count,
         "rationaleText": rationale, "referencesJson": json_text(list(option.proposal.evidence_refs)),
         "validationJson": json_text(validation), "originType": "MANUAL" if manual else "AGENT"}, ("rationaleText", "referencesJson", "validationJson"))
    for rank, member in enumerate(option.proposal.members, 1):
        person = next(p for p in bundle.candidates if p.person_id == member.person_id)
        execute(connection, """INSERT INTO pod_proposal_members(proposal_id,person_id,role_in_pod,selected_flag,planned_hours,score,
            rank_position,responsibilities,deliverable_ids_json,evidence_json,factors_json,person_skills_version,person_workload_version,manual_flag)
            VALUES(:proposalId,:personId,:podRole,'Y',:plannedHours,:scoreValue,:rankPosition,:responsibilities,
            :deliverablesJson,:evidenceJson,:factorsJson,:skillsVersion,:workloadVersion,:manualFlag)""",
            {"proposalId": proposal_id, "personId": member.person_id, "podRole": member.role.value, "plannedHours": member.hours,
             "scoreValue": None if option.scores[member.person_id]["score"] is None else Decimal(str(option.scores[member.person_id]["score"])), "rankPosition": rank,
             "manualFlag": "Y" if manual and member.person_id in validation.get("manual_ids", ()) else "N",
             "responsibilities": member.responsibilities, "deliverablesJson": json_text(list(member.deliverable_ids)),
             "evidenceJson": json_text(person), "factorsJson": json_text(option.scores[member.person_id]),
             "skillsVersion": bundle.versions[member.person_id]["skills_version"],
             "workloadVersion": bundle.versions[member.person_id]["workload_version"]},
            ("deliverablesJson", "evidenceJson", "factorsJson"))
    execute(connection, "UPDATE pod_proposals SET status='READY_FOR_REVIEW' WHERE proposal_id=:proposalId", {"proposalId": proposal_id})
    return proposal_id, version
