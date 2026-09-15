"""Relational closure/capacity regression tests; no Oracle writes or model calls."""
import sqlite3
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from closure_sql_fixture import register_closure_day, sqlite_closure_sql

from app.capacity import calculate_capacity, schedule_available_hours
from app.storage import COUNTED_ASSIGNMENT_DAY_SQL, load_capacity_ledger

MON = date(2026, 9, 14)


class ClosureAllocationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        register_closure_day(self.db)
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE people(person_id TEXT, active_flag TEXT, weekly_work_hours INTEGER,
                workload_version INTEGER, availability_version INTEGER);
            INSERT INTO people VALUES ('P-1','Y',40,7,2);
            CREATE TABLE person_capacity_days(person_id TEXT,work_date TEXT,available_hours INTEGER,
                external_committed_hours INTEGER,availability_version INTEGER);
            CREATE TABLE load_guardrails(policy_version TEXT PRIMARY KEY,scheduling_timezone TEXT);
            INSERT INTO load_guardrails VALUES ('original','Asia/Kolkata');
            INSERT INTO load_guardrails VALUES ('later-runtime','America/Los_Angeles');
            CREATE TABLE pod_assignments(assignment_id TEXT PRIMARY KEY,status TEXT,closed_at TEXT,policy_version TEXT);
            CREATE TABLE assignment_days(assignment_id TEXT,person_id TEXT,work_date TEXT,assigned_hours INTEGER);
        ''')
        self.db.executemany('INSERT INTO person_capacity_days VALUES (?,?,?,?,2)', [
            ('P-1', (MON + timedelta(days=i)).isoformat(), 8 if i % 7 < 5 else 0, 2 if i % 7 < 5 else 0)
            for i in range(21)
        ])
        self.add_assignment('closing')

    def add_assignment(self, name, hours=2, days=5, status='CONFIRMED', closed_at=None, offset=0):
        self.db.execute('INSERT INTO pod_assignments VALUES (?,?,?,?)', (name, status, closed_at, 'original'))
        self.db.executemany('INSERT INTO assignment_days VALUES (?,?,?,?)', [
            (name, 'P-1', (MON + timedelta(days=i + offset)).isoformat(), hours) for i in range(days)
        ])

    def close(self, instant='2026-09-16T12:00:00+00:00'):
        self.db.execute("UPDATE pod_assignments SET status='CLOSED',closed_at=? WHERE assignment_id='closing'", (instant,))

    def query(self, connection, sql, **binds):
        binds = {k: v.isoformat() if isinstance(v, date) else v for k, v in binds.items()}
        values = [dict(row) for row in connection.execute(sqlite_closure_sql(sql), binds)]
        for row in values:
            if 'work_date' in row:
                row['work_date'] = date.fromisoformat(row['work_date'])
        return values

    def ledger(self, start=MON, end=None):
        with patch('app.storage.rows', side_effect=self.query):
            return load_capacity_ledger(self.db, 'P-1', start, end or start + timedelta(days=6))[0]

    def percent(self, start=MON):
        return calculate_capacity(self.ledger(start), start, start + timedelta(days=6), ()).weeks[0].allocation_pct

    def test_normal_completion_preserves_entire_planned_week(self):
        before = self.percent()
        self.close('2026-09-18T12:00:00+00:00')
        self.assertEqual(before, Decimal('50'))
        self.assertEqual(self.percent(), before)
        self.assertEqual(self.percent(MON + timedelta(days=7)), Decimal('25'))

    def test_early_completion_retains_closing_day_and_releases_only_later_days(self):
        original = list(self.db.execute('SELECT * FROM assignment_days'))
        self.close()
        self.assertEqual([(d.day, d.hours) for d in self.ledger().confirmed_work], [
            (MON + timedelta(days=i), Decimal(2)) for i in range(3)])
        self.assertEqual(self.percent(), Decimal('40'))  # 6 project + 10 external / 40
        self.assertEqual(list(self.db.execute('SELECT * FROM assignment_days')), original)

    def test_overlapping_confirmed_pod_and_external_work_are_unchanged(self):
        self.add_assignment('other', hours=1)
        self.close()
        self.assertEqual(self.percent(), Decimal('52.5'))  # 6 + 5 + 10 / 40

    def test_leave_changes_denominator_not_closure_cutoff(self):
        self.db.execute("UPDATE person_capacity_days SET available_hours=0,external_committed_hours=0 WHERE work_date='2026-09-18'")
        self.close()
        self.assertEqual(self.percent(), Decimal('43.75'))  # 6 project + 8 external / 32

    def test_full_week_leave_is_unknown_percentage_not_division_by_zero(self):
        self.db.execute('UPDATE person_capacity_days SET available_hours=0,external_committed_hours=0')
        self.close('2026-09-13T12:00:00+00:00')
        self.assertIsNone(self.percent())

    def test_overdue_open_schedule_does_not_roll_hours_forward(self):
        self.assertEqual(self.percent(MON + timedelta(days=7)), Decimal('25'))
        self.assertEqual(self.db.execute("SELECT status FROM pod_assignments").fetchone()[0], 'CONFIRMED')
        self.close('2026-09-23T12:00:00+00:00')
        self.assertEqual(self.percent(), Decimal('50'))
        self.assertEqual(self.percent(MON + timedelta(days=7)), Decimal('25'))

    def test_weekend_closure_keeps_previous_week_and_releases_next_week(self):
        self.db.executemany("INSERT INTO assignment_days VALUES ('closing','P-1',?,2)", [
            ((MON + timedelta(days=i)).isoformat(),) for i in range(7, 12)])
        self.close('2026-09-19T12:00:00+00:00')
        self.assertEqual(self.percent(), Decimal('50'))
        self.assertEqual(self.percent(MON + timedelta(days=7)), Decimal('25'))

    def test_closure_before_scheduled_start_releases_all_project_hours(self):
        self.close('2026-09-13T12:00:00+00:00')
        self.assertEqual(self.percent(), Decimal('25'))

    def test_midnight_boundary_uses_original_policy_not_utc_or_runtime_timezone(self):
        # 18:30 UTC is midnight on Thursday in the assignment's India timezone.
        self.close('2026-09-16T18:29:59+00:00')
        self.assertEqual(self.percent(), Decimal('40'))
        self.close('2026-09-16T18:30:00+00:00')
        self.assertEqual(self.percent(), Decimal('45'))

    def test_other_person_and_cancelled_import_do_not_enter_ledger(self):
        self.add_assignment('cancelled', hours=8, status='CANCELLED', closed_at='2026-09-18T12:00:00+00:00')
        self.db.execute("INSERT INTO assignment_days VALUES ('closing','P-OTHER','2026-09-14',8)")
        self.close()
        self.assertEqual(self.percent(), Decimal('40'))

    def test_new_request_scheduler_uses_released_days_not_past_capacity(self):
        start, end = MON + timedelta(days=3), MON + timedelta(days=4)
        with self.assertRaises(ValueError):
            schedule_available_hours(self.ledger(), Decimal(12), start, end)
        self.close()
        scheduled = schedule_available_hours(self.ledger(), Decimal(12), start, end)
        self.assertEqual([(d.day, d.hours) for d in scheduled], [(start, Decimal(6)), (end, Decimal(6))])
        self.assertTrue(calculate_capacity(self.ledger(), start, end, scheduled).feasible)

    def test_weekly_history_still_counts_when_request_checks_only_remaining_days(self):
        self.close()
        start, end = MON + timedelta(days=3), MON + timedelta(days=4)
        self.assertEqual(sum(d.hours for d in self.ledger(start, end).confirmed_work), Decimal(6))

    def test_calendar_and_ledger_share_exact_predicate(self):
        from app import assignments
        self.assertEqual(assignments.COUNTED_ASSIGNMENT_DAY_SQL, COUNTED_ASSIGNMENT_DAY_SQL)
        source = Path(assignments.__file__).read_text(encoding='utf-8')
        self.assertIn('JOIN requests r ON r.request_id=a.request_id WHERE {COUNTED_ASSIGNMENT_DAY_SQL}', source)
        self.close()
        calendar = self.query(self.db, f'''SELECT d.work_date,d.assigned_hours
            FROM assignment_days d JOIN pod_assignments a ON a.assignment_id=d.assignment_id
            WHERE {COUNTED_ASSIGNMENT_DAY_SQL} ORDER BY d.work_date''')
        self.assertEqual([(d['work_date'], d['assigned_hours']) for d in calendar],
                         [(d.day, d.hours) for d in self.ledger().confirmed_work])


if __name__ == '__main__':
    unittest.main()
