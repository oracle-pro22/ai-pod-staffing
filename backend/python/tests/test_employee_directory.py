"""Employee-directory filtering; no Oracle writes, authentication changes or network."""
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.assignments import ADMINISTRATOR_ONLY_SQL, AssignmentStore
from app.capacity import CapacityLedger
from app.policy import DEFAULT_POLICY


class EffectiveEmployeePredicateTests(unittest.TestCase):
    def test_effective_admin_only_predicate_preserves_employees_and_unassigned_people(self):
        # Execute the production predicate in an in-memory SQL database, replacing
        # only Oracle's current-day expression with an equivalent bound date.
        with sqlite3.connect(':memory:') as connection:
            connection.executescript('''CREATE TABLE people(person_id TEXT);
                CREATE TABLE app_roles(role_code TEXT,active_flag TEXT);
                CREATE TABLE app_user_roles(person_id TEXT,role_code TEXT,active_flag TEXT,effective_from TEXT,effective_to TEXT);''')
            for role in ('SYSTEM_ADMINISTRATOR', 'POD_CAPTAIN', 'POD_LEAD', 'POD_MEMBER'):
                connection.execute('INSERT INTO app_roles VALUES (?,?)', (role, 'Y'))
            connection.executemany('INSERT INTO people VALUES (?)', [(name,) for name in (
                'admin', 'mixed', 'new', 'future_admin', 'expired_admin', 'inactive_admin', 'future_member', 'inactive_member')])
            assignments = [
                ('admin', 'SYSTEM_ADMINISTRATOR', 'Y', '2026-01-01', None),
                ('mixed', 'SYSTEM_ADMINISTRATOR', 'Y', '2026-01-01', None),
                ('mixed', 'POD_MEMBER', 'Y', '2026-01-01', None),
                ('future_admin', 'SYSTEM_ADMINISTRATOR', 'Y', '2026-09-15', None),
                ('expired_admin', 'SYSTEM_ADMINISTRATOR', 'Y', '2026-01-01', '2026-09-13'),
                ('inactive_admin', 'SYSTEM_ADMINISTRATOR', 'N', '2026-01-01', None),
                ('future_member', 'SYSTEM_ADMINISTRATOR', 'Y', '2026-01-01', None),
                ('future_member', 'POD_MEMBER', 'Y', '2026-09-15', None),
                ('inactive_member', 'SYSTEM_ADMINISTRATOR', 'Y', '2026-01-01', None),
                ('inactive_member', 'POD_MEMBER', 'N', '2026-01-01', None),
            ]
            connection.executemany('INSERT INTO app_user_roles VALUES (?,?,?,?,?)', assignments)
            sql = f'SELECT p.person_id FROM people p WHERE NOT ({ADMINISTRATOR_ONLY_SQL}) ORDER BY p.person_id'
            sql = sql.replace('TRUNC(SYSDATE)', ':current_day')
            result = [item[0] for item in connection.execute(sql, {'current_day': '2026-09-14'})]
            self.assertEqual(result, ['expired_admin', 'future_admin', 'inactive_admin', 'mixed', 'new'])
            connection.execute("UPDATE app_roles SET active_flag='N' WHERE role_code='SYSTEM_ADMINISTRATOR'")
            self.assertEqual(len(connection.execute(sql, {'current_day': '2026-09-14'}).fetchall()), 8)


class AdministratorWorkspaceTests(unittest.TestCase):
    def workspace(self, *, admin_only=True, full_directory=True):
        permission = SimpleNamespace(role='SYSTEM_ADMINISTRATOR', scope='FULL', resource='REQUESTS', actions={'view'})
        team = SimpleNamespace(role='SYSTEM_ADMINISTRATOR', scope='FULL', resource='TEAM_SKILLS', actions={'view'})
        user = SimpleNamespace(person_id='P-standalone-admin', roles={'SYSTEM_ADMINISTRATOR'},
                               subject='unchanged-admin-identity', require=MagicMock(return_value=permission),
                               permissions=(permission, team) if full_directory else (permission,))

        @contextmanager
        def read():
            yield None

        def query(_connection, sql, **binds):
            if 'AS pending_review' in sql:
                return [{'pending_review': 0, 'approved': 0, 'rejected': 0}]
            if "p.active_flag='Y' AND NOT" in sql:
                self.assertIn(ADMINISTRATOR_ONLY_SQL, sql)
                if full_directory:
                    self.assertIn('AND (1=1)', sql)
                    return [{'person_id': 'P-employee'}] + ([] if admin_only else [{'person_id': 'P-standalone-admin'}])
                self.assertEqual(binds, {'profileViewerId': 'P-standalone-admin'})
                self.assertIn('AND (p.person_id=:profileViewerId)', sql)
                return [] if admin_only else [{'person_id': 'P-standalone-admin'}]
            if 'AS total' in sql:
                return [
                    {'person_id': person_id, 'total': 0}
                    for key, person_id in binds.items() if key.startswith('activePerson')
                ]
            return []

        with patch('app.assignments.rows', side_effect=query), patch('app.assignments.load_policy', return_value=DEFAULT_POLICY), \
             patch('app.assignments.ZoneInfo', return_value=timezone.utc), \
             patch('app.assignments.load_capacity_ledgers', side_effect=lambda _connection, person_ids, *_: {
                 person_id: (CapacityLedger(), 0) for person_id in person_ids
             }) as capacity:
            result = AssignmentStore(SimpleNamespace(read=read), SimpleNamespace(staffing_policy_version='draft')).workspace(
                user, date(2026, 9, 14))
        self.assertEqual(user.person_id, 'P-standalone-admin')
        self.assertEqual(user.subject, 'unchanged-admin-identity')
        self.assertEqual(user.roles, {'SYSTEM_ADMINISTRATOR'})
        loaded = set(capacity.call_args.args[1]) if capacity.called else set()
        return result, loaded

    def test_admin_stays_authenticated_but_not_in_employee_metrics(self):
        result, reads = self.workspace()
        self.assertEqual([person['person_id'] for person in result['people']], ['P-employee'])
        self.assertEqual(reads, {'P-employee'})

    def test_actor_only_path_does_not_reinsert_standalone_admin(self):
        result, reads = self.workspace(full_directory=False)
        self.assertEqual(result['people'], [])
        self.assertEqual(reads, set())

    def test_combined_role_employee_remains_visible(self):
        result, reads = self.workspace(admin_only=False)
        self.assertEqual({person['person_id'] for person in result['people']}, {'P-employee', 'P-standalone-admin'})
        self.assertEqual(reads, {'P-employee', 'P-standalone-admin'})


if __name__ == '__main__':
    unittest.main()
