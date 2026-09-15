"""Offline Phase-5 authorization, capacity and lifecycle tests. No Oracle/OCI/email calls."""
import json
import unittest
from contextlib import contextmanager
from datetime import date, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from app.assignments import AssignmentStore, CloseProject, scope_clause
from app.auth import Actor, Permission
from app.capacity import CapacityLedger
from app.capacity_admin import build_days
from app.errors import ServiceError
from app.notifications import prepare_assignment_notice
from app.policy import DEFAULT_POLICY


def actor(role='POD_LEAD', scope='SCOPED'):
    permission = SimpleNamespace(role=role, scope=scope, actions=frozenset({'view','update'}), resource='REQUESTS')
    return SimpleNamespace(person_id='P-006', subject='real-subject', roles={role}, permissions=(permission,), require=MagicMock(return_value=permission))


class ScopeTests(unittest.TestCase):
    def test_captain_is_scoped_by_responsible_captain_not_request_source(self):
        clause, binds = scope_clause(actor('POD_CAPTAIN', 'FULL'), 'REQUESTS')
        self.assertEqual(clause, 'r.responsible_captain_id=:viewerId')
        self.assertEqual(binds, {'viewerId': 'P-006'})

    def test_lead_even_with_full_permission_needs_final_lead_assignment(self):
        clause, _ = scope_clause(actor('POD_LEAD', 'FULL'), 'REQUESTS')
        self.assertIn("mine.role_in_pod='POD_LEAD'", clause)
        self.assertIn("mine.status IN ('CONFIRMED','CLOSED')", clause)
        self.assertNotIn('recommendations', clause)

    def test_member_needs_final_assignment_and_admin_needs_full(self):
        self.assertIn('mine.person_id=:viewerId', scope_clause(actor('POD_MEMBER'), 'REQUESTS')[0])
        self.assertEqual(scope_clause(actor('SYSTEM_ADMINISTRATOR', 'FULL'), 'REPORTS'), ('1=1', {}))
        self.assertNotEqual(scope_clause(actor('SYSTEM_ADMINISTRATOR', 'OWN'), 'REPORTS')[0], '1=1')

    def test_locked_permission_stops_before_query(self):
        user = actor(); user.require.side_effect = ServiceError('FORBIDDEN', 'No access', 403)
        with self.assertRaises(ServiceError): scope_clause(user, 'REPORTS')


class CapacityRefreshTests(unittest.TestCase):
    start, end = date(2026,9,14), date(2026,9,18)

    def event(self, kind='NON_AVAILABILITY', hours=8):
        return {'capacity_kind': kind, 'allocated_hours': hours, 'starts_on': self.start, 'ends_on': self.start}

    def test_expands_full_week_and_separates_external_work_from_absence(self):
        days = build_days(40, self.start, self.end, [self.event(), self.event('EXTERNAL_WORK', 2)])
        self.assertEqual(len(days), 7)
        self.assertEqual(days[self.start], {'available': Decimal(0), 'external': Decimal(2)})
        self.assertEqual(days[date(2026,9,20)]['available'], 0)

    def test_unknown_weekly_hours_not_treated_as_free(self):
        for hours in (None, 0, 81):
            with self.assertRaises(ServiceError): build_days(hours, self.start, self.end, [])

    def test_legacy_unknown_or_zero_events_require_review(self):
        for event in (self.event('UNKNOWN'), self.event(hours=0)):
            with self.assertRaises(ServiceError): build_days(40, self.start, self.end, [event])

    def test_overlapping_absences_are_not_silently_clamped(self):
        with self.assertRaises(ServiceError): build_days(40, self.start, self.end, [self.event(), self.event()])

    def test_excessive_refresh_range_rejected(self):
        with self.assertRaises(ServiceError): build_days(40, self.start, date(2027,1,1), [])


