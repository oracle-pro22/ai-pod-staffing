"""Exact slot grants and account eligibility; offline, no Oracle/model calls."""
import sqlite3
import unittest
from decimal import Decimal
from unittest.mock import patch

from test_mvp_phase2 import roster
from test_rules import FRI, MON

from app.alternatives import exact_team, replacement_options
from app.capacity import CapacityLedger
from app.contracts import PodRole
from app.errors import ServiceError
from app.evidence import collect_evidence
from app.explicit_role_policy import migration_sql, policy_from_document, revised_policy
from app.manual_planning import ManualSlot, manual_plan
from app.manual_store import ManualStore
from app.rules import eligible_for_slot, validate_pod


class ExplicitSlotTests(unittest.TestCase):
    def setUp(self):
        self.bundle = roster()
        # Deliberately frozen legacy policy: it is not permission to inherit slots.
        self.bundle = self.bundle.model_copy(update={'policy': self.bundle.policy.model_copy(update={
            'member_role_codes': ('POD_MEMBER', 'POD_LEAD')})})

    def test_captain_lead_never_inherits_member_even_from_legacy_policy(self):
        person = self.bundle.candidates[0]
        roles = (*person.roles, person.roles[0].model_copy(update={'code': 'POD_CAPTAIN'}))
        person = person.model_copy(update={'roles': roles})
        self.assertTrue(eligible_for_slot(person, PodRole.LEAD, self.bundle.request))
        self.assertFalse(eligible_for_slot(person, PodRole.MEMBER, self.bundle.request))
        with self.assertRaises(ServiceError):
            exact_team(self.bundle, ('P-003',), ('P-001', 'P-009'))

    def test_alternatives_never_offer_lead_only_person_as_member(self):
        selected = exact_team(self.bundle, ('P-001',), ('P-004', 'P-005'))
        result = replacement_options(self.bundle, selected)
        self.assertFalse({r.person_id for r in result.replacements if r.role == PodRole.MEMBER} & {'P-002', 'P-003'})

    def test_manual_cannot_bypass_explicit_role(self):
        slots = (ManualSlot(person_id='P-003', role='POD_LEAD', manual=True),
                 ManualSlot(person_id='P-001', role='POD_MEMBER', manual=True),
                 ManualSlot(person_id='P-009', role='POD_MEMBER', manual=True))
        with self.assertRaises(ServiceError) as error:
            manual_plan(self.bundle, slots)
        self.assertEqual(error.exception.code, 'ROLE_INELIGIBLE')

    def test_final_gate_rejects_removed_member_grant_with_unchanged_legacy_policy(self):
        dual = self.bundle.candidates[0].model_copy(update={'roles': (*self.bundle.candidates[0].roles,
            self.bundle.candidates[3].roles[0])})
        approved_evidence = self.bundle.model_copy(update={'candidates': (dual, *self.bundle.candidates[1:])})
        option = exact_team(approved_evidence, ('P-003',), ('P-001', 'P-009'))
        before = self.bundle.policy.model_dump_json()
        issues = validate_pod(self.bundle.request, option.proposal, self.bundle.candidates,
            self.bundle.ledgers, self.bundle.policy, catalogue=self.bundle.catalogue)
        self.assertIn(('ROLE_INELIGIBLE', 'P-001'), {(i.code, i.person_id) for i in issues})
        self.assertEqual(before, self.bundle.policy.model_dump_json())

    def test_explicit_dual_grants_allow_either_slot_but_not_both(self):
        person = self.bundle.candidates[0].model_copy(update={'roles': (*self.bundle.candidates[0].roles,
            self.bundle.candidates[3].roles[0])})
        self.assertTrue(all(eligible_for_slot(person, role, self.bundle.request) for role in PodRole))
        with self.assertRaises(ServiceError):
            exact_team(self.bundle, ('P-001',), ('P-001', 'P-004'))

    def test_expiring_grant_cannot_cover_whole_request(self):
        person = self.bundle.candidates[3]
        person = person.model_copy(update={'roles': (person.roles[0].model_copy(update={'ends_on': MON}),)})
        self.assertFalse(eligible_for_slot(person, PodRole.MEMBER, self.bundle.request))

    def test_inactive_and_captain_only_cannot_fill_any_slot(self):
        person = self.bundle.candidates[0]
        captain_only = person.model_copy(update={'roles': (person.roles[0].model_copy(update={'code':'POD_CAPTAIN'}),)})
        for candidate in (person.model_copy(update={'active':False}), captain_only):
            self.assertFalse(any(eligible_for_slot(candidate, role, self.bundle.request) for role in PodRole))


