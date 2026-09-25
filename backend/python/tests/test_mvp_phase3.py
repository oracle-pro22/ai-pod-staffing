"""Offline Phase 3 arithmetic, authority and atomic database-command tests."""
import copy
import json
import unittest
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app

from pydantic import ValidationError
from app.capacity import CapacityLedger, spread_hours
from app.errors import ServiceError
from app.execution_store import ExecutionStore
from app.alternatives import exact_team
from app.selections import snapshot
from app.manual_planning import ManualSlot, manual_plan
from app.manual_store import ManualStore, ManualPreviewInput, ManualDecisionInput
from test_mvp_phase2 import roster, captain
from test_rules import MON, FRI


def single(hours='16', committed='24', leave='40', external='40'):
    base = roster()
    p = base.candidates[0].model_copy(update={'skills': (), 'deliverables': ()})
    ledger = CapacityLedger(confirmed_work=spread_hours(D(committed), MON, FRI) if D(committed) else (),
        absences=spread_hours(D(leave), MON, FRI) if D(leave) else (),
        external_work=spread_hours(D(external), MON, FRI) if D(external) else ())
    return base.model_copy(update={'request': base.request.model_copy(update={'total_hours': D(hours), 'lead_count': 1, 'member_count': 0}),
        'candidates': (p,), 'ledgers': {p.person_id: ledger},
        'policy': base.policy.model_copy(update={'status': 'APPROVED', 'approved_by': 'operator', 'approved_at': '2026-09-01T00:00:00Z'})})


SLOT = ManualSlot(person_id='P-001', role='POD_LEAD', manual=True)


