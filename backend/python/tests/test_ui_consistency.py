"""Daily calendar totals come from the same scoped ledger as weekly allocation."""
import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from pydantic import ValidationError

from app.assignments import capacity_people
from app.capacity import CapacityLedger
from app.contracts import DailyHours, RequestSnapshot
from app.policy import DEFAULT_POLICY


class CalendarCapacityTests(unittest.TestCase):
    def test_reported_pod_work_and_onboarding_are_returned_only_for_allowed_people(self):
        monday = date(2026, 10, 12)
        ledger = CapacityLedger(reported_pod_work=tuple(
            DailyHours(day=monday + timedelta(days=n), hours=Decimal(6)) for n in range(5)))
        def query(_connection, sql, **binds):
            self.assertEqual(binds.get('activePerson0'), 'robert')
            if 'roster_onboarding' in sql:
                return [{'person_id': 'robert', 'status': 'DRAFT'}]
            return []
        with patch('app.assignments.rows', side_effect=query), patch('app.assignments.load_capacity_ledgers',
                return_value={'robert': (ledger, 1)}):
            people = capacity_people(None, ['robert'], monday, monday + timedelta(days=6), monday, DEFAULT_POLICY)
        self.assertEqual(len(people), 1)
        person = people[0]
        self.assertEqual(person['allocation_pct'], Decimal(75))
        self.assertEqual(person['onboarding_status'], 'DRAFT')
        self.assertEqual([d['reported_pod_hours'] for d in person['capacity_days']], [6, 6, 6, 6, 6, 0, 0])
        self.assertEqual(sum(d['reported_pod_hours'] for d in person['capacity_days']), person['weeks'][0]['reported_pod_hours'])

    def test_new_request_contract_requires_one_lead_and_maximum_five_members(self):
        from test_phase3 import bundle
        request = bundle().request.model_dump()
        for changes in ({'lead_count': 0}, {'lead_count': 2}, {'member_count': 6}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                RequestSnapshot.model_validate({**request, **changes})
        for count in (0, 5):
            self.assertEqual(RequestSnapshot.model_validate({**request, 'lead_count': 1, 'member_count': count}).member_count, count)
