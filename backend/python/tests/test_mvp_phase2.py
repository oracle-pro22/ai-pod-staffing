"""Supervisor, conditional choices, immutable drafts and transactional approval.

Offline models/Oracle doubles; these do not claim live OCI or Oracle lock tests.
"""
import copy
import json
import unittest
from contextlib import contextmanager
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent_budget import budget_counters, reserve_call
from app.agents.staffing import Analysis, required_plan_references
from app.agents.supervisor import choose_transition, execution_status
from app.alternatives import exact_team, replacement_options, selected_ids
from app.auth import Actor, Permission
from app.capacity import CapacityLedger, spread_hours
from app.config import Settings
from app.engine_version import new_checkpoint, validate_checkpoint_state
from app.errors import ServiceError
from app.main import create_app
from app.planning import find_options, json_text
from app.selections import (ReviewSnapshot, SelectionStore, SelectionUpdate, evidence_hash,
                            review_view, selection_for_approval, snapshot)
from app.workflow import StaffingWorkflow
from test_agent_handoff import BudgetedMemoryStore, analysis_values, evidence_calls
from test_demo_agent_planning import data, employee
from test_phase3 import job
from test_phase3_runtime import ScriptedModel
from test_rules import MON, FRI


def roster():
    people = tuple(employee(f'P-{i:03}', 'POD_LEAD' if i <= 3 else 'POD_MEMBER') for i in range(1, 10))
    return data(candidates=people, ledgers={p.person_id: CapacityLedger() for p in people},
        versions={p.person_id: {'skills_version': 1, 'workload_version': 1, 'availability_version': 1} for p in people},
        names={p.person_id: f'Person {i}' for i, p in enumerate(people)},
        context={'business_objectives': 'Sales guide', 'expected_outcomes': 'Reviewed deck', 'project_description': 'Launch'},
        policy=data().policy.model_copy(update={'maximum_allocation_pct': D(85)}))


def captain(role='POD_CAPTAIN', person_id='P-010'):
    return Actor('captain-subject', person_id, frozenset({role}),
                 (Permission(role, 'AI_FITMENT', 'FULL', frozenset({'view', 'approve'})),))


