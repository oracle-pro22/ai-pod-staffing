"""Offline rule tests: only Pydantic is required; no database or model calls."""
import unittest
from datetime import date
from decimal import Decimal as D

from pydantic import ValidationError

from app.capacity import CapacityLedger, DailyHours, calculate_capacity, spread_hours
from app.contracts import (
    Candidate, CaptainDecision, Proposal,
    ProposedMember, RequestSnapshot, Requirement,
)
from app.errors import ServiceError
from app.policy import DEFAULT_POLICY, StaffingPolicy, Weights
from app.rules import score_candidate, validate_pod

MON = date(2026, 9, 14)
FRI = date(2026, 9, 18)


def request(**overrides):
    return RequestSnapshot.model_validate({
        "request_id": "REQ-1046", "revision": 1, "responsible_captain_id": "P-010",
        "title": "Launch communication", "starts_on": MON, "ends_on": FRI,
        "total_hours": 20, "member_count": 0, "deliverable_ids": ["DEL-001"],
        "requirements": [{"skill_id": "INT-001"}], **overrides,
    })


def person(**overrides):
    return Candidate.model_validate({
        "person_id": "P-006", "active": True,
        "roles": [{"code": "POD_LEAD", "starts_on": MON}],
        "skills": [{"skill_id": "INT-001", "strength": 4}], **overrides,
    })


def proposal(**overrides):
    return Proposal.model_validate({
        "request_id": "REQ-1046", "request_revision": 1, "policy_version": DEFAULT_POLICY.version,
        "members": [{"person_id": "P-006", "role": "POD_LEAD", "hours": 20,
                     "responsibilities": "Coordinate delivery", "deliverable_ids": ["DEL-001"]}],
        "rationale": "Matching capability and available hours.", "evidence_refs": ["skill:INT-001:P-006"],
        **overrides,
    })


def codes(req=None, pod=None, people=None, ledgers=None):
    return {issue.code for issue in validate_pod(
        req or request(), pod or proposal(), people if people is not None else (person(),),
        ledgers if ledgers is not None else {"P-006": CapacityLedger()},
    )}


