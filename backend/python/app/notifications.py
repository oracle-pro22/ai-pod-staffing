"""Prepare transactional email intents. Deliberately contains NO delivery implementation."""
import re
from uuid import uuid4

from app.execution_store import execute
from app.planning import json_text
from app.storage import rows


def prepare_assignment_notice(connection, decision_id, proposal_id, request_id, member, assignment_id):
    records = rows(connection, "SELECT email_address FROM people WHERE person_id=:personId", personId=member.person_id)
    email = str(records[0].get("email_address") or "").strip() if records else ""
    valid = bool(len(email) <= 320 and re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email))
    # Never mark pending, even if a runtime notification flag is accidentally enabled.
    execute(connection, """INSERT INTO notification_outbox(notification_id,decision_id,proposal_id,request_id,
        recipient_person_id,recipient_email,deduplication_key,payload_json,status,last_error_code)
        VALUES(:noticeId,:decisionId,:proposalId,:requestId,:personId,:emailAddress,:dedupKey,:payloadJson,'DISABLED',:errorCode)""",
        {"noticeId": uuid4().hex, "decisionId": decision_id, "proposalId": proposal_id, "requestId": request_id,
         "personId": member.person_id, "emailAddress": email if valid else None,
         "dedupKey": f"{decision_id}:{member.person_id}:POD_ASSIGNED",
         "payloadJson": json_text({"template_version": 1, "assignment_id": assignment_id, "request_id": request_id,
                                   "role_in_pod": member.role.value, "assigned_hours": str(member.hours)}),
         "errorCode": None if valid else "RECIPIENT_EMAIL_REQUIRED"}, ("payloadJson",))