class AlternativeTests(unittest.TestCase):
    def setUp(self):
        self.data = roster()
        self.option = exact_team(self.data, ('P-001',), ('P-004', 'P-005'))

    def test_one_lead_plus_two_distinct_alternatives_and_n_plus_two_members(self):
        result = replacement_options(self.data, self.option)
        self.assertEqual({r.person_id for r in result.replacements if r.role == 'POD_LEAD'}, {'P-002', 'P-003'})
        members = {r.person_id for r in result.replacements if r.role == 'POD_MEMBER'}
        self.assertEqual(len(members), 2)
        self.assertFalse(members & {'P-001', 'P-004', 'P-005'})
        self.assertTrue(result.exhaustive)
        self.assertFalse(result.notes)
        for replacement in result.replacements:
            leads, members = selected_ids(self.option)
            change = lambda ids: tuple(replacement.person_id if pid == replacement.replaces else pid for pid in ids)
            option = exact_team(self.data, change(leads), change(members))
            people = option.proposal.members
            self.assertEqual(len({p.person_id for p in people}), 3)
            self.assertNotIn(replacement.replaces, {p.person_id for p in people})
            self.assertEqual(sum(p.hours for p in people), D(24))
            self.assertEqual(sum(day.hours for p in people for day in p.daily_schedule), D(24))

    def test_pinned_team_is_not_silently_replaced_and_roles_not_changed(self):
        # This person can fill either slot only because both grants are explicit.
        dual = self.data.candidates[0].model_copy(update={'roles': (*self.data.candidates[0].roles,
            self.data.candidates[3].roles[0])})
        self.data = self.data.model_copy(update={'candidates': (dual, *self.data.candidates[1:])})
        original = copy.deepcopy(self.data)
        chosen = exact_team(self.data, ('P-003',), ('P-001', 'P-009'))
        self.assertEqual(selected_ids(chosen), (('P-003',), ('P-001', 'P-009')))
        self.assertEqual(self.data, original)

    def test_wrong_count_duplicate_unknown_wrong_role_rejected(self):
        for leads, members in ((('P-001',), ('P-001', 'P-004')), (('P-004',), ('P-005', 'P-006')),
                              (('P-001',), ('P-004',)), (('P-999',), ('P-004', 'P-005'))):
            with self.subTest(leads=leads, members=members), self.assertRaises(ServiceError):
                exact_team(self.data, leads, members)

    def test_high_load_and_skillless_alternatives_are_not_padded(self):
        self.data.ledgers['P-002'] = CapacityLedger(external_work=spread_hours(D(34), MON, FRI))
        people = tuple(p.model_copy(update={'skills': (), 'deliverables': ()}) if p.person_id == 'P-003' else p for p in self.data.candidates)
        source = self.data.model_copy(update={'candidates': people})
        result = replacement_options(source, self.option)
        self.assertFalse([r for r in result.replacements if r.role == 'POD_LEAD'])
        self.assertTrue(result.notes)
        with self.assertRaises(ServiceError):
            exact_team(source, ('P-002',), ('P-004', 'P-005'))

    def test_replacement_recalculates_every_person_and_exact_effort(self):
        self.data.ledgers['P-002'] = CapacityLedger(external_work=spread_hours(D(28), MON, FRI))
        option = exact_team(self.data, ('P-002',), ('P-004', 'P-005'))
        self.assertEqual({m.person_id: m.hours for m in option.proposal.members}, {'P-002': D(6), 'P-004': D(9), 'P-005': D(9)})
        self.assertEqual(option.scores['P-002']['window_allocation_pct'], D(85))
        self.assertEqual(option.scores['P-004']['window_allocation_pct'], D('22.50'))
        self.assertEqual(self.option.scores['P-004']['window_allocation_pct'], D(20))

    def test_new_admin_limit_is_used_without_changing_weights(self):
        self.data.ledgers['P-002'] = CapacityLedger(external_work=spread_hours(D(28), MON, FRI))
        with self.assertRaises(ServiceError):
            exact_team(self.data.model_copy(update={'policy': self.data.policy.model_copy(update={'maximum_allocation_pct': D(75)})}),
                       ('P-002',), ('P-004', 'P-005'))

    def test_collective_coverage_still_applies_to_swaps(self):
        source = self.data.model_copy(update={'candidates': tuple(p.model_copy(update={'skills': ()}) if p.person_id != 'P-001'
                                                                else p for p in self.data.candidates)})
        result = replacement_options(source, self.option)
        self.assertFalse([r for r in result.replacements if r.role == 'POD_LEAD'])

    def test_short_pool_zero_members_and_bounded_search_are_honest(self):
        short = data()
        result = replacement_options(short, find_options(short).options[0])
        self.assertFalse(result.replacements)
        self.assertTrue(result.notes)
        bounded = replacement_options(self.data, self.option, limit=1)
        self.assertFalse(bounded.exhaustive)
        self.assertEqual(bounded.examined, 1)
        source = self.data.model_copy(update={'request': self.data.request.model_copy(update={'member_count': 0, 'total_hours': D(8)})})
        solo = exact_team(source, ('P-001',), ())
        self.assertFalse([r for r in replacement_options(source, solo).replacements if r.role == 'POD_MEMBER'])


