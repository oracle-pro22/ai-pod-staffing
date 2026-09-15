"""Regression tests for meaningful, ledger-backed demo staffing (no network)."""
import unittest
from datetime import timedelta
from decimal import Decimal as D

from pydantic import ValidationError

from app.capacity import (CapacityLedger, DailyHours, calculate_capacity, distribute_cents,
                          schedule_available_hours, spread_hours)
from app.contracts import Candidate, DeliverableEvidence
from app.errors import ServiceError
from app.planning import EvidenceBundle, SearchResult, find_options, max_hours
from app.policy import DEFAULT_POLICY, SchedulingRules, StaffingPolicy
from app.rules import minimum_member_contribution, score_candidate, validate_pod
from test_rules import FRI, MON, person, request

POLICY = StaffingPolicy(version='staffing-demo-v2', scheduling=SchedulingRules())


def experience(level='INDEPENDENT', did='DEL-001'):
    return DeliverableEvidence(deliverable_id=did, experience_level=level,
        contribution_scope='END_TO_END', interested=True, experience='Created and reviewed sales launch materials.')


def employee(pid='P-006', role='POD_LEAD', **changes):
    return person(person_id=pid, roles=[{'code': role, 'starts_on': MON}],
        **{'skills': [{'skill_id': 'INT-001', 'strength': 4, 'evidence': 'Delivered customer-facing launch work.'}],
           'deliverables': [experience()], **changes})


def data(**changes):
    people = (employee(), employee('P-007', 'POD_MEMBER'), employee('P-008', 'POD_MEMBER'))
    return EvidenceBundle(**{'request': request(member_count=2, total_hours=24), 'policy': POLICY,
        'candidates': people, 'ledgers': {p.person_id: CapacityLedger() for p in people},
        'versions': {p.person_id: {'skills_version': 1, 'workload_version': 1, 'availability_version': 1} for p in people},
        'names': {p.person_id: p.person_id for p in people}, 'context': {},
        'catalogue': {'DEL-001': {'deliverable_name': 'Sales guide', 'mapped_capabilities': [
            {'skill_id': 'INT-001', 'interest_name': 'GTM SME'}]}}, **changes})


