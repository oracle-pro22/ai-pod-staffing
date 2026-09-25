"""Offline transaction/ledger regressions. No Oracle, credentials, or model calls."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.auth import Actor, Permission
from app.availability import AvailabilityInput, cancel_availability, create_availability, update_availability
from app.capacity import calculate_capacity
from app.errors import ServiceError
from app.storage import load_capacity_ledger

MON = date(2099, 1, 5)
PERSON = Actor('account:test', 'P-TEST', frozenset({'POD_MEMBER'}), (
    Permission('POD_MEMBER', 'MY_AVAILABILITY', 'OWN', frozenset({'view', 'create', 'update'})),))


def body(**changes):
    return AvailabilityInput(**{**dict(personId='P-TEST', eventType='Leave', startsOn=MON,
                                      endsOn=MON, title='Planned leave', allocatedHours=4), **changes})


class Database:
    """Simulate relevant Oracle rows, trigger and transaction boundaries only."""
    def __init__(self):
        self.person = dict(weekly_work_hours=40, availability_version=1, workload_version=1)
        self.events, self.days = [], {}
        self.commits = self.rollbacks = 0
        self.allow = True
        self.add_week(MON)
        self.add_week(MON + timedelta(days=14))

    def add_week(self, first):
        for i in range(7):
            day = first + timedelta(days=i)
            self.days[day] = dict(work_date=day, available_hours=Decimal(8 if i < 5 else 0),
                                 external_committed_hours=Decimal(0), availability_version=1,
                                 source_version='capacity-refresh-v1')

    @contextmanager
    def write(self):
        before = deepcopy((self.person, self.events, self.days))
        try:
            yield self
            self.commits += 1
        except BaseException:
            self.person, self.events, self.days = before
            self.rollbacks += 1
            raise

    def query(self, _c, sql, **b):
        if 'FROM app_user_roles' in sql:
            return [{'person_id': 'P-TEST'}] if self.allow else []
        if 'FROM people' in sql:
            return [dict(self.person)]
        if 'FROM roster_pod_claims' in sql or 'FROM assignment_days' in sql:
            return []
        if 'FROM person_capacity_days' in sql:
            return [dict(v) for d, v in self.days.items()
                    if 'startDay' not in b or b['startDay'] <= d <= b['endDay']]
        if 'FROM availability' in sql:
            if 'availability_id=:availabilityId' in sql:
                return [e for e in self.events if e['availability_id'] == b['availabilityId']]
            if 'event_type=:kind' in sql:
                return [e for e in self.events if e['title'] == b['title']
                        and e['starts_on'] == b['firstDay'] and e['ends_on'] == b['lastDay']
                        and e['event_type'] == b['kind'] and e.get('status', 'ACTIVE') == 'ACTIVE'
                        and e['availability_id'] != b.get('availabilityId')]
            return [e for e in self.events if e.get('status', 'ACTIVE') == 'ACTIVE'
                    and e['starts_on'] <= b['endDay'] and e['ends_on'] >= b['startDay']]
        raise AssertionError(sql)

    def event(self, _c, sql, **b):
        if 'INSERT INTO availability' in sql:
            self.events.append(dict(availability_id=len(self.events)+1, person_id='P-TEST', event_type=b['kind'], title=b['title'],
                                    starts_on=b['firstDay'], ends_on=b['lastDay'], allocated_hours=b['hours'],
                                    capacity_kind=b['capacityKind'], status='ACTIVE'))
        elif "status='CANCELLED'" in sql:
            next(e for e in self.events if e['availability_id'] == b['availabilityId'])['status'] = 'CANCELLED'
        elif 'UPDATE availability SET event_type' in sql:
            saved = next(e for e in self.events if e['availability_id'] == b['availabilityId'])
            saved.update(event_type=b['kind'], starts_on=b['firstDay'], ends_on=b['lastDay'], title=b['title'],
                         allocated_hours=b['hours'], capacity_kind=b['capacityKind'])
        else:
            raise AssertionError(sql)
        self.person['availability_version'] += 1
        self.person['workload_version'] += 1

    def merge(self, _c, sql, b, _clobs):
        assert 'MERGE INTO person_capacity_days' in sql
        self.days[b['workDay']] = dict(work_date=b['workDay'], available_hours=b['availableHours'],
                                      external_committed_hours=b['externalHours'],
                                      availability_version=b['versionNumber'], source_version='capacity-refresh-v1')

    @contextmanager
    def wired(self):
        with ExitStack() as stack:
            for module in ('availability', 'capacity_admin', 'storage'):
                stack.enter_context(patch(f'app.{module}.rows', side_effect=self.query))
            stack.enter_context(patch('app.availability.execute', side_effect=self.event))
            stack.enter_context(patch('app.capacity_admin.execute', side_effect=self.merge))
            stack.enter_context(patch('app.availability.current_account'))
            stack.enter_context(patch('app.availability.audit'))
            stack.enter_context(patch('app.availability.active_policy_version', return_value='test'))
            stack.enter_context(patch('app.availability.load_policy', return_value=SimpleNamespace(scheduling_timezone='UTC')))
            yield


def test_leave_refreshes_other_recorded_weeks_and_preserves_external_work():
    db = Database()
    db.events.append(dict(availability_id=1, event_type='Commitment', title='External work', starts_on=MON,
                          ends_on=MON, allocated_hours=Decimal(2), capacity_kind='EXTERNAL_WORK'))
    with db.wired():
        create_availability(db, PERSON, body())
        ledger, _ = load_capacity_ledger(db, 'P-TEST', MON, MON + timedelta(days=4))
        capacity = calculate_capacity(ledger, MON, MON + timedelta(days=4), ())
        # A second recorded week must not remain stale after a person-wide version bump.
        load_capacity_ledger(db, 'P-TEST', MON + timedelta(days=14), MON + timedelta(days=18))
    assert db.commits == 1 and db.rollbacks == 0
    assert capacity.weeks[0].available_hours == 36
    assert capacity.weeks[0].committed_hours == 2
    assert all(d['availability_version'] == 2 for d in db.days.values())
    assert len(db.days) == 14  # Unknown intervening week was NOT filled.


@pytest.mark.parametrize('hours', [9, 16])
def test_impossible_leave_rolls_back_event_versions_and_capacity(hours):
    db = Database()
    before = deepcopy((db.person, db.days))
    with db.wired(), pytest.raises(ServiceError, match='overlapping absence'):
        create_availability(db, PERSON, AvailabilityInput(**{**body().model_dump(by_alias=True), 'allocatedHours': hours}))
    assert (db.person, db.days) == before and db.events == []
    assert db.commits == 0 and db.rollbacks == 1


def test_protected_baseline_is_not_erased_and_partial_refresh_rolls_back():
    db = Database()
    day = MON + timedelta(days=14)
    db.days[day].update(source_version='reviewed-import', external_committed_hours=3)
    before = deepcopy(db.days)
    with db.wired(), pytest.raises(ServiceError, match='additional absence or external work'):
        create_availability(db, PERSON, body())
    assert db.days == before and db.person['availability_version'] == 1 and not db.events


def test_duplicate_does_not_increment_version_twice():
    db = Database()
    with db.wired():
        create_availability(db, PERSON, body())
        with pytest.raises(ServiceError, match='already recorded'):
            create_availability(db, PERSON, body())
    assert len(db.events) == 1 and db.person['availability_version'] == 2


def test_event_outside_confirmed_period_does_not_invent_free_capacity():
    db = Database()
    day = MON + timedelta(days=28)
    with db.wired():
        create_availability(db, PERSON, AvailabilityInput(**{**body().model_dump(by_alias=True), 'startsOn': day, 'endsOn': day}))
    assert len(db.days) == 14 and day not in db.days
    assert all(d['availability_version'] == 2 for d in db.days.values())


def test_more_than_thirteen_recorded_weeks_are_refreshed_in_bounded_blocks():
    db = Database()
    for i in range(15):
        db.add_week(MON + timedelta(weeks=i))
    with db.wired():
        create_availability(db, PERSON, body())
    assert len(db.days) == 105 and all(d['availability_version'] == 2 for d in db.days.values())


def test_other_person_and_revoked_permission_cannot_save():
    db = Database()
    with db.wired():
        with pytest.raises(ServiceError, match='own profile'):
            create_availability(db, PERSON, AvailabilityInput(**{**body().model_dump(by_alias=True), 'personId': 'OTHER'}))
        db.allow = False
        with pytest.raises(ServiceError, match='permission changed'):
            create_availability(db, PERSON, body())
    assert not db.events and db.commits == 0


@pytest.mark.parametrize('hours', [0, -1, 'NaN', '1.001'])
def test_invalid_hours_rejected_before_writing(hours):
    with pytest.raises(ValidationError):
        AvailabilityInput(**{**body().model_dump(by_alias=True), 'allocatedHours': hours})


def test_external_commitment_counts_as_committed_work():
    db = Database()
    with db.wired():
        create_availability(db, PERSON, body(eventType='External commitment', title='Customer support'))
        ledger, _ = load_capacity_ledger(db, 'P-TEST', MON, MON + timedelta(days=4))
        capacity = calculate_capacity(ledger, MON, MON + timedelta(days=4), ())
    assert capacity.weeks[0].available_hours == 40
    assert capacity.weeks[0].committed_hours == 4


def test_edit_refreshes_union_of_old_and_new_dates():
    db = Database()
    with db.wired():
        create_availability(db, PERSON, body())
        update_availability(db, PERSON, 1, body(startsOn=MON + timedelta(days=1), endsOn=MON + timedelta(days=1), allocatedHours=2))
    assert db.events[0]['starts_on'] == MON + timedelta(days=1)
    assert db.days[MON]['available_hours'] == 8
    assert db.days[MON + timedelta(days=1)]['available_hours'] == 6


def test_cancel_removes_event_from_future_capacity_but_retains_history():
    db = Database()
    with db.wired():
        create_availability(db, PERSON, body())
        cancel_availability(db, PERSON, 1)
    assert db.events[0]['status'] == 'CANCELLED'
    assert db.days[MON]['available_hours'] == 8