class SupervisorTests(unittest.TestCase):
    def test_full_real_langgraph_journey_has_three_distinct_tool_roles(self):
        source = roster()
        option = find_options(source).options[0]
        model = ScriptedModel([[('delegate_analysis', {})], *evidence_calls(), [('complete_analysis', analysis_values())],
            [('delegate_planning', {})], [('get_validated_options', {})], [('complete_plan', {
                'plan_id': option.plan_id, 'explanation': 'Valid team',
                'evidence_refs': sorted(required_plan_references(source, option.proposal))})], [('finish_review', {})]])
        store, item = BudgetedMemoryStore(), job(source)
        result = StaffingWorkflow(store, item, lambda: model).run()
        self.assertEqual(result['outcome'], 'READY_FOR_REVIEW')
        self.assertEqual(item.checkpoint['model_calls'], 9)
        self.assertEqual(item.checkpoint['supervisor_model_calls'], 3)
        self.assertEqual(item.checkpoint['delegate_attempts'], {'analysis': 1, 'planning': 1})
        self.assertNotIn('supervisor_pending', {k: v for k, v in item.checkpoint.items() if v != 'finish_review'})
        self.assertTrue(any(stage == 'supervisor' for stage, _ in store.saved))

    def test_cannot_skip_analysis_call_writes_or_invent_clarifications(self):
        for action, args in (('delegate_planning', {}), ('finish_review', {}), ('execute_sql', {}),
                             ('request_clarification', {}), ('delegate_analysis', {'person_id': 'P-001'})):
            with self.subTest(action=action), self.assertRaises(ServiceError):
                choose_transition(ScriptedModel([[(action, args)]]), new_checkpoint(), lambda: None, lambda: None)

    def test_repeated_inspection_exhausts_durable_budget(self):
        item, store = job(roster()), BudgetedMemoryStore()
        with self.assertRaises(ServiceError) as error:
            StaffingWorkflow(store, item, lambda: ScriptedModel([[('inspect_execution_status', {})]] * 10)).run()
        self.assertEqual(error.exception.code, 'AGENT_BUDGET_EXCEEDED')
        self.assertEqual(item.checkpoint['supervisor_model_calls'], 4)

    def test_model_output_retry_is_bounded_and_resumes_evidence_reads(self):
        source = roster()
        option = find_options(source).options[0]
        model = ScriptedModel([[('delegate_analysis', {})], [], [('delegate_analysis', {})], *evidence_calls(),
            [('complete_analysis', analysis_values())], [('delegate_planning', {})], [('get_validated_options', {})],
            [('complete_plan', {'plan_id': option.plan_id, 'explanation': 'Valid',
                              'evidence_refs': sorted(required_plan_references(source, option.proposal))})], [('finish_review', {})]])
        item, store = job(source), BudgetedMemoryStore()
        self.assertEqual(StaffingWorkflow(store, item, lambda: model).run()['outcome'], 'READY_FOR_REVIEW')
        self.assertEqual(item.checkpoint['delegate_attempts']['analysis'], 2)
        self.assertEqual(item.checkpoint['model_calls'], 11)

    def test_old_two_agent_checkpoint_not_reinterpreted(self):
        for change in ({'format_version': 3}, {'engine_version': 'staffing-engine-v3'}, {'supervisor_model_calls': None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_checkpoint_state({**new_checkpoint(), **change})

    def test_pending_and_completed_delegate_crash_recovery(self):
        source, store = roster(), BudgetedMemoryStore()
        item = job(source)
        item.checkpoint.update(supervisor_pending='delegate_analysis', delegate_inflight='analysis', delegate_attempts={'analysis': 2})
        flow = StaffingWorkflow(store, item, lambda: self.fail('Pending delegation should not call Supervisor again'))
        self.assertEqual(flow.supervise({})['route'], 'analysis_delegate')
        item.checkpoint['analysis'] = Analysis(**analysis_values()).model_dump(mode='json')
        flow.model_factory = lambda: ScriptedModel([[('delegate_planning', {})]])
        self.assertEqual(flow.supervise({})['route'], 'planning_delegate')
        self.assertNotIn('delegate_inflight', item.checkpoint)

    def test_all_three_model_counters_sum_and_total_never_increases(self):
        state = new_checkpoint()
        for stage, count in (('supervisor', 1), ('analyst', 6), ('supervisor', 1), ('planner', 3), ('supervisor', 1)):
            for _ in range(count):
                state.update(reserve_call(state, stage, 'model_calls', 12))
        self.assertEqual(budget_counters(state)['model_calls'], 12)
        for stage in ('supervisor', 'analyst', 'planner'):
            with self.assertRaises(ServiceError):
                reserve_call(state, stage, 'model_calls', 12)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.data = roster()
        self.original = exact_team(self.data, ('P-001',), ('P-004', 'P-005'))
        self.review = snapshot(self.data, self.original, self.original, 2000)

    def test_preview_roundtrip_preserves_original_and_sources(self):
        changed = exact_team(self.data, ('P-002',), ('P-004', 'P-005'))
        preview = snapshot(self.data, changed, self.original, 2000)
        restored = ReviewSnapshot.model_validate_json(json_text(preview))
        view = review_view(self.review, restored, 1, 'SD-1')
        self.assertEqual(view['members'][0]['source'], 'ALTERNATIVE')
        self.assertFalse(view['reserves_capacity'])
        self.assertEqual(view['original_members'][0]['person_id'], 'P-001')
        self.assertNotIn('evidence_hash', view)
        self.assertNotIn('ledgers', view)

    def test_approval_rejects_stale_selection_or_changed_workload(self):
        latest = {'selection_id': 'SD-1', 'revision': 1}
        with patch('app.selections.load_review', return_value=(self.review, self.review, latest)):
            with self.assertRaises(ServiceError) as error:
                selection_for_approval(None, {'proposal_id': 'PP-1'}, None, self.data)
            self.assertEqual(error.exception.code, 'STALE_SELECTION')
            changed = self.data.model_copy(update={'versions': {**self.data.versions, 'P-004': {'skills_version': 2}}})
            with self.assertRaises(ServiceError) as error:
                selection_for_approval(None, {'proposal_id': 'PP-1'}, 'SD-1', changed)
            self.assertEqual(error.exception.code, 'SELECTION_REFRESH_REQUIRED')
            accepted = selection_for_approval(None, {'proposal_id': 'PP-1'}, 'SD-1', self.data)
            self.assertEqual(accepted, self.review)

    def test_skill_policy_catalogue_and_request_changes_change_fingerprint(self):
        baseline = evidence_hash(self.data)
        for changes in ({'request': self.data.request.model_copy(update={'revision': 2})},
                        {'catalogue': {}}, {'ledgers': {}}, {'candidates': ()},
                        {'policy': self.data.policy.model_copy(update={'maximum_allocation_pct': D(80)})}):
            self.assertNotEqual(baseline, evidence_hash(self.data.model_copy(update=changes)))

    def test_client_cannot_supply_scores_hours_override_or_actor(self):
        for change in ({'hours': 1}, {'override': True}, {'score': 100}, {'actor_subject': 'admin'},
                       {'person_id': 'P-001'}, {'revision': True}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                SelectionUpdate(**{'revision': 0, 'idempotency_key': 'selection-test-00001', **change})


class SelectionStoreTests(SelectionTests):
    def setUp(self):
        super().setUp()
        self.pending, self.committed = [], []
        self.prior, self.latest = [], None
        self.fail = False
        @contextmanager
        def transaction():
            try:
                yield None
                self.committed.extend(self.pending)
            finally:
                self.pending.clear()
        self.store = SelectionStore(SimpleNamespace(write=transaction), SimpleNamespace(staffing_max_candidates=60, staffing_search_limit=2000))
        self.patches = [patch('app.selections.rows', side_effect=self.read),
            patch('app.manual_store.rows', side_effect=self.read),
            patch('app.selections.execute', side_effect=self.write),
            patch('app.selections.require_current_policy'), patch('app.decisions.DecisionStore.authorize'),
            patch('app.selections.collect_evidence', return_value=self.data),
            patch('app.selections.load_review', side_effect=lambda *_: (self.review, self.review, self.latest))]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)

    def read(self, _, sql, **binds):
        if 'SELECT request_id,policy_version' in sql:
            return [{'request_id': self.data.request.request_id, 'policy_version': self.data.policy.version}]
        if 'SELECT request_revision' in sql:
            return [{'request_revision': 1, 'responsible_captain_id': 'P-010', 'status': 'NEEDS_RECOMMENDATION'}]
        if 'SELECT * FROM pod_proposals' in sql:
            return [{'status': 'READY_FOR_REVIEW', 'request_revision': 1}]
        if 'body_hash FROM' in sql:
            return self.prior
        return []

    def write(self, _, sql, binds, *args):
        self.pending.append((sql, binds))
        if self.fail and 'audit_events' in sql:
            raise RuntimeError('Audit failed')

    def change(self, **changes):
        return SelectionUpdate(**{'revision': 0, 'idempotency_key': 'selection-test-00001', **changes})

    def test_only_draft_and_audit_written_no_assignments_no_original_edits(self):
        choice = next(r for r in self.review.alternatives.replacements if r.role == 'POD_LEAD')
        result = self.store.update(captain(), 'PP-1', self.change(person_id=choice.person_id, replaces=choice.replaces, role=choice.role))
        self.assertEqual(result['revision'], 1)
        self.assertEqual(result['members'][0]['person_id'], choice.person_id)
        sql = ' '.join(s.lower() for s, _ in self.committed)
        self.assertIn('insert into mvp_p2_selections', sql)
        audit_sql, audit_binds = next((s, b) for s, b in self.committed if 'audit_events' in s.lower())
        self.assertIn('correlation_id', audit_sql.lower())
        self.assertIn(':auditId', audit_sql)
        self.assertTrue(audit_binds['auditId'])
        for forbidden in ('update pod_proposals', 'pod_assignments', 'assignment_days', 'notification_outbox', 'update people'):
            self.assertNotIn(forbidden, sql)

    def test_offered_person_cannot_replace_an_unadvertised_slot(self):
        with self.assertRaises(ServiceError) as error:
            self.store.update(captain(), 'PP-1', self.change(person_id='P-009', replaces='P-001', role='POD_LEAD'))
        self.assertEqual(error.exception.code, 'INVALID_SELECTION')
        self.assertFalse(self.committed)

    def test_stale_revision_and_non_captain_have_no_writes(self):
        for user, change in ((captain(), self.change(revision=1)), (captain('SYSTEM_ADMINISTRATOR'), self.change()),
                             (captain('POD_MEMBER'), self.change()), (captain('POD_LEAD'), self.change())):
            with self.subTest(user=user), self.assertRaises(ServiceError):
                self.store.update(user, 'PP-1', change)
        self.assertFalse(self.committed)

    def test_failed_audit_rolls_back_preview(self):
        self.fail = True
        with self.assertRaises(RuntimeError):
            self.store.update(captain(), 'PP-1', self.change())
        self.assertFalse(self.committed)

    def test_manual_draft_blocks_alternative_changes(self):
        with patch('app.manual_store.pending_manual', return_value={'draft_id': 'MD-1'}), self.assertRaises(ServiceError) as error:
            self.store.update(captain(), 'PP-1', self.change())
        self.assertEqual(error.exception.code, 'MANUAL_DRAFT_ACTIVE')
        self.assertFalse(self.committed)


class SelectionApiTests(unittest.TestCase):
    def setUp(self):
        self.auth, self.store = MagicMock(), MagicMock()
        self.auth.resolve.return_value = captain()
        settings = Settings(backend_env='test', backend_auth_mode='local', backend_local_token='x'*32, backend_local_subject='captain-subject')
        self.client = TestClient(create_app(settings, MagicMock(), authorization=self.auth, selections=self.store))
        self.headers = {'Authorization': 'Bearer ' + 'x'*32}
        self.body = {'revision': 0, 'idempotency_key': 'selection-test-00001'}

    def test_verified_captain_forwarded_not_browser_role(self):
        self.store.update.return_value = {'revision': 1}
        response = self.client.post('/v1/proposals/PP-1/selection', headers=self.headers, json=self.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.update.call_args.args[0].subject, 'captain-subject')

    def test_direct_api_non_captain_and_tampered_fields_rejected(self):
        for role in ('SYSTEM_ADMINISTRATOR', 'POD_LEAD', 'POD_MEMBER'):
            self.auth.resolve.return_value = captain(role)
            self.assertEqual(self.client.post('/v1/proposals/PP-1/selection', headers=self.headers, json=self.body).status_code, 403)
        self.auth.resolve.return_value = captain()
        self.assertEqual(self.client.post('/v1/proposals/PP-1/selection', headers=self.headers, json={**self.body, 'override': True}).status_code, 422)
        self.assertEqual(self.client.post('/v1/proposals/PP-1/selection', json=self.body).status_code, 401)
        self.store.update.assert_not_called()


class SelectedApprovalTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing transactional Oracle double, including rollback
        # injection and real existing authorization/assignment code.
        from test_phase4 import DecisionTests
        self.h = DecisionTests(methodName='test_approval_commits_final_assignments_and_exact_days_without_email')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        h = self.h
        extra = employee('P-008', 'POD_MEMBER')
        h.data = h.data.model_copy(update={'candidates': (*h.data.candidates, extra),
            'ledgers': {**h.data.ledgers, 'P-008': CapacityLedger()},
            'versions': {**h.data.versions, 'P-008': {'skills_version': 0, 'workload_version': 0, 'availability_version': 0}},
            'names': {**h.data.names, 'P-008': 'Alternative Member'}})
        h.fresh = h.data
        original = snapshot(h.data, h.option, h.option, 2000)
        chosen = exact_team(h.data, ('P-006',), ('P-008',))
        self.review = snapshot(h.data, chosen, h.option, 2000)
        self.latest = {'selection_id': 'SD-1', 'revision': 1}
        self.loaded = original, self.review, self.latest
        patches = [patch('app.decisions.load_review', side_effect=lambda *_: self.loaded),
                   patch('app.selections.load_review', side_effect=lambda *_: self.loaded),
                   patch('app.proposal_writer.execute', side_effect=h.execute),
                   patch('app.storage.rows', return_value=[{'next_version': 2}])]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def test_approved_exact_selection_is_new_frozen_revision_and_one_transaction(self):
        result = self.h.decide(selection_id='SD-1')
        self.assertNotEqual(result['proposal_id'], 'PP-1')
        assignments = [b for sql, b in self.h.committed if 'INSERT INTO pod_assignments' in sql]
        self.assertEqual({b['personId'] for b in assignments}, {'P-006', 'P-008'})
        self.assertEqual(sum(b['assignedHours'] for b in assignments), D(20))
        self.assertTrue(all(b['proposalId'] == result['proposal_id'] for b in assignments))
        new_proposals = [b for sql, b in self.h.committed if 'INSERT INTO pod_proposals' in sql]
        self.assertEqual(len(new_proposals), 1)
        self.assertEqual(new_proposals[0]['executionId'], 'RUN-1')
        provenance = json.loads(new_proposals[0]['validationJson'])
        self.assertEqual(provenance['source_proposal_id'], 'PP-1')
        self.assertEqual(provenance['selection_id'], 'SD-1')
        self.assertEqual(provenance['selection_sources']['P-008'], 'ALTERNATIVE')
        self.assertTrue(any('INSERT INTO mvp_p2_decisions' in sql for sql, _ in self.h.committed))

    def test_new_proposal_or_assignment_failure_rolls_back_everything(self):
        for statement in ('INSERT INTO pod_proposal_members', 'INSERT INTO mvp_p2_decisions', 'INSERT INTO assignment_days'):
            self.h.fail_on = statement
            with self.subTest(statement=statement), self.assertRaises(RuntimeError):
                self.h.decide(selection_id='SD-1')
            self.assertFalse(self.h.committed)

    def test_stale_draft_and_even_small_workload_change_cannot_be_silently_approved(self):
        with self.assertRaises(ServiceError) as error:
            self.h.decide()
        self.assertEqual(error.exception.code, 'STALE_SELECTION')
        ledgers = {**self.h.data.ledgers, 'P-008': CapacityLedger(external_work=spread_hours(D(1), MON, FRI))}
        self.h.fresh = self.h.data.model_copy(update={'ledgers': ledgers})
        with self.assertRaises(ServiceError) as error:
            self.h.decide(selection_id='SD-1')
        self.assertEqual(error.exception.code, 'SELECTION_REFRESH_REQUIRED')
        self.assertFalse(self.h.committed)

    def test_reject_selection_requires_reason_and_retains_source_link_no_assignment(self):
        self.h.decide('REJECTED', selection_id='SD-1', reason='Choose a different delivery profile')
        self.assertTrue(any('INSERT INTO mvp_p2_decisions' in sql and b['selectionId'] == 'SD-1' for sql, b in self.h.committed))
        self.assertFalse(any('INSERT INTO pod_assignments' in sql or 'INSERT INTO pod_proposals' in sql for sql, _ in self.h.committed))

    def test_selected_approval_idempotency_replays_final_proposal_not_original(self):
        self.h.prior = [{'proposal_id': 'PP-final', 'proposal_version': 2, 'decision_id': 'DC-1',
                         'action_type': 'APPROVED', 'reason': None}]
        def read(connection, sql, **binds):
            if 'FROM mvp_p2_decisions' in sql:
                return [{'source_proposal_id': 'PP-1', 'source_proposal_version': 1, 'selection_id': 'SD-1'}]
            return self.h.read(connection, sql, **binds)
        with patch('app.decisions.rows', side_effect=read):
            result = self.h.decide(selection_id='SD-1')
            self.assertTrue(result['replayed'])
            self.assertEqual(result['proposal_id'], 'PP-final')
            with self.assertRaises(ServiceError) as error:
                self.h.decide(selection_id='SD-other')
            self.assertEqual(error.exception.code, 'IDEMPOTENCY_CONFLICT')
        self.assertFalse(self.h.committed)


if __name__ == '__main__':
    unittest.main()