class MeaningfulPlanTests(unittest.TestCase):
    def test_original_friday_leave_point_zero_four_hours_reproduced_and_fixed(self):
        source = data()
        source.ledgers['P-008'] = CapacityLedger(absences=(DailyHours(day=FRI, hours=8),))
        legacy = source.model_copy(update={'policy': DEFAULT_POLICY})
        self.assertEqual(max_hours(legacy, 'P-008'), 4)  # four cents, not four hours
        self.assertEqual(max_hours(source, 'P-008'), 2400)
        plan = find_options(source).options[0]
        self.assertEqual([row.hours for row in plan.proposal.members], [D(8)] * 3)
        member = next(row for row in plan.proposal.members if row.person_id == 'P-008')
        self.assertEqual([day.hours for day in member.daily_schedule], [D(2)] * 4)
        self.assertNotIn(FRI, {day.day for day in member.daily_schedule})
        self.assertEqual(plan.scores['P-008']['projected_allocation_pct'], D(25))

    def test_exact_cents_conserved_without_token_team_members(self):
        source = data(request=request(member_count=2, total_hours='24.01'))
        plan = find_options(source).options[0]
        self.assertEqual(sorted(row.hours for row in plan.proposal.members), [D(8), D(8), D('8.01')])
        self.assertEqual(sum(day.hours for m in plan.proposal.members for day in m.daily_schedule), D('24.01'))
        self.assertEqual(minimum_member_contribution(source.request, POLICY), D('4.01'))
        weighted = sum(plan.scores[m.person_id]['score'] * m.hours for m in plan.proposal.members) / D('24.01')
        self.assertEqual(plan.average_score, weighted)

    def test_tiny_request_needs_smaller_pod_not_dummy_contributions(self):
        with self.assertRaises(ServiceError) as error:
            find_options(data(request=request(member_count=2, total_hours=1)))
        self.assertEqual(error.exception.code, 'NEEDS_INFORMATION')
        self.assertIn('Reduce the POD size', error.exception.message)

    def test_low_capacity_member_is_excluded_not_given_a_token_assignment(self):
        source = data()
        source.ledgers['P-008'] = CapacityLedger(external_work=spread_hours(D('39.96'), MON, FRI))
        found = find_options(source)
        self.assertFalse(found.options)
        self.assertEqual(found.exclusions['P-008'], 'INSUFFICIENT_MEANINGFUL_CAPACITY')

    def test_extra_idle_unqualified_person_is_not_selected(self):
        source = data()
        extra = employee('P-009', 'POD_MEMBER', skills=[], deliverables=[])
        source = source.model_copy(update={'candidates': (*source.candidates, extra),
            'ledgers': {**source.ledgers, extra.person_id: CapacityLedger()}})
        found = find_options(source)
        self.assertEqual(found.exclusions[extra.person_id], 'NO_RELEVANT_EVIDENCE')
        self.assertTrue(found.options)
        self.assertNotIn(extra.person_id, [row.person_id for row in found.options[0].proposal.members])

    def test_missing_capacity_remains_unknown_not_free(self):
        source = data()
        source.ledgers.pop('P-008')
        self.assertFalse(find_options(source).options)

    def test_only_effective_staffing_roles_are_selected(self):
        for role in ('POD_CAPTAIN', 'SYSTEM_ADMINISTRATOR'):
            source = data()
            people = (*source.candidates[:2], employee('P-008', role))
            self.assertFalse(find_options(source.model_copy(update={'candidates': people})).options)
        source = data()
        ending = Candidate.model_validate({**source.candidates[0].model_dump(),
            'roles': [{'code': 'POD_LEAD', 'starts_on': MON, 'ends_on': FRI - timedelta(days=1)}]})
        self.assertFalse(find_options(source.model_copy(update={'candidates': (ending, *source.candidates[1:])})).options)

    def test_mandatory_gap_cannot_be_replaced_by_interest(self):
        req = request(member_count=2, total_hours=24,
            requirements=[{'skill_id': 'INT-001'}, {'skill_id': 'INT-MISSING'}])
        self.assertFalse(find_options(data(request=req)).options)

    def test_project_manager_comes_from_effective_role_not_rating(self):
        req = request(member_count=2, total_hours=24, requirements=[{'skill_id': 'INT-001'},
            {'skill_id': 'INT-PM', 'assessment_type': 'ROLE_DERIVED', 'derived_role_code': 'POD_LEAD'}])
        self.assertTrue(find_options(data(request=req)).options)
        self.assertFalse(any(row.skill_id == 'INT-PM' for p in data().candidates for row in p.skills))

    def test_learning_requires_an_experienced_same_deliverable_teammate(self):
        source = data()
        learners = tuple(p.model_copy(update={'deliverables': (experience('LEARNING'),)}) for p in source.candidates)
        self.assertFalse(find_options(source.model_copy(update={'candidates': learners})).options)
        mentored = (source.candidates[0], *learners[1:])
        self.assertTrue(find_options(source.model_copy(update={'candidates': mentored})).options)

    def test_empty_evidence_does_not_inflate_skill_scores(self):
        req = request(requirements=[{'skill_id': 'INT-001'}, {'skill_id': 'INT-002'}])
        candidate = employee(skills=[{'skill_id': 'INT-001', 'strength': 4, 'evidence': 'Actual experience'},
                                     {'skill_id': 'INT-002', 'strength': 5}])
        result = score_candidate(candidate, req, D(50), POLICY)
        self.assertEqual(result['factors']['skill'], D(20))
        self.assertIn('INT-002', result['unknown_skill_ids'])
        self.assertGreater(score_candidate(candidate, req, D(50), DEFAULT_POLICY)['score'], result['score'])

    def test_reproducible_plan_and_schedule_survive_json_checkpoint(self):
        source = data()
        found = find_options(source)
        self.assertEqual(found, find_options(source))
        restored = SearchResult.model_validate_json(found.model_dump_json())
        self.assertEqual(restored.options[0].proposal, found.options[0].proposal)
        self.assertTrue(all(row.daily_schedule for row in restored.options[0].proposal.members))
        self.assertEqual(validate_pod(source.request, restored.options[0].proposal, source.candidates, source.ledgers, POLICY, catalogue=source.catalogue), ())

    def test_bounded_search_does_not_claim_global_optimum(self):
        source = data()
        extra = employee('P-009', 'POD_MEMBER')
        source = source.model_copy(update={'candidates': (*source.candidates, extra),
            'ledgers': {**source.ledgers, extra.person_id: CapacityLedger()}})
        found = find_options(source, limit=1)
        self.assertEqual(found.examined, 1)
        self.assertFalse(found.exhaustive)

    def test_v2_schedule_cannot_be_removed_or_moved_to_weekend(self):
        source = data()
        proposal = find_options(source).options[0].proposal
        member = proposal.members[0]
        for schedule in ((), (DailyHours(day=FRI + timedelta(days=1), hours=member.hours),)):
            changed = proposal.model_copy(update={'members': (member.model_copy(update={'daily_schedule': schedule}), *proposal.members[1:])})
            codes = {i.code for i in validate_pod(source.request, changed, source.candidates, source.ledgers, POLICY)}
            self.assertIn('INVALID_SCHEDULE', codes)
        with self.assertRaises(ValidationError):
            type(member).model_validate({**member.model_dump(), 'daily_schedule': [{'day': MON, 'hours': '0.01'}]})

    def test_deliverable_coverage_is_local_to_its_actual_assignees(self):
        source = data(request=request(member_count=1, total_hours=20,
            deliverable_ids=['DEL-001', 'DEL-002'], requirements=[{'skill_id': 'INT-001'}, {'skill_id': 'INT-002'}]))
        lead = employee(deliverables=[])
        member = employee('P-007', 'POD_MEMBER', deliverables=[],
            skills=[{'skill_id': 'INT-002', 'strength': 4, 'evidence': 'Created reviewed videos.'}])
        catalogue = {**source.catalogue, 'DEL-002': {'mapped_capabilities': [{'skill_id': 'INT-002'}]}}
        source = source.model_copy(update={'candidates': (lead, member), 'catalogue': catalogue})
        proposal = find_options(source).options[0].proposal
        self.assertEqual(proposal.members[1].deliverable_ids, ('DEL-002',))
        wrong_member = proposal.members[1].model_copy(update={'deliverable_ids': ('DEL-001',)})
        changed = proposal.model_copy(update={'members': (proposal.members[0], wrong_member)})
        issues = validate_pod(source.request, changed, source.candidates, source.ledgers, POLICY, catalogue=catalogue)
        self.assertIn(('DELIVERABLE_COVERAGE_GAP', 'DEL-002'), {(i.code, i.reference_id) for i in issues})

    def test_unmapped_deliverable_without_experience_is_not_invented(self):
        source = data(request=request(member_count=2, total_hours=24, deliverable_ids=['DEL-001', 'DEL-002']))
        source = source.model_copy(update={'catalogue': {**source.catalogue, 'DEL-002': {}}})
        self.assertFalse(find_options(source).options)
        # Existing end-to-end delivery evidence can support a request-specific deliverable.
        lead = source.candidates[0].model_copy(update={'deliverables': (*source.candidates[0].deliverables, experience(did='DEL-002'))})
        source = source.model_copy(update={'candidates': (lead, *source.candidates[1:])})
        proposal = find_options(source).options[0].proposal
        issues = validate_pod(source.request, proposal, source.candidates, source.ledgers, POLICY)
        self.assertIn('CATALOGUE_EVIDENCE_MISSING', {i.code for i in issues})