class ManualPlanningTests(unittest.TestCase):
    def test_24_existing_plus_16_new_is_100_even_during_full_leave(self):
        source = single()
        before = source.model_dump_json()
        option = manual_plan(source, (SLOT,))
        facts = option.scores['P-001']
        self.assertIsNone(facts['score'])
        self.assertIsNone(option.average_score)
        self.assertEqual(facts['window_allocation_pct'], D(100))
        self.assertEqual(facts['projected_allocation_pct'], D(100))
        self.assertIsNone(facts['reported_workload']['window_allocation_pct'])
        self.assertEqual(facts['ignored_leave_hours'], D(40))
        self.assertEqual(facts['ignored_external_hours'], D(40))
        self.assertEqual(sum(d.hours for d in option.proposal.members[0].daily_schedule), D(16))
        self.assertEqual(source.model_dump_json(), before)
        self.assertTrue(facts['recorded_gaps'])

    def test_even_one_hundredth_over_100_is_blocked_no_rounding_bypass(self):
        with self.assertRaises(ServiceError) as e:
            manual_plan(single('16.01'), (SLOT,))
        self.assertEqual(e.exception.code, 'MANUAL_CAPACITY_EXCEEDED')

    def test_existing_pod_hours_are_not_ignored_or_replaced_by_external_work(self):
        with self.assertRaises(ServiceError):
            manual_plan(single('1', '40', '0', '0'), (SLOT,))
        result = manual_plan(single('40', '0', '0', '40'), (SLOT,))
        self.assertEqual(result.scores['P-001']['window_allocation_pct'], D(100))
        self.assertEqual(result.scores['P-001']['reported_workload']['window_allocation_pct'], D(200))

    def test_manual_may_exceed_85_but_lower_admin_limit_does_not_change_100(self):
        source = single('12', '24', '0', '0')
        for threshold in (D(85), D(60), D(95)):
            source = source.model_copy(update={'policy': source.policy.model_copy(update={'maximum_allocation_pct': threshold})})
            self.assertEqual(manual_plan(source, (SLOT,)).scores['P-001']['window_allocation_pct'], D(90))

    def test_daily_and_partial_week_limit_not_hidden_by_full_week_capacity(self):
        source = single('4', '0', '0', '0')
        req = source.request.model_copy(update={'starts_on': MON, 'ends_on': MON})
        ledger = CapacityLedger(confirmed_work=spread_hours(D(5), MON, MON))
        source = source.model_copy(update={'request': req, 'ledgers': {'P-001': ledger}})
        with self.assertRaises(ServiceError):
            manual_plan(source, (SLOT,))
        source = source.model_copy(update={'request': req.model_copy(update={'total_hours': D(3)})})
        self.assertEqual(manual_plan(source, (SLOT,)).scores['P-001']['window_allocation_pct'], D(100))

    def test_wrong_role_duplicate_count_inactive_unknown_and_no_explicit_override(self):
        for source, slots in ((single(), (SLOT.model_copy(update={'role': 'POD_MEMBER'}),)),
                              (single(), (SLOT, SLOT)), (single(), (SLOT.model_copy(update={'person_id': 'P-999'}),)),
                              (single(), (SLOT.model_copy(update={'manual': False}),))):
            with self.subTest(slots=slots), self.assertRaises(ServiceError):
                manual_plan(source, slots)
        source = single()
        source = source.model_copy(update={'candidates': (source.candidates[0].model_copy(update={'active': False}),)})
        with self.assertRaises(ServiceError):
            manual_plan(source, (SLOT,))

    def test_unknown_capacity_fails_closed(self):
        with self.assertRaises(ServiceError) as e:
            manual_plan(single().model_copy(update={'ledgers': {}}), (SLOT,))
        self.assertEqual(e.exception.code, 'CAPACITY_UNKNOWN')

    def test_nonmanual_slots_keep_skill_support_and_capacity_rules(self):
        source = roster()
        slots = (SLOT, ManualSlot(person_id='P-004', role='POD_MEMBER', manual=False), ManualSlot(person_id='P-005', role='POD_MEMBER', manual=False))
        source.ledgers['P-001'] = CapacityLedger(absences=spread_hours(D(40), MON, FRI))
        option = manual_plan(source, slots)
        self.assertEqual(sum(m.hours for m in option.proposal.members), D(24))
        self.assertIsNotNone(option.scores['P-004']['score'])
        source.ledgers['P-004'] = CapacityLedger(external_work=spread_hours(D(40), MON, FRI))
        with self.assertRaises(ServiceError):
            manual_plan(source, slots)
        source.ledgers['P-004'] = CapacityLedger()
        source = source.model_copy(update={'candidates': tuple(p.model_copy(update={'skills': (), 'deliverables': ()}) if p.person_id == 'P-004' else p for p in source.candidates)})
        with self.assertRaises(ServiceError) as e:
            manual_plan(source, slots)
        self.assertEqual(e.exception.code, 'MANUAL_TEAM_INVALID')

    def test_part_time_multiweek_and_rounding_use_person_hours_not_default40(self):
        source = single('20', '0', '0', '0')
        source.ledgers['P-001'] = CapacityLedger(weekly_hours=D(20))
        self.assertEqual(manual_plan(source, (SLOT,)).scores['P-001']['window_allocation_pct'], D(100))
        source = source.model_copy(update={'request': source.request.model_copy(update={'ends_on': FRI + timedelta(days=7), 'total_hours': D('39.99')})})
        self.assertEqual(sum(d.hours for d in manual_plan(source, (SLOT,)).proposal.members[0].daily_schedule), D('39.99'))