class AccountEvidenceTests(unittest.TestCase):
    """Execute actual candidate/pool predicates against isolated in-memory rows."""
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE people(person_id TEXT,full_name TEXT,active_flag TEXT,
              skills_version INTEGER,workload_version INTEGER,availability_version INTEGER,deliverable_experience_json TEXT);
            CREATE TABLE app_accounts(person_id TEXT,identity_subject TEXT,active_flag TEXT);
            CREATE TABLE app_user_roles(person_id TEXT,identity_subject TEXT,role_code TEXT,active_flag TEXT,effective_from TEXT,effective_to TEXT);
            CREATE TABLE app_roles(role_code TEXT,active_flag TEXT);
            CREATE TABLE roster_onboarding(person_id TEXT,status TEXT);
        ''')
        self.db.executemany('INSERT INTO app_roles VALUES(?,?)', [('POD_LEAD','Y'),('POD_MEMBER','Y'),('POD_CAPTAIN','Y')])
        for pid in range(1, 7):
            person = f'P-{pid:03}'
            self.db.execute('INSERT INTO people VALUES(?,?,?,?,?,?,?)', (person,person,'N' if pid == 3 else 'Y',1,1,1,None))
            if pid != 6:
                self.db.execute('INSERT INTO app_accounts VALUES(?,?,?)', (person, f'acct:{person}', 'N' if pid == 2 else 'Y'))
            self.db.execute('INSERT INTO app_user_roles VALUES(?,?,?,?,?,?)', (person,
                'obsolete:subject' if pid == 4 else f'acct:{person}', 'POD_LEAD','Y', MON.isoformat(),
                MON.isoformat() if pid == 5 else None))
        self.db.execute('INSERT INTO app_user_roles VALUES(?,?,?,?,?,?)', ('P-001','acct:P-001','POD_MEMBER','Y',MON.isoformat(),None))
        # An old subject must not add Captain-derived capability to the active account.
        self.db.execute('INSERT INTO app_user_roles VALUES(?,?,?,?,?,?)', ('P-001','old:subject','POD_CAPTAIN','Y',MON.isoformat(),None))

    def sql_rows(self, _connection, sql, **binds):
        binds = {key: value.isoformat() if hasattr(value, 'isoformat') else value for key, value in binds.items()}
        records = [dict(row) for row in self.db.execute(sql, binds).fetchall()]
        if 'ur.effective_from' in sql and 'p.person_id' not in sql:
            from datetime import date
            for row in records:
                row['effective_from'] = date.fromisoformat(row['effective_from'])
                row['effective_to'] = date.fromisoformat(row['effective_to']) if row['effective_to'] else None
        return records

    def test_manual_pool_one_person_exact_roles_excludes_disabled_inactive_unmatched_expired_missing(self):
        store = ManualStore(None, None)
        with patch('app.manual_store.rows', side_effect=self.sql_rows):
            pool = store.pool(None, {'estimated_start_date': MON, 'estimated_completion_date': FRI})
        self.assertEqual(pool, [{'person_id': 'P-001', 'full_name': 'P-001', 'role_codes': ['POD_LEAD','POD_MEMBER']}])

    def test_manual_pool_excludes_only_unfinished_setup(self):
        for state in ('DRAFT', 'REVIEW', 'COMPLETE'):
            self.db.execute('DELETE FROM roster_onboarding')
            self.db.execute('INSERT INTO roster_onboarding VALUES(?,?)', ('P-001', state))
            with patch('app.manual_store.rows', side_effect=self.sql_rows):
                pool = ManualStore(None, None).pool(None, {'estimated_start_date': MON, 'estimated_completion_date': FRI})
            self.assertEqual(bool(pool), state in ('REVIEW', 'COMPLETE'))

    def test_normal_evidence_uses_same_account_and_subject_authority(self):
        source = roster()
        req = source.request
        def read(c, sql, **binds):
            if 'FROM people p' in sql or 'FROM app_user_roles ur' in sql:
                return self.sql_rows(c, sql, **binds)
            if 'FROM requests' in sql:
                return [{'project_description':'Launch','business_objectives':'Launch','expected_outcomes':'Launch','project_type_id':'TYPE-1'}]
            if 'FROM deliverables' in sql:
                return [{'deliverable_id':'DEL-001','deliverable_name':'Launch','project_type_id':'TYPE-1','customer_note':''}]
            return []
        with patch('app.evidence.rows', side_effect=read), patch('app.evidence.load_request_snapshot', return_value=req), \
             patch('app.evidence.load_policy', return_value=source.policy), \
             patch('app.evidence.load_capacity_ledger', return_value=(CapacityLedger(),1)):
            result = collect_evidence(None, req.request_id, source.policy.version)
        self.assertEqual([p.person_id for p in result.candidates], ['P-001'])
        self.assertEqual({r.code for r in result.candidates[0].roles}, {'POD_LEAD','POD_MEMBER'})


class PolicyRevisionTests(unittest.TestCase):
    def setUp(self):
        self.old = roster().policy.model_copy(update={'status':'APPROVED','approved_by':'original',
            'approved_at':'2026-09-01T00:00:00Z','member_role_codes':('POD_MEMBER','POD_LEAD')})

    def test_revision_changes_only_role_rules_and_approval_metadata(self):
        before = self.old.model_dump_json()
        new = revised_policy(self.old, 'staffing-exact-roles-v1', 'reviewer', '2026-09-23T00:00:00Z')
        self.assertEqual(new.member_role_codes, ('POD_MEMBER',))
        self.assertEqual(new.maximum_allocation_pct, Decimal(85))
        for field in ('weights','scheduling','default_weekly_hours','minimum_strength','maximum_agent_steps','scheduling_timezone'):
            self.assertEqual(getattr(new,field),getattr(self.old,field))
        self.assertEqual(self.old.model_dump_json(), before)
        sql = migration_sql(self.old, new)
        self.assertNotIn('UPDATE staffing_policy_control',sql)
        self.assertNotIn('UPDATE staffing_runtime',sql)
        self.assertIn("USER<>'AI_POD_STAFFING'",sql)
        self.assertIn("agents_enabled='N' AND notifications_enabled='N'",sql)
        self.assertIn("status IN ('QUEUED','RUNNING')",sql)
        self.assertIn('FOR UPDATE NOWAIT',sql)
        self.assertIn('WHERE policy_version=\'staffing-exact-roles-v1\' AND rule_code=\'MEMBER_ROLES\'',sql)
        self.assertIn('WHENEVER SQLERROR EXIT FAILURE ROLLBACK',sql)

    def test_invalid_revision_and_unrelated_policy_changes_rejected(self):
        for version in (self.old.version,"new'; DELETE",''):
            with self.assertRaises(ValueError):
                revised_policy(self.old,version,'reviewer','2026-09-23T00:00:00Z')
        new = revised_policy(self.old,'exact-v1','reviewer','2026-09-23T00:00:00Z')
        with self.assertRaises(ValueError):
            migration_sql(self.old,new.model_copy(update={'maximum_allocation_pct':Decimal(100)}))

    def test_accepts_bare_policy_or_read_only_audit_wrapper(self):
        document = self.old.model_dump(mode='json')
        self.assertEqual(policy_from_document(document),self.old)
        self.assertEqual(policy_from_document({'active_policy':document,'writes':0}),self.old)


if __name__ == '__main__':
    unittest.main()
