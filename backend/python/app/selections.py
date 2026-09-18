"""Captain-only, append-only selection previews. No OCI calls or reservations.

All mutations serialize on the request after the active-policy control lock.
Client sends one advertised replacement, never hours, scores or override flags.
"""
import hashlib
import json
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.alternatives import Alternatives, exact_team, replacement_options, selected_ids
from app.contracts import Contract, EntityId, PodRole
from app.engine_version import ENGINE_VERSION
from app.errors import ServiceError
from app.evidence import collect_evidence
from app.execution_store import execute
from app.planning import PlanOption, json_text
from app.policy_admin import require_current_policy
from app.storage import document, rows


class SelectionUpdate(Contract):
    revision: int = Field(ge=0, strict=True)
    person_id: EntityId | None = None
    replaces: EntityId | None = None
    role: PodRole | None = None
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")

    @model_validator(mode="after")
    def replacement_or_refresh(self):
        fields = (self.person_id, self.replaces, self.role)
        if any(fields) and not all(fields):
            raise ValueError("Supply a complete replacement or refresh the selected team")
        return self


class ReviewSnapshot(Contract):
    engine_version: str = ENGINE_VERSION
    selected: PlanOption
    alternatives: Alternatives
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    names: dict[str, str]
    sources: dict[str, str]
    rationale: str
    as_of: date | None = None
    active_pods: dict[str, int] = Field(default_factory=dict)


def evidence_hash(bundle):
    value = bundle.model_dump(mode="json")
    value["candidates"] = sorted(value["candidates"], key=lambda p: p["person_id"])
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def snapshot(bundle, option, original, limit, connection=None):
    from app.agents.grounding import grounded_plan_rationale
    original_slots = {(m.person_id, m.role) for m in original.proposal.members}
    today, active_pods = None, {}
    if connection is not None:
        today = datetime.now(ZoneInfo(bundle.policy.scheduling_timezone)).date()
        counts = rows(connection, """SELECT person_id,COUNT(DISTINCT request_id) AS total FROM pod_assignments
            WHERE status='CONFIRMED' AND starts_on<=:todayDay AND ends_on>=:todayDay GROUP BY person_id""", todayDay=today)
        totals = {row['person_id']: int(row['total']) for row in counts}
        active_pods = {pid: totals.get(pid, 0) for pid in bundle.names}
    return ReviewSnapshot(selected=option, alternatives=replacement_options(bundle, option, limit), as_of=today, active_pods=active_pods,
        evidence_hash=evidence_hash(bundle), names=bundle.names,
        sources={m.person_id: "RECOMMENDED" if (m.person_id, m.role) in original_slots else "ALTERNATIVE"
                 for m in option.proposal.members}, rationale=grounded_plan_rationale(bundle, option.proposal, option.scores))


def save_initial_review(connection, proposal_id, bundle, option, limit):
    review = snapshot(bundle, option, option, limit, connection)
    execute(connection, "INSERT INTO mvp_p2_reviews(proposal_id,review_json) VALUES(:proposalId,:reviewJson)",
            {"proposalId": proposal_id, "reviewJson": json_text(review)}, ("reviewJson",))


def member_view(member, factors, review):
    return {"person_id": member.person_id, "full_name": review.names.get(member.person_id, member.person_id),
            "role_in_pod": member.role.value, "planned_hours": member.hours, "responsibilities": member.responsibilities,
            "deliverable_ids": member.deliverable_ids, "score": factors["score"],
            "factors": factors, "source": review.sources.get(member.person_id, "ALTERNATIVE"),
            "active_pods": review.active_pods.get(member.person_id), "active_pods_as_of": review.as_of}