class ManualStoreTests(unittest.TestCase):
    def setUp(self):
        self.source = single()
        self.actor = captain()
        self.request_id = self.source.request.request_id
        self.settings = SimpleNamespace(staffing_decisions_enabled=True, staffing_max_candidates=60)
        self.drafts, self.resolutions, self.committed, self.queries = [], [], [], []
        self.pending, self.fail_on, self.running, self.permission, self.active, self.status = [], None, False, True, True, 'NEEDS_RECOMMENDATION'
        self.revision = 1
        @contextmanager
        def tx():
            try:
                yield None
                for sql, b in self.pending:
                    if 'INSERT INTO mvp_p3_drafts' in sql:
                        self.drafts.append({'draft_id': b['draftId'], 'request_id': b['requestId'], 'request_revision': b['requestRevision'],
                            'revision': b['revision'], 'policy_version': b['policyVersion'], 'preview_json': b['previewJson'],
                            'idempotency_key': b['idemKey'], 'body_hash': b['bodyHash']})
                    if 'INSERT INTO mvp_p3_resolutions' in sql:
                        self.resolutions.append({'draft_id': b['draftId'], 'request_id': b['requestId'], 'action_type': b['actionType'],
                            'proposal_id': b['proposalId'], 'decision_id': b['decisionId'], 'idempotency_key': b['idemKey'], 'body_hash': b['bodyHash']})
                self.committed.extend(copy.deepcopy(self.pending))
            finally:
                self.pending.clear()
        self.store = ManualStore(SimpleNamespace(write=tx, read=tx), self.settings)
        for target in ('app.manual_store.rows','app.decisions.rows','app.storage.rows'):
            p = patch(target, side_effect=self.read); p.start(); self.addCleanup(p.stop)
        for target in ('app.manual_store.execute','app.decisions.execute','app.proposal_writer.execute'):
            p = patch(target, side_effect=self.execute); p.start(); self.addCleanup(p.stop)
        for p in (patch('app.manual_store.active_policy_version', side_effect=lambda *_a, **_k: self.source.policy.version),
                  patch('app.manual_store.collect_evidence', side_effect=lambda *_: self.source),
                  patch('app.decisions.prepare_assignment_notice')):
            p.start(); self.addCleanup(p.stop)

    def read(self, _, sql, **b):
        self.queries.append(sql)
        if sql.startswith('SELECT request_revision'):
            return [{'request_revision': self.revision, 'responsible_captain_id': self.actor.person_id, 'status': self.status,
                     'estimated_start_date': MON, 'estimated_completion_date': FRI, 'requested_lead_count': 1, 'requested_contributor_count': 0}]
        if sql.startswith('SELECT ur.person_id'):
            return [{'person_id': self.actor.person_id}] if self.permission else []
        if 'SELECT DISTINCT p.person_id' in sql:
            return [{'person_id': 'P-001', 'full_name': 'Selected Lead', 'role_code': 'POD_LEAD'}] if self.active else []
        if 'FROM mvp_p3_drafts' in sql:
            if 'idemKey' in b:
                return [d for d in self.drafts if d['idempotency_key'] == b['idemKey']]
            return self.drafts[-1:]
        if 'FROM mvp_p3_resolutions' in sql:
            return [r for r in self.resolutions if r['idempotency_key'] == b.get('idemKey') or r['draft_id'] == b.get('draftId')]
        if 'FROM agent_executions' in sql:
            return [{'execution_id': 'RUN-active'}] if self.running else []
        if 'MAX(proposal_version)' in sql:
            return [{'next_version': 1}]
        return []

    def execute(self, _, sql, binds, *args):
        self.pending.append((sql, binds))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError('Injected write failure')

    def preview(self, **changes):
        return self.store.preview(self.actor, self.request_id, ManualPreviewInput(**{
            'request_revision': 1, 'slots': (SLOT,), 'idempotency_key': 'manual_preview_key_0001', **changes}))

    def decide(self, draft, action='APPROVED', **changes):
        return self.store.decide(self.actor, self.request_id, ManualDecisionInput(**{
            'draft_id': draft['draft_id'], 'action': action, 'idempotency_key': 'manual_decision_key_0001', **changes}))

    def test_preview_creates_only_draft_and_audit_no_execution_proposal_or_capacity(self):
        draft = self.preview()
        self.assertEqual(len(self.committed), 2)
        self.assertTrue(all('mvp_p3_drafts' in sql or 'audit_events' in sql for sql, _ in self.committed))
        audit_sql, audit_binds = next((sql, binds) for sql, binds in self.committed if 'audit_events' in sql)
        self.assertIn('correlation_id', audit_sql.lower())
        self.assertIn(':auditId', audit_sql)
        self.assertTrue(audit_binds['auditId'])
        self.assertEqual(draft['members'][0]['source'], 'MANUAL')
        self.assertIsNone(draft['members'][0]['score'])
        self.assertFalse(draft['reserves_capacity'])
        self.assertEqual(self.store.get(self.actor, self.request_id)['draft']['draft_id'], draft['draft_id'])

    def test_approval_without_successful_agent_creates_real_manual_origin_and_exact_assignment(self):
        draft = self.preview()
        result = self.decide(draft)
        self.assertEqual(result['status'], 'APPROVED')
        proposals = [b for sql,b in self.committed if 'INSERT INTO pod_proposals' in sql]
        self.assertEqual(proposals[0]['originType'], 'MANUAL')
        self.assertIsNone(proposals[0]['executionId'])
        members = [b for sql,b in self.committed if 'INSERT INTO pod_proposal_members' in sql]
        self.assertIsNone(members[0]['scoreValue'])
        self.assertEqual(members[0]['manualFlag'], 'Y')
        assignments = [b for sql,b in self.committed if 'INSERT INTO pod_assignments' in sql]
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]['personId'], 'P-001')
        self.assertEqual(sum(b['assignedHours'] for sql,b in self.committed if 'INSERT INTO assignment_days' in sql), D(16))
        self.assertFalse(any('INSERT INTO agent_executions' in sql for sql,_ in self.committed))
        self.assertIsNone(self.store.get(self.actor, self.request_id)['draft'])

    def test_duplicate_preview_and_approval_replay_without_extra_writes(self):
        draft = self.preview()
        self.assertEqual(self.preview()['draft_id'], draft['draft_id'])
        result = self.decide(draft)
        count = len(self.committed)
        replay = self.decide(draft)
        self.assertEqual(replay['proposal_id'], result['proposal_id'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(len(self.committed), count)
        with self.assertRaises(ServiceError):
            self.decide(draft, reason='Changed payload')

    def test_stale_workload_requires_recalculation_not_silent_new_numbers(self):
        draft = self.preview()
        self.source = single('16', '25')
        with self.assertRaises(ServiceError) as error:
            self.decide(draft)
        self.assertEqual(error.exception.code, 'SELECTION_REFRESH_REQUIRED')
        self.assertEqual(len(self.committed), 2)
        with self.assertRaises(ServiceError) as error:
            self.preview(previous_draft_id=draft['draft_id'], idempotency_key='new_manual_preview_key')
        self.assertEqual(error.exception.code, 'MANUAL_CAPACITY_EXCEEDED')

    def test_partial_write_failures_roll_back_final_proposal_assignments_and_resolution(self):
        draft = self.preview()
        for failure in ('INSERT INTO pod_proposals','INSERT INTO pod_proposal_members','INSERT INTO approval_decisions',
                        'INSERT INTO assignment_days','INSERT INTO mvp_p3_resolutions', 'INSERT INTO audit_events'):
            self.fail_on = failure
            with self.subTest(failure=failure), self.assertRaises(RuntimeError):
                self.decide(draft)
            self.assertEqual(len(self.committed), 2)
            self.assertFalse(self.resolutions)

    def test_running_job_and_wrong_request_revision_stop_preview(self):
        self.running = True
        with self.assertRaises(ServiceError): self.preview()
        self.running = False
        with self.assertRaises(ServiceError): self.preview(request_revision=2)
        self.assertFalse(self.committed)

    def test_permissions_and_disabled_account_rechecked_at_approval(self):
        draft = self.preview()
        self.permission = False
        with self.assertRaises(ServiceError): self.decide(draft)
        self.permission = True
        self.active = False
        with self.assertRaises(ServiceError): self.decide(draft)
        self.assertEqual(len(self.committed), 2)

    def test_non_captain_cannot_read_preview_or_decide(self):
        for role in ('POD_MEMBER','POD_LEAD','SYSTEM_ADMINISTRATOR'):
            self.actor = captain(role=role)
            with self.subTest(role=role), self.assertRaises(ServiceError): self.preview()
            with self.assertRaises(ServiceError): self.store.get(self.actor, self.request_id)
        self.assertFalse(self.committed)

    def test_discard_is_audited_releases_draft_fence_no_assignment(self):
        draft = self.preview()
        result = self.decide(draft, 'DISCARDED')
        self.assertEqual(result['status'], 'DISCARDED')
        self.assertFalse(any('INSERT INTO pod_proposals' in sql or 'INSERT INTO pod_assignments' in sql for sql,_ in self.committed))
        self.assertIsNone(self.store.get(self.actor, self.request_id)['draft'])

    def test_reject_requires_reason_and_keeps_manual_history_without_assignments(self):
        draft = self.preview()
        with self.assertRaises(ServiceError): self.decide(draft, 'REJECTED')
        self.decide(draft, 'REJECTED', reason='Different delivery owner needed')
        self.assertFalse(any('INSERT INTO pod_assignments' in sql for sql,_ in self.committed))
        self.assertEqual(self.resolutions[0]['action_type'], 'REJECTED')

    def test_optimistic_revision_and_tampered_fields_cannot_broaden_scope(self):
        draft = self.preview()
        with self.assertRaises(ServiceError): self.preview(idempotency_key='new_preview_key_0002')
        with self.assertRaises(ValidationError):
            ManualPreviewInput(request_revision=1, slots=(SLOT,), idempotency_key='manual_input_key_123', actor_subject='spoof')
        with self.assertRaises(ValidationError):
            ManualSlot(person_id='P-001', role='POD_LEAD', manual='true')
        with self.assertRaises(ServiceError):
            self.preview(previous_draft_id=draft['draft_id'], slots=(SLOT.model_copy(update={'manual': False}),), idempotency_key='new_preview_key_0002')

    def test_refresh_creates_append_only_revision_and_old_tab_cannot_approve(self):
        first = self.preview()
        second = self.preview(previous_draft_id=first['draft_id'], idempotency_key='manual_preview_key_0002')
        self.assertEqual(second['revision'], 2)
        self.assertEqual(len(self.drafts), 2)
        with self.assertRaises(ServiceError) as e: self.decide(first)
        self.assertEqual(e.exception.code, 'STALE_SELECTION')
        self.assertEqual(self.decide(second)['status'], 'APPROVED')

    def test_captain_can_preview_another_captains_request(self):
        self.actor = captain(person_id='P-other')
        # The request still belongs to the original Captain, not to the caller.
        original_read = self.read
        def read(c, sql, **b):
            found = original_read(c, sql, **b)
            if sql.startswith('SELECT request_revision'): found[0]['responsible_captain_id'] = 'P-010'
            return found
        with patch('app.manual_store.rows', side_effect=read):
            result = self.preview()
        self.assertTrue(result['draft_id'])

    def test_mixed_manual_preview_pins_original_normal_slots_and_recalculates_hours(self):
        self.source = roster().model_copy(update={'policy': self.source.policy})
        selected = exact_team(self.source, ('P-001',), ('P-004', 'P-005'))
        review = snapshot(self.source, selected, selected, 2000)
        original_read = self.read
        def read(c, sql, **b):
            if sql.startswith('SELECT request_id,request_revision,status,policy_version'):
                return [{'request_id': self.request_id, 'request_revision': 1, 'status': 'READY_FOR_REVIEW', 'policy_version': self.source.policy.version}]
            if 'SELECT DISTINCT p.person_id' in sql:
                return [{'person_id': p.person_id, 'full_name': self.source.names[p.person_id], 'role_code': p.roles[0].code} for p in self.source.candidates]
            return original_read(c, sql, **b)
        slots = (SLOT, ManualSlot(person_id='P-004', role='POD_MEMBER', manual=False), ManualSlot(person_id='P-005', role='POD_MEMBER', manual=False))
        with patch('app.manual_store.rows', side_effect=read), patch('app.manual_store.load_review', return_value=(review, review, None)):
            draft = self.preview(source_proposal_id='PP-original', slots=slots)
            self.assertEqual(draft['source_proposal_id'], 'PP-original')
            self.assertEqual(len(draft['original_members']), 3)
            self.assertEqual(sum(m['planned_hours'] for m in draft['members']), D(24))
            self.assertIsNone(draft['members'][0]['score'])
            self.assertTrue(all(m['score'] is not None for m in draft['members'][1:]))
            with self.assertRaises(ServiceError) as error:
                self.preview(source_proposal_id='PP-original', previous_draft_id=draft['draft_id'],
                    slots=(SLOT, slots[1], slots[2].model_copy(update={'person_id': 'P-006'})), idempotency_key='mixed_preview_new_key')
            self.assertEqual(error.exception.code, 'INVALID_SELECTION')


class ManualQueueFenceTests(unittest.TestCase):
    def test_saved_manual_draft_blocks_explicit_and_automatic_reruns_before_writes(self):
        @contextmanager
        def write():
            yield None
        store = ExecutionStore(SimpleNamespace(write=write), SimpleNamespace())
        request = {'request_revision': 1, 'responsible_captain_id': 'P-010', 'status': 'NEEDS_RECOMMENDATION', 'agent_enabled': 'Y'}
        def read(_, sql, **binds):
            return [request] if 'FROM requests' in sql else []
        with patch.object(store, 'require_enabled'), patch('app.execution_store.active_policy_version', return_value='policy-1'), \
             patch('app.execution_store.assert_captain'), patch('app.execution_store.rows', side_effect=read), \
             patch('app.manual_store.pending_manual', return_value={'draft_id': 'MD-1'}), patch('app.execution_store.execute') as execute:
            for automatic in (False, True):
                with self.subTest(automatic=automatic), self.assertRaises(ServiceError) as error:
                    store.enqueue('REQ-1', 'captain-subject', 'P-010', 'manual_fence_key_001', automatic=automatic)
                self.assertEqual(error.exception.code, 'MANUAL_DRAFT_ACTIVE')
            execute.assert_not_called()


class ManualApiTests(unittest.TestCase):
    def setUp(self):
        self.auth, self.manual = MagicMock(), MagicMock()
        self.auth.resolve.return_value = captain()
        settings = Settings(backend_env='test', backend_auth_mode='local', backend_local_token='x'*32, backend_local_subject='captain-subject')
        self.client = TestClient(create_app(settings, MagicMock(), authorization=self.auth, manual=self.manual))
        self.headers = {'Authorization': 'Bearer ' + 'x'*32}
        self.preview = {'request_revision': 1, 'slots': [SLOT.model_dump(mode='json')], 'idempotency_key': 'manual_preview_key_0001'}
        self.decision = {'draft_id': 'MD-1', 'action': 'APPROVED', 'idempotency_key': 'manual_decision_key_0001'}

    def test_only_verified_captain_calls_manual_operations(self):
        self.manual.get.return_value = {'people': [], 'draft': None}
        self.manual.preview.return_value = {'draft_id': 'MD-1'}
        self.manual.decide.return_value = {'status': 'APPROVED'}
        self.assertEqual(self.client.get('/v1/requests/REQ-1/manual', headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post('/v1/requests/REQ-1/manual-preview', headers=self.headers, json=self.preview).status_code, 200)
        self.assertEqual(self.client.post('/v1/requests/REQ-1/manual-decision', headers=self.headers, json=self.decision).status_code, 200)
        self.assertEqual(self.manual.preview.call_args.args[0].subject, 'captain-subject')

    def test_api_denies_member_lead_admin_and_unsigned_call(self):
        for role in ('POD_MEMBER','POD_LEAD','SYSTEM_ADMINISTRATOR'):
            self.auth.resolve.return_value = captain(role)
            self.assertEqual(self.client.get('/v1/requests/REQ-1/manual', headers=self.headers).status_code, 403)
            for endpoint, body in (('manual-preview', self.preview), ('manual-decision', self.decision)):
                self.assertEqual(self.client.post(f'/v1/requests/REQ-1/{endpoint}', headers=self.headers, json=body).status_code, 403)
        self.assertEqual(self.client.get('/v1/requests/REQ-1/manual').status_code, 401)
        self.manual.get.assert_not_called(); self.manual.preview.assert_not_called(); self.manual.decide.assert_not_called()

    def test_client_cannot_supply_hours_scores_ceiling_or_identity(self):
        for extra in ({'maximum_pct': 150}, {'actor_subject': 'other-captain'}, {'planned_hours': 50}, {'score': 100}):
            self.assertEqual(self.client.post('/v1/requests/REQ-1/manual-preview', headers=self.headers, json={**self.preview, **extra}).status_code, 422)
        self.manual.preview.assert_not_called()


if __name__ == '__main__':
    unittest.main()
