"""Offline lifecycle regressions; no Oracle, account changes, or model calls."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.availability import AvailabilityEnd, cancel_availability, update_availability, create_availability
from app.availability_schedule import event_days
from app.capacity import calculate_capacity
from app.errors import ServiceError
from app.roster_lifecycle import OnboardingInput
from app.schedule_dates import RescheduleInput, require_future_schedule
from app.storage import load_capacity_ledger
from test_availability_save import Database, MON, PERSON, body


@pytest.fixture(autouse=True)
def fixed_capacity_business_date():
    with patch('app.storage.capacity_business_day', return_value=MON):
        yield


def ongoing(db):
    with db.wired():
        create_availability(db, PERSON, body(eventType='External commitment', endsOn=MON+timedelta(days=4), allocatedHours='10.01'))


def test_end_ongoing_preserves_original_rounding_and_releases_remaining_days():
    db = Database()
    ongoing(db)
    with db.wired(), patch('app.availability.today', return_value=MON+timedelta(days=2)):
        result = cancel_availability(db, PERSON, 1, AvailabilityEnd(revision=1, effectiveOn=MON+timedelta(days=2)))
    assert result['retainedHours'] == '4.01'
    assert [entry.hours for entry in event_days(db.events[0])] == [Decimal('2.01'), Decimal('2.00')]
    assert db.days[MON]['external_committed_hours'] == Decimal('2.01')
    assert db.days[MON+timedelta(days=2)]['external_committed_hours'] == 0
    assert db.events[0]['allocated_hours'] == Decimal('10.01')  # original retained


@pytest.mark.parametrize('offset,expected_status', [(0, 'CANCELLED'), (2, 'ACTIVE')])
def test_end_remaining_respects_existing_oracle_status_constraint(offset, expected_status):
    import sqlite3
    from app.availability import end_remaining
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute('''CREATE TABLE availability(availability_id INTEGER, effective_until TEXT, revision INTEGER,
            status TEXT, updated_at TEXT, cancelled_at TEXT, cancelled_by TEXT,
            CHECK ((status='ACTIVE' AND cancelled_at IS NULL AND cancelled_by IS NULL)
                OR (status='CANCELLED' AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL)))''')
        connection.execute("INSERT INTO availability(availability_id,revision,status) VALUES (1,1,'ACTIVE')")
        original = dict(availability_id=1, starts_on=MON, ends_on=MON+timedelta(days=4), allocated_hours=Decimal('10.01'))
        def execute(c, sql, **binds):
            converted = {key: value.isoformat() if isinstance(value, date) else value for key, value in binds.items()}
            c.execute(sql.replace('SYSTIMESTAMP', 'CURRENT_TIMESTAMP'), converted)
        with patch('app.availability.execute', side_effect=execute):
            end_remaining(connection, original, MON+timedelta(days=offset), PERSON)
        status, revision = connection.execute('SELECT status,revision FROM availability').fetchone()
        assert status == expected_status and revision == 2
    finally:
        connection.close()


def test_adjust_remaining_creates_new_segment_without_redistributing_history():
    db = Database()
    ongoing(db)
    with db.wired(), patch('app.availability.today', return_value=MON+timedelta(days=2)):
        update_availability(db, PERSON, 1, body(eventType='External commitment', startsOn=MON+timedelta(days=2),
            endsOn=MON+timedelta(days=4), allocatedHours=9))
    assert len(db.events) == 2
    assert db.days[MON]['external_committed_hours'] == Decimal('2.01')
    assert db.days[MON+timedelta(days=1)]['external_committed_hours'] == Decimal(2)
    assert db.days[MON+timedelta(days=2)]['external_committed_hours'] == Decimal(3)
    assert sum(d['external_committed_hours'] for d in db.days.values()) == Decimal('13.01')


def test_invalid_remaining_leave_rolls_back_both_segments():
    db = Database()
    ongoing(db)
    with db.wired(), patch('app.availability.today', return_value=MON+timedelta(days=2)):
        with pytest.raises(ServiceError, match='overlapping'):
            update_availability(db, PERSON, 1, body(startsOn=MON+timedelta(days=2),
                endsOn=MON+timedelta(days=2), allocatedHours=16))
    assert len(db.events) == 1 and db.events[0]['effective_until'] is None
    assert db.events[0]['revision'] == 1


def test_stale_tab_cannot_overwrite_an_availability_revision():
    db = Database()
    ongoing(db)
    with db.wired():
        update_availability(db, PERSON, 1, body(eventType='External commitment', allocatedHours=1))
        with pytest.raises(ServiceError) as error:
            cancel_availability(db, PERSON, 1, AvailabilityEnd(revision=1, effectiveOn=MON))
    assert error.value.code == 'STALE_AVAILABILITY'


def test_history_and_other_people_cannot_be_changed():
    db = Database()
    ongoing(db)
    with db.wired(), patch('app.availability.today', return_value=MON+timedelta(days=7)):
        with pytest.raises(ServiceError):
            cancel_availability(db, PERSON, 1, AvailabilityEnd(revision=1, effectiveOn=MON+timedelta(days=7)))
    assert db.events[0]['effective_until'] is None


def ledger_query(complete=True, saved=(), stale=False):
    def query(c, sql, **binds):
        if 'FROM people' in sql:
            return [{'person_id': 'P', 'weekly_work_hours': 40, 'availability_version': 2, 'workload_version': 7}]
        if 'FROM person_capacity_days' in sql:
            return [{'person_id': 'P', 'work_date': d, 'available_hours': 4, 'external_committed_hours': 1,
                     'availability_version': 1 if stale else 2} for d in saved]
        if 'FROM roster_onboarding' in sql:
            return [{'person_id': 'P'}] if complete else []
        if 'FROM availability' in sql:
            return [{'person_id': 'P', 'starts_on': MON, 'ends_on': MON, 'allocated_hours': 8,
                     'capacity_kind': 'NON_AVAILABILITY', 'effective_until': None},
                    {'person_id': 'P', 'starts_on': MON+timedelta(days=1), 'ends_on': MON+timedelta(days=4),
                     'allocated_hours': 16, 'capacity_kind': 'EXTERNAL_WORK', 'effective_until': None}]
        if 'FROM assignment_days' in sql:
            return [{'person_id': 'P', 'work_date': MON+timedelta(days=1), 'hours': 2}]
        if 'FROM roster_pod_claims' in sql:
            return [{'person_id': 'P', 'starts_on': MON+timedelta(days=2), 'ends_on': MON+timedelta(days=2), 'total_hours': 3}]
        raise AssertionError(sql)
    return query


def test_future_capacity_derives_missing_weeks_and_counts_all_sources_once():
    with patch('app.storage.rows', side_effect=ledger_query()):
        ledger, version = load_capacity_ledger(None, 'P', MON, MON+timedelta(days=4))
    result = calculate_capacity(ledger, MON, MON+timedelta(days=4), ())
    assert result.weeks[0].available_hours == 32
    assert result.weeks[0].committed_hours == 21  # 16 external + 2 approved + 3 reported
    assert version == 7


def test_future_capacity_preserves_reviewed_daily_adjustments():
    with patch('app.storage.rows', side_effect=ledger_query(saved=[MON+timedelta(days=1)])):
        ledger, _ = load_capacity_ledger(None, 'P', MON, MON+timedelta(days=4))
    assert next(x.hours for x in ledger.absences if x.day == MON+timedelta(days=1)) == 4
    assert next(x.hours for x in ledger.external_work if x.day == MON+timedelta(days=1)) == 1


@pytest.mark.parametrize('complete,stale', [(False, False), (True, True)])
def test_incomplete_onboarding_or_stale_existing_days_never_become_free(complete, stale):
    with patch('app.storage.rows', side_effect=ledger_query(complete, [MON] if stale else [], stale)):
        with pytest.raises(ServiceError) as error:
            load_capacity_ledger(None, 'P', MON, MON+timedelta(days=4))
    assert error.value.code == 'CAPACITY_STALE'


def test_future_capacity_long_requests_are_chunked_and_do_not_write():
    with patch('app.storage.rows', side_effect=ledger_query()):
        ledger, _ = load_capacity_ledger(None, 'P', MON, MON+timedelta(weeks=30))
    assert len(ledger.absences) == 217


def test_missing_historical_capacity_is_not_reconstructed_from_todays_contract():
    with patch('app.storage.rows', side_effect=ledger_query()), patch('app.storage.capacity_business_day', return_value=MON+timedelta(weeks=1)):
        with pytest.raises(ServiceError) as error:
            load_capacity_ledger(None, 'P', MON, MON+timedelta(days=4))
    assert error.value.code == 'CAPACITY_STALE'


@pytest.mark.parametrize('text', ['', '   ', '\t\n'])
def test_onboarding_rated_skill_requires_plain_nonblank_experience(text):
    with pytest.raises(ValidationError, match='experience'):
        OnboardingInput(revision=1, starts_on=MON, ends_on=MON, confirmed=True,
            skills=[{'skill_id': 'S', 'strength': 5, 'evidence': text}])


def test_experience_is_self_reported_text_not_proof_or_approval():
    value = OnboardingInput(revision=1, starts_on=MON, ends_on=MON, confirmed=True,
        skills=[{'skill_id': 'S', 'strength': 5, 'evidence': 'I write communication plans.'}])
    assert value.skills[0].evidence == 'I write communication plans.'


@pytest.mark.parametrize('offset', [-7, -1, 0, 1])
def test_shared_approval_date_guard(offset):
    request = SimpleNamespace(starts_on=MON+timedelta(days=offset))
    with patch('app.schedule_dates.business_date', return_value=MON):
        if offset < 0:
            with pytest.raises(ServiceError) as error:
                require_future_schedule(request, None)
            assert error.value.code == 'SCHEDULE_DATES_EXPIRED'
        else:
            require_future_schedule(request, None)


def test_date_guard_prevents_real_approval_writer_from_committing_past_work():
    from test_phase4 import DecisionTests
    harness = DecisionTests()
    harness.setUp()
    try:
        with patch('app.schedule_dates.business_date', return_value=harness.data.request.ends_on+timedelta(days=1)):
            with pytest.raises(ServiceError) as error:
                harness.decide()
        assert error.value.code == 'SCHEDULE_DATES_EXPIRED'
        assert harness.committed == []
    finally:
        harness.doCleanups()


def test_manual_approval_cannot_bypass_date_guard():
    from test_mvp_phase3 import ManualStoreTests
    harness = ManualStoreTests()
    harness.setUp()
    try:
        draft = harness.preview()
        before = list(harness.committed)
        with patch('app.schedule_dates.business_date', return_value=harness.source.request.ends_on+timedelta(days=1)):
            with pytest.raises(ServiceError) as error:
                harness.decide(draft)
        assert error.value.code == 'SCHEDULE_DATES_EXPIRED'
        assert harness.committed == before
    finally:
        harness.doCleanups()


@pytest.mark.parametrize('revision,status,running,allowed', [
    (1, 'NEEDS_RECOMMENDATION', False, True),
    (2, 'NEEDS_RECOMMENDATION', False, False),
    (1, 'STAFFED', False, False),
    (1, 'NEEDS_RECOMMENDATION', True, False),
])
def test_rescheduling_is_locked_revisioned_and_cannot_change_staffed_or_running_work(revision, status, running, allowed):
    from contextlib import contextmanager
    from unittest.mock import MagicMock
    from app.schedule_dates import reschedule
    commands = []
    @contextmanager
    def tx():
        yield None
    def query(c, sql, **b):
        if 'FROM requests' in sql:
            assert 'FOR UPDATE' in sql
            return [{'request_revision': revision, 'status': status, 'responsible_captain_id': 'captain'}]
        if 'FROM agent_executions' in sql:
            return [{'execution_id': 'RUN'}] if running else []
        return []
    body = RescheduleInput(revision=1, starts_on=MON, ends_on=MON+timedelta(days=4), needed_by=MON, total_hours=32)
    actor = SimpleNamespace(subject='captain', require=MagicMock())
    with patch('app.storage.rows', side_effect=query), patch('app.storage.load_policy'), \
         patch('app.policy_admin.active_policy_version'), patch('app.schedule_dates.business_date', return_value=MON), \
         patch('app.decisions.DecisionStore.authorize') as authorize, patch('app.roster_lifecycle.current_account'), \
         patch('app.roster_lifecycle.audit'), patch('app.accounts.execute', side_effect=lambda c, sql, **b: commands.append((sql, b))):
        if allowed:
            assert reschedule(SimpleNamespace(write=tx), actor, 'REQ', body)['rerun_required']
            authorize.assert_called_once()
            assert len(commands) == 1 and "estimated_effort_unit='HOURS'" in commands[0][0]
            assert commands[0][1]['hours'] == 32
        else:
            with pytest.raises(ServiceError):
                reschedule(SimpleNamespace(write=tx), actor, 'REQ', body)
            assert commands == []