def review_view(original, review, revision=0, selection_id=None):
    return {"revision": revision, "selection_id": selection_id, "rationale": review.rationale,
            "members": [member_view(m, review.selected.scores[m.person_id], review) for m in review.selected.proposal.members],
            "original_members": [member_view(m, original.selected.scores[m.person_id], original) for m in original.selected.proposal.members],
            "alternatives": [{"replaces": r.replaces, "role": r.role.value,
                              "member": member_view(r.member, r.factors, review)}
                             for r in review.alternatives.replacements],
            "notes": review.alternatives.notes, "search_exhaustive": review.alternatives.exhaustive,
            "reserves_capacity": False}


def load_review(connection, proposal_id):
    initial = rows(connection, "SELECT review_json FROM mvp_p2_reviews WHERE proposal_id=:proposalId", proposalId=proposal_id)
    if not initial:
        return None
    original = ReviewSnapshot.model_validate(document(initial[0]["review_json"]))
    drafts = rows(connection, """SELECT selection_id,revision,review_json FROM mvp_p2_selections
        WHERE proposal_id=:proposalId ORDER BY revision DESC FETCH FIRST 1 ROW ONLY""", proposalId=proposal_id)
    latest = drafts[0] if drafts else None
    review = ReviewSnapshot.model_validate(document(latest["review_json"])) if latest else original
    if original.engine_version != ENGINE_VERSION or review.engine_version != ENGINE_VERSION:
        raise ServiceError("SELECTION_VERSION", "Saved selection uses an older engine. Re-run fitment.", 409)
    return original, review, latest


def attach_review(connection, record):
    # Existing pre-upgrade proposals remain readable; new runs get selections.
    loaded = load_review(connection, record["proposal_id"])
    if loaded:
        original, review, latest = loaded
        record["selection_review"] = review_view(original, review, latest["revision"] if latest else 0,
                                                  latest["selection_id"] if latest else None)