class WorkspaceTests(unittest.TestCase):
    def test_own_calendar_filters_assignments_and_days_and_never_loads_directory(self):
        statements = []
        @contextmanager
        def read(): yield None
        user = actor('POD_MEMBER', 'OWN')
        def query(_conn, sql, **binds):
            statements.append((sql, binds))
            if 'AS pending_review' in sql: return [{'pending_review':0,'approved':0,'rejected':0}]
            if 'AS total' in sql: return [{'total':0}]
            if "p.active_flag='Y' AND NOT" in sql:
                self.assertEqual(binds, {'profileViewerId': 'P-006'})
                return [{'person_id': 'P-006'}]
            return []
        with patch('app.assignments.rows', side_effect=query), patch('app.assignments.load_policy', return_value=DEFAULT_POLICY), patch('app.assignments.ZoneInfo', return_value=timezone.utc), patch('app.assignments.load_capacity_ledger', return_value=(CapacityLedger(),0)):
            result = AssignmentStore(SimpleNamespace(read=read), SimpleNamespace(staffing_policy_version='draft')).workspace(user, date(2026,9,16), 'ALLOCATION_CALENDAR')
        self.assertEqual(result['week_start'], date(2026,9,14))
        self.assertEqual(len(result['people']), 1)
        scoped = [(s,b) for s,b in statements if 'JOIN requests r' in s and ('SELECT a.assignment_id' in s or 'SELECT d.assignment_id' in s)]
        self.assertEqual(len(scoped), 2)
        self.assertTrue(all('a.person_id=:ownId' in s and b['ownId']=='P-006' for s,b in scoped))
        self.assertFalse(any(s == "SELECT person_id FROM people WHERE active_flag='Y'" for s,_ in statements))

    def test_unknown_capacity_returns_null_not_free_capacity(self):
        @contextmanager
        def read(): yield None
        def query(_conn, sql, **binds):
            if 'AS pending_review' in sql: return [{'pending_review':0,'approved':0,'rejected':0}]
            if 'AS total' in sql: return [{'total':1}]
            if "p.active_flag='Y' AND NOT" in sql: return [{'person_id': 'P-006'}]
            return []
        with patch('app.assignments.rows', side_effect=query), patch('app.assignments.load_policy', return_value=DEFAULT_POLICY), patch('app.assignments.ZoneInfo', return_value=timezone.utc), patch('app.assignments.load_capacity_ledger', side_effect=ServiceError('CAPACITY_STALE','Refresh',409)):
            result = AssignmentStore(SimpleNamespace(read=read), SimpleNamespace(staffing_policy_version='draft')).workspace(actor(), date(2026,9,16))
        self.assertIsNone(result['people'][0]['allocation_pct'])
        self.assertEqual(result['people'][0]['capacity_status'], 'CAPACITY_STALE')


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.user = actor()
        self.commands, self.committed = [], []
        self.query_log, self.command_binds = [], []
        self.status, self.revision = 'STAFFED', 3
        self.members = [{'assignment_id':'AS-1','person_id':'P-006','role_in_pod':'POD_LEAD','status':'CONFIRMED','close_reason':None},
                        {'assignment_id':'AS-2','person_id':'P-007','role_in_pod':'POD_MEMBER','status':'CONFIRMED','close_reason':None}]
        self.linked, self.fail = True, False
        @contextmanager
        def write():
            yield None
            self.committed.extend(self.commands)
        self.store = AssignmentStore(SimpleNamespace(write=write), SimpleNamespace(staffing_decisions_enabled=True))
        def read(_connection, sql, **binds):
            self.query_log.append((sql, binds))
            if sql.startswith('SELECT status'): return [{'status': self.status, 'request_revision': self.revision}]
            if sql.startswith('SELECT ur.person_id'): return [{'person_id':'P-006'}] if self.linked else []
            if sql.startswith('SELECT assignment_id'): return self.members
            return []
        def execute(_connection, sql, *args):
            self.commands.append(sql)
            self.command_binds.append(args[0])
            if self.fail and 'audit_events' in sql: raise RuntimeError('Injected audit failure')
        for p in (patch('app.assignments.rows', side_effect=read), patch('app.assignments.execute', side_effect=execute)):
            p.start(); self.addCleanup(p.stop)

    def close(self, **values):
        return self.store.close(self.user, 'REQ-1', CloseProject(request_revision=values.get('revision',3), reason=values.get('reason','Work completed')))

    def test_close_updates_assignments_request_audit_and_retains_days(self):
        self.assertEqual(self.close()['status'], 'CLOSED')
        self.assertEqual(len(self.committed), 3)
        self.assertIn("agent_enabled='N'", self.committed[1])
        self.assertFalse(any('DELETE' in s or 'UPDATE assignment_days' in s for s in self.committed))

    def test_unassigned_lead_and_revoked_mapping_cannot_close(self):
        self.user.person_id = 'OTHER'
        with self.assertRaises(ServiceError): self.close()
        self.user.person_id = 'P-006'; self.linked = False
        with self.assertRaises(ServiceError): self.close()
        self.assertFalse(self.committed)

    def test_stale_revision_or_blank_note_cannot_close(self):
        with self.assertRaises(ServiceError): self.close(revision=2)
        with self.assertRaises(ValidationError): self.close(reason='  ')
        self.assertFalse(self.committed)

    def test_audit_failure_rolls_back_closure(self):
        self.fail = True
        with self.assertRaises(RuntimeError): self.close()
        self.assertFalse(self.committed)

    def test_same_closure_replays_without_extra_writes(self):
        self.status = 'CLOSED'
        self.members = [{**m, 'status':'CLOSED', 'close_reason':'Work completed'} for m in self.members]
        self.assertTrue(self.close()['replayed'])
        self.assertFalse(self.committed)
        with self.assertRaises(ServiceError): self.close(reason='Different note')

    def test_closure_uses_database_clock_and_audits_next_day_planned_hours_rule(self):
        self.close()
        self.assertIn('closed_at=SYSTIMESTAMP', self.commands[0])
        audit = json.loads(self.command_binds[-1]['afterJson'])
        self.assertEqual(audit['capacity_rule'], 'PRESERVE_THROUGH_CLOSURE_DAY_RELEASE_LATER')
        self.assertEqual(audit['closure_date_basis'], 'ASSIGNMENT_POLICY_TIMEZONE')
        self.assertEqual(audit['workload_basis'], 'PLANNED_HOURS')
        self.assertEqual(audit['assignment_ids'], ['AS-1', 'AS-2'])

    def test_locks_request_and_all_people_in_sorted_order(self):
        self.members.reverse()
        self.close()
        self.assertIn('FOR UPDATE WAIT 5', self.query_log[0][0])
        people_locks = [binds['personId'] for sql, binds in self.query_log if sql.startswith('SELECT person_id FROM people')]
        self.assertEqual(people_locks, ['P-006', 'P-007'])

    def test_client_cannot_backdate_closure_or_supply_partial_day_hours(self):
        for extra in ({'closed_at': '2026-09-01T00:00:00Z'}, {'completion_date': '2026-09-01'}, {'actual_hours': 3}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                CloseProject(request_revision=3, reason='Done', **extra)

    def test_member_captain_and_admin_cannot_close_even_with_update_permission(self):
        for role in ('POD_MEMBER', 'POD_CAPTAIN', 'SYSTEM_ADMINISTRATOR'):
            self.user = Actor('subject', 'P-006', frozenset({role}),
                (Permission(role, 'REQUESTS', 'FULL', frozenset({'view', 'update'})),))
            with self.subTest(role=role), self.assertRaises(ServiceError):
                self.close()
        self.assertFalse(self.commands)

    def test_decisions_disabled_and_unstaffed_requests_cannot_close(self):
        self.store.settings.staffing_decisions_enabled = False
        with self.assertRaises(ServiceError):
            self.close()
        self.assertFalse(self.query_log)
        self.store.settings.staffing_decisions_enabled = True
        for status in ('NEEDS_RECOMMENDATION', 'IN_REVIEW'):
            self.status = status
            with self.subTest(status=status), self.assertRaises(ServiceError):
                self.close()
        self.assertFalse(self.committed)


class OutboxTests(unittest.TestCase):
    def test_no_email_still_creates_disabled_intent_without_sensitive_evidence(self):
        member = SimpleNamespace(person_id='P-006', role=SimpleNamespace(value='POD_LEAD'), hours=12)
        with patch('app.notifications.rows', return_value=[{'email_address': None}]), patch('app.notifications.execute') as write:
            prepare_assignment_notice(None, 'DC1', 'PP1', 'REQ1', member, 'AS1')
            sql, binds = write.call_args.args[1:3]
            self.assertIn("'DISABLED'", sql)
            self.assertEqual(binds['errorCode'], 'RECIPIENT_EMAIL_REQUIRED')
            self.assertIsNone(binds['emailAddress'])
            self.assertNotIn('evidence', binds['payloadJson'])

    def test_valid_email_does_not_enable_delivery(self):
        member = SimpleNamespace(person_id='P-006', role=SimpleNamespace(value='POD_LEAD'), hours=12)
        with patch('app.notifications.rows', return_value=[{'email_address': 'person@example.test'}]), patch('app.notifications.execute') as write:
            prepare_assignment_notice(None, 'DC1', 'PP1', 'REQ1', member, 'AS1')
            self.assertIn("'DISABLED'", write.call_args.args[1])
            self.assertEqual(write.call_args.args[2]['dedupKey'], 'DC1:P-006:POD_ASSIGNED')