class ScheduleMathTests(unittest.TestCase):
    def test_partial_leave_external_and_confirmed_work_all_reduce_headroom(self):
        ledger = CapacityLedger(absences=(DailyHours(day=MON, hours=4),),
            external_work=(DailyHours(day=MON, hours=2),), confirmed_work=(DailyHours(day=MON, hours=1),))
        schedule = schedule_available_hours(ledger, D(10), MON, FRI)
        self.assertEqual(schedule[0].hours, D(1))
        self.assertEqual(sum(row.hours for row in schedule), D(10))
        self.assertTrue(calculate_capacity(ledger, MON, FRI, schedule).feasible)

    def test_daily_overload_not_hidden_by_weekly_average(self):
        ledger = CapacityLedger(confirmed_work=(DailyHours(day=MON, hours=7),))
        result = calculate_capacity(ledger, MON, FRI, (DailyHours(day=MON, hours=2),), allow_empty_weeks=True)
        self.assertFalse(result.feasible)
        self.assertEqual(result.weeks[0].allocation_pct, D('22.50'))

    def test_full_absence_week_can_be_skipped_without_work_or_divide_by_zero(self):
        ledger = CapacityLedger(absences=spread_hours(D(40), MON, FRI))
        end = FRI + timedelta(days=7)
        schedule = schedule_available_hours(ledger, D(8), MON, end)
        self.assertTrue(all(row.day > FRI for row in schedule))
        result = calculate_capacity(ledger, MON, end, schedule, allow_empty_weeks=True)
        self.assertTrue(result.feasible)
        self.assertIsNone(result.weeks[0].allocation_pct)
        self.assertFalse(calculate_capacity(ledger, MON, end, schedule).feasible)  # frozen v1 unchanged

    def test_one_day_request_distinguishes_window_from_full_week(self):
        source = data(request=request(member_count=0, total_hours=8, ends_on=MON), candidates=(employee(),))
        metrics = find_options(source).options[0].scores['P-006']
        self.assertEqual(metrics['window_allocation_pct'], D(100))
        self.assertEqual(metrics['projected_allocation_pct'], D(20))
        self.assertEqual(metrics['window_available_hours'], D(8))
        self.assertEqual(metrics['available_hours'], D(40))

    def test_peak_week_current_load_is_not_an_unrelated_current_calendar_week(self):
        end = FRI + timedelta(days=7)
        source = data(request=request(member_count=0, total_hours=8, ends_on=end), candidates=(employee(),))
        source.ledgers['P-006'] = CapacityLedger(external_work=spread_hours(D(20), MON + timedelta(days=7), end))
        metrics = find_options(source).options[0].scores['P-006']
        self.assertEqual(metrics['peak_week_start'], (MON + timedelta(days=7)).isoformat())
        self.assertEqual(metrics['current_allocation_pct'], D(50))
        self.assertEqual(metrics['projected_allocation_pct'], D(60))
        self.assertEqual(metrics['window_allocation_pct'], D(35))

    def test_capacity_ceiling_and_commitments_outside_request_are_respected(self):
        ledger = CapacityLedger(confirmed_work=(DailyHours(day=FRI, hours=8),))
        with self.assertRaises(ValueError):
            schedule_available_hours(ledger, D(1), MON, MON, D(80))
        ledger = CapacityLedger(external_work=(DailyHours(day=MON, hours=3),))
        schedule = schedule_available_hours(ledger, D(1), MON, MON, D(50))
        self.assertEqual(schedule[0].hours, D(1))
        with self.assertRaises(ValueError):
            schedule_available_hours(ledger, D('1.01'), MON, MON, D(50))

    def test_percentage_rounding_is_consistent(self):
        # 0.05 / 40 * 100 = 0.125%, consistently displayed as 0.13%.
        # Such tiny proposals are not allowed in v2, but existing-work metrics can be tiny.
        source = data(request=request(member_count=0, total_hours=1), candidates=(employee(),))
        source.ledgers['P-006'] = CapacityLedger(external_work=(DailyHours(day=MON, hours=D('.05')),))
        metrics = find_options(source).options[0].scores['P-006']
        self.assertEqual(metrics['current_allocation_pct'], D('.13'))
        self.assertEqual(metrics['current_window_allocation_pct'], D('.13'))

    def test_integer_waterfill_conserves_bounded_totals(self):
        for total in range(1, 160):
            for caps in ([3, 7, 150], [50, 30, 60], [2, 2, 2]):
                result = distribute_cents(total, caps, 1)
                if 3 <= total <= sum(caps):
                    self.assertEqual(sum(result), total)
                    self.assertTrue(all(1 <= n <= cap for n, cap in zip(result, caps)))
                else:
                    self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