class ContractTests(unittest.TestCase):
    def test_rejection_requires_nonblank_reason(self):
        for reason in ("", "   "):
            with self.subTest(reason=reason), self.assertRaises(ValidationError):
                CaptainDecision(proposal_id="PROP-1", proposal_version=1, action="REJECTED",
                                reason=reason, idempotency_key="decision-12345678")

    def test_approval_needs_no_acceptance_step(self):
        decision = CaptainDecision(proposal_id="PROP-1", proposal_version=1, action="APPROVED",
                                   idempotency_key="decision-12345678")
        self.assertEqual(decision.action, "APPROVED")
        self.assertNotIn("acceptance", decision.model_dump())

    def test_cannot_supply_actor_or_override_identity(self):
        with self.assertRaises(ValidationError):
            CaptainDecision(proposal_id="PROP-1", proposal_version=1, action="APPROVED",
                            idempotency_key="decision-12345678", actor_id="P-010")

    def test_invalid_schedule(self):
        for changes in ({"ends_on": date(2026, 9, 13)}, {"ends_on": date(2028, 1, 1)}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                request(**changes)

    def test_request_needs_effort_requirements_and_deliverables(self):
        for changes in ({"total_hours": 0}, {"total_hours": "NaN"}, {"total_hours": "1.001"},
                        {"requirements": []}, {"deliverable_ids": []}, {"revision": True}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                request(**changes)

    def test_duplicate_catalogue_references_rejected(self):
        for changes in ({"deliverable_ids": ["DEL-001", "DEL-001"]},
                        {"requirements": [{"skill_id": "INT-001"}, {"skill_id": "INT-001"}]}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                request(**changes)

    def test_role_derived_cannot_be_self_rated(self):
        with self.assertRaises(ValidationError):
            Requirement(skill_id="INT-PM", assessment_type="ROLE_DERIVED", minimum_strength=5)

    def test_duplicate_person_evidence_rejected(self):
        with self.assertRaises(ValidationError):
            person(skills=[{"skill_id": "INT-001", "strength": 3}] * 2)

    def test_weights_must_total_100(self):
        with self.assertRaises(ValidationError):
            Weights(skill=90)

    def test_draft_policy_cannot_be_used_for_live_assignment(self):
        with self.assertRaises(ServiceError):
            DEFAULT_POLICY.require_published()
        with self.assertRaises(ValidationError):
            StaffingPolicy(status="APPROVED")


class CapacityTests(unittest.TestCase):
    def test_twenty_hours_out_of_forty_is_fifty_percent(self):
        result = calculate_capacity(CapacityLedger(), MON, FRI, spread_hours(D(20), MON, FRI))
        self.assertTrue(result.feasible)
        self.assertEqual(result.weeks[0].allocation_pct, D(50))

    def test_distribution_preserves_cents_and_total(self):
        rows = spread_hours(D("10.01"), MON, FRI)
        self.assertEqual(sum(row.hours for row in rows), D("10.01"))
        self.assertTrue(all(row.hours == row.hours.quantize(D(".01")) for row in rows))

    def test_weekend_has_no_capacity(self):
        with self.assertRaises(ValueError):
            spread_hours(D(1), date(2026, 9, 19), date(2026, 9, 20))

    def test_short_request_includes_rest_of_week_commitments(self):
        ledger = CapacityLedger(confirmed_work=(DailyHours(day=FRI, hours=8),))
        result = calculate_capacity(ledger, MON, MON, spread_hours(D(8), MON, MON))
        self.assertEqual(result.weeks[0].committed_hours, D(8))
        self.assertEqual(result.weeks[0].allocation_pct, D(40))

    def test_daily_overload_rejected_even_if_week_looks_free(self):
        result = calculate_capacity(CapacityLedger(), MON, MON, spread_hours(D(9), MON, MON))
        self.assertFalse(result.feasible)
        self.assertEqual(result.overloaded_days, (MON,))

    def test_leave_reduces_capacity_and_blocks_scheduled_work(self):
        ledger = CapacityLedger(absences=(DailyHours(day=MON, hours=8),))
        result = calculate_capacity(ledger, MON, FRI, spread_hours(D(20), MON, FRI))
        self.assertEqual(result.weeks[0].available_hours, D(32))
        self.assertFalse(result.feasible)

    def test_full_absence_does_not_divide_by_zero(self):
        ledger = CapacityLedger(absences=spread_hours(D(40), MON, FRI))
        result = calculate_capacity(ledger, MON, FRI, spread_hours(D(1), MON, FRI))
        self.assertIsNone(result.weeks[0].allocation_pct)
        self.assertFalse(result.feasible)

    def test_external_and_confirmed_work_both_count(self):
        ledger = CapacityLedger(confirmed_work=spread_hours(D(16), MON, FRI),
                                external_work=spread_hours(D(8), MON, FRI))
        result = calculate_capacity(ledger, MON, FRI, spread_hours(D(20), MON, FRI))
        self.assertEqual(result.weeks[0].allocation_pct, D(110))
        self.assertFalse(result.feasible)

    def test_pending_proposals_not_part_of_ledger(self):
        with self.assertRaises(ValidationError):
            CapacityLedger(pending_work=[])

    def test_duplicates_and_out_of_window_proposals_rejected(self):
        row = DailyHours(day=MON, hours=2)
        with self.assertRaises(ValidationError):
            CapacityLedger(confirmed_work=[row, row])
        for rows in ((row, row), (DailyHours(day=date(2026, 9, 21), hours=2),)):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                calculate_capacity(CapacityLedger(), MON, FRI, rows)

    def test_multiweek_and_part_time_capacity(self):
        result = calculate_capacity(CapacityLedger(weekly_hours=20), MON, date(2026, 9, 25),
                                    spread_hours(D(20), MON, date(2026, 9, 25)))
        self.assertEqual(len(result.weeks), 2)
        self.assertTrue(all(week.allocation_pct == D(50) for week in result.weeks))

    def test_exact_comparison_not_rounded_percentage(self):
        result = calculate_capacity(CapacityLedger(weekly_hours=80), MON, FRI,
                                    spread_hours(D("80.01"), MON, FRI))
        self.assertFalse(result.feasible)


class EligibilityTests(unittest.TestCase):
    def test_valid_pod(self):
        self.assertEqual(codes(), set())

    def test_stale_request_and_policy(self):
        self.assertIn("STALE_REQUEST", codes(pod=proposal(request_revision=2)))
        self.assertIn("STALE_POLICY", codes(pod=proposal(policy_version="old")))

    def test_duplicate_members_and_evidence(self):
        self.assertIn("DUPLICATE_PERSON", codes(pod=proposal(members=proposal().members * 2)))
        self.assertIn("DUPLICATE_EVIDENCE", codes(people=(person(), person())))

    def test_unknown_and_inactive_people(self):
        self.assertIn("INACTIVE_OR_UNKNOWN", codes(people=()))
        self.assertIn("INACTIVE_OR_UNKNOWN", codes(people=(person(active=False),)))

    def test_effective_role_required_throughout_request(self):
        for roles in ([], [{"code": "POD_MEMBER", "starts_on": MON}],
                      [{"code": "POD_LEAD", "starts_on": MON, "ends_on": MON}]):
            with self.subTest(roles=roles):
                self.assertIn("ROLE_INELIGIBLE", codes(people=(person(roles=roles),)))

    def test_unknown_capacity_is_not_assumed_free(self):
        self.assertIn("CAPACITY_UNKNOWN", codes(ledgers={}))

    def test_interest_alone_is_not_proficiency(self):
        candidate = person(skills=[{"skill_id": "INT-001", "interested": True}])
        self.assertIn("CAPABILITY_GAP", codes(people=(candidate,)))

    def test_below_threshold_is_gap(self):
        self.assertIn("CAPABILITY_GAP", codes(people=(person(skills=[{"skill_id": "INT-001", "strength": 2}]),)))

    def test_role_derived_mapping_must_be_explicit(self):
        req = request(requirements=[{"skill_id": "INT-PM", "assessment_type": "ROLE_DERIVED"}])
        self.assertIn("ROLE_MAPPING_MISSING", codes(req=req))
        req = request(requirements=[{"skill_id": "INT-PM", "assessment_type": "ROLE_DERIVED",
                                     "derived_role_code": "POD_LEAD"}])
        self.assertEqual(codes(req=req), set())

    def test_counts_effort_and_deliverables_checked(self):
        self.assertIn("POD_SIZE", codes(req=request(member_count=1)))
        self.assertIn("EFFORT_TOTAL", codes(req=request(total_hours=21)))
        self.assertIn("DELIVERABLE_SCOPE", codes(req=request(deliverable_ids=["DEL-002"])))

    def test_supported_experience_needs_assigned_mentor(self):
        lead = person(deliverables=[{"deliverable_id": "DEL-001", "experience_level": "SUPPORTED",
                                     "contribution_scope": "CONTRIBUTOR", "experience": "Helped deliver it"}])
        self.assertIn("SUPPORT_REQUIRED", codes(people=(lead,)))
        mentor = person(person_id="P-007", roles=[{"code": "POD_MEMBER", "starts_on": MON}], deliverables=[{
            "deliverable_id": "DEL-001", "experience_level": "MENTOR",
            "contribution_scope": "END_TO_END", "experience": "Delivered and mentored teams",
        }])
        member = ProposedMember(person_id="P-007", role="POD_MEMBER", hours=5,
                                responsibilities="Mentor", deliverable_ids=["DEL-001"])
        req = request(member_count=1, total_hours=25)
        pod = proposal(members=(*proposal().members, member))
        self.assertEqual(codes(req=req, pod=pod, people=(lead, mentor),
                               ledgers={"P-006": CapacityLedger(), "P-007": CapacityLedger()}), set())

    def test_optional_capability_does_not_block(self):
        req = request(requirements=[{"skill_id": "INT-002", "mandatory": False}])
        self.assertEqual(codes(req=req), set())


class ScoreTests(unittest.TestCase):
    def test_score_is_repeatable_and_explained(self):
        first = score_candidate(person(), request(), D(50))
        self.assertEqual(first, score_candidate(person(), request(), D(50)))
        self.assertEqual(first["score"], D("47.50"))
        self.assertEqual(sum(first["factors"].values()), first["score"])

    def test_missing_rating_never_invented(self):
        result = score_candidate(person(skills=[]), request(), D(50))
        self.assertEqual(result["unknown_skill_ids"], ["INT-001"])
        self.assertEqual(result["factors"]["skill"], 0)

    def test_experience_without_description_is_not_scored_as_proof(self):
        candidate = person(deliverables=[{"deliverable_id": "DEL-001", "experience_level": "MENTOR",
                                          "contribution_scope": "END_TO_END"}])
        self.assertEqual(score_candidate(candidate, request(), D(50))["factors"]["deliverable"], 0)

    def test_invalid_capacity_not_scored(self):
        for value in (D(-1), D(101), D("NaN")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                score_candidate(person(), request(), value)


if __name__ == "__main__":
    unittest.main()