class SelectionStore:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def update(self, actor, proposal_id, change):
        from app.decisions import DecisionStore
        actor.require("AI_FITMENT", "approve", "POD_CAPTAIN")
        digest = hashlib.sha256(f"{actor.subject}|{change.idempotency_key}".encode()).hexdigest()
        body_hash = hashlib.sha256(json_text(change).encode()).hexdigest()
        with self.database.write() as connection:
            initial = rows(connection, "SELECT request_id,policy_version FROM pod_proposals WHERE proposal_id=:proposalId", proposalId=proposal_id)
            if not initial:
                raise ServiceError("PROPOSAL_NOT_FOUND", "Proposal not found.", 404)
            require_current_policy(connection, initial[0]["policy_version"], lock=True)
            request = rows(connection, "SELECT request_revision,responsible_captain_id,status FROM requests WHERE request_id=:requestId FOR UPDATE WAIT 5",
                           requestId=initial[0]["request_id"])[0]
            DecisionStore.authorize(connection, actor, request["responsible_captain_id"])
            prior = rows(connection, "SELECT proposal_id,body_hash FROM mvp_p2_selections WHERE idempotency_key=:idemKey", idemKey=digest)
            if prior:
                if prior[0]["proposal_id"] != proposal_id or prior[0]["body_hash"] != body_hash:
                    raise ServiceError("IDEMPOTENCY_CONFLICT", "This selection key was used for another change.", 409)
                loaded = load_review(connection, proposal_id)
                return review_view(loaded[0], loaded[1], loaded[2]["revision"], loaded[2]["selection_id"])
            proposal = rows(connection, "SELECT * FROM pod_proposals WHERE proposal_id=:proposalId", proposalId=proposal_id)[0]
            from app.manual_store import pending_manual
            if pending_manual(connection, initial[0]['request_id'], request['request_revision']):
                raise ServiceError('MANUAL_DRAFT_ACTIVE', 'Review or discard the manual draft before changing normal alternatives.', 409)
            if (proposal["status"] != "READY_FOR_REVIEW" or proposal["request_revision"] != request["request_revision"]
                or request["status"] not in ("NEEDS_RECOMMENDATION", "IN_REVIEW")):
                raise ServiceError("STALE_PROPOSAL", "Proposal is no longer current. Refresh the review.", 409)
            loaded = load_review(connection, proposal_id)
            if not loaded:
                raise ServiceError("SELECTION_UNAVAILABLE", "Re-run fitment to generate selectable alternatives.", 409)
            original, previous, latest = loaded
            if change.revision != (latest["revision"] if latest else 0):
                raise ServiceError("STALE_SELECTION", "The selection changed in another tab. Refresh before choosing again.", 409)
            leads, members = selected_ids(previous.selected)
            if change.person_id:
                advertised = next((r for r in previous.alternatives.replacements
                    if (r.person_id, r.replaces, r.role) == (change.person_id, change.replaces, change.role)), None)
                if advertised is None:
                    raise ServiceError("INVALID_SELECTION", "Choose a currently offered replacement; manual override is not enabled.", 409)
                if advertised.role == PodRole.LEAD:
                    leads = tuple(advertised.person_id if pid == advertised.replaces else pid for pid in leads)
                else:
                    members = tuple(advertised.person_id if pid == advertised.replaces else pid for pid in members)
            for pid in sorted(set((*leads, *members))):
                rows(connection, "SELECT person_id FROM people WHERE person_id=:personId FOR UPDATE WAIT 5", personId=pid)
            fresh = collect_evidence(connection, initial[0]["request_id"], initial[0]["policy_version"], self.settings.staffing_max_candidates)
            # Reuse current evidence only; a draft never loosens the normal rules.
            option = exact_team(fresh, leads, members)
            current = snapshot(fresh, option, original.selected, self.settings.staffing_search_limit, connection)
            selection_id = "SD" + uuid4().hex[:28]
            revision = change.revision + 1
            execute(connection, """INSERT INTO mvp_p2_selections(selection_id,proposal_id,revision,actor_subject,
                idempotency_key,body_hash,review_json) VALUES(:selectionId,:proposalId,:revision,:actorSubject,:idemKey,:bodyHash,:reviewJson)""",
                {"selectionId": selection_id, "proposalId": proposal_id, "revision": revision, "actorSubject": actor.subject,
                 "idemKey": digest, "bodyHash": body_hash, "reviewJson": json_text(current)}, ("reviewJson",))
            audit_id = uuid4().hex
            execute(connection, """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,
                correlation_id,after_state_json)
                VALUES(:auditId,'POD_SELECTION',:selectionId,'PREVIEWED',:actorSubject,:auditId,:afterJson)""",
                {"auditId": audit_id, "selectionId": selection_id, "actorSubject": actor.subject,
                 "afterJson": json_text({"proposal_id": proposal_id, "revision": revision, "sources": current.sources,
                                         "reserves_capacity": False})}, ("afterJson",))
            return review_view(original, current, revision, selection_id)


def selection_for_approval(connection, proposal, selection_id, fresh):
    """Runs under decision transaction locks. No writes until preview matches."""
    loaded = load_review(connection, proposal["proposal_id"])
    if not loaded:
        if selection_id:
            raise ServiceError("INVALID_SELECTION", "Selection does not belong to this proposal.", 409)
        return None
    original, current, latest = loaded
    if selection_id != (latest["selection_id"] if latest else None):
        raise ServiceError("STALE_SELECTION", "Review the latest saved selection before approval.", 409)
    if current.evidence_hash != evidence_hash(fresh):
        raise ServiceError("SELECTION_REFRESH_REQUIRED", "Evidence or workload changed. Recalculate the selected POD, review the new figures and approve again.", 409)
    option = exact_team(fresh, *selected_ids(current.selected))
    if option.model_dump(mode="json") != current.selected.model_dump(mode="json"):
        raise ServiceError("SELECTION_REFRESH_REQUIRED", "The selected schedule changed. Recalculate and review before approval.", 409)
    return current if latest else None
