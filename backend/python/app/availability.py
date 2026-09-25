"""Own availability writes and capacity refresh, committed together."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.accounts import execute
from app.capacity import spread_hours
from app.capacity_admin import refresh_recorded_capacity
from app.contracts import Contract, EntityId
from app.policy_admin import active_policy_version
from app.roster_lifecycle import current_account, demand, audit
from app.storage import rows, load_policy


EVENT_TYPES = Literal['OOO', 'Leave', 'Travel', 'Training', 'Reduced hours', 'External commitment']


class AvailabilityInput(Contract):
    person_id: EntityId = Field(alias='personId')
    event_type: EVENT_TYPES = Field(alias='eventType')
    starts_on: date = Field(alias='startsOn')
    ends_on: date = Field(alias='endsOn')
    title: str = Field(min_length=1, max_length=500)
    allocated_hours: Decimal = Field(alias='allocatedHours', gt=0, le=100000, decimal_places=2, allow_inf_nan=False)

    @model_validator(mode='after')
    def valid(self):
        if self.ends_on < self.starts_on or (self.ends_on-self.starts_on).days > 366:
            raise ValueError('Use an ordered availability period of at most 366 days')
        spread_hours(self.allocated_hours, self.starts_on, self.ends_on)
        return self


def capacity_kind(event_type):
    return 'EXTERNAL_WORK' if event_type == 'External commitment' else 'NON_AVAILABILITY'


def require_own_write(c, actor, action='create'):
    permission = actor.require('MY_AVAILABILITY', action)
    demand(permission.scope == 'OWN', 'You can only change availability for your own profile.', 'FORBIDDEN', 403)
    current_account(c, actor)
    demand(rows(c, f"""SELECT ur.person_id FROM app_user_roles ur
        JOIN app_roles ar ON ar.role_code=ur.role_code AND ar.active_flag='Y'
        JOIN role_permissions rp ON rp.role_code=ur.role_code AND rp.resource_code='MY_AVAILABILITY'
        WHERE ur.identity_subject=:subject AND ur.person_id=:pid AND ur.role_code=:role
        AND ur.active_flag='Y' AND ur.effective_from<=TRUNC(SYSDATE)
        AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))
        AND rp.access_scope='OWN' AND rp.can_view='Y' AND rp.can_{action}='Y'""",
        subject=actor.subject, pid=actor.person_id, role=permission.role), 'Your permission changed.', 'FORBIDDEN', 403)
    return permission


def today(c):
    policy = load_policy(c, active_policy_version(c))
    return datetime.now(ZoneInfo(policy.scheduling_timezone)).date()


def create_availability(database, actor, body):
    demand(actor.person_id == body.person_id,
           'You can only add availability for your own profile.', 'FORBIDDEN', 403)
    with database.write() as c:
        rows(c, 'SELECT person_id FROM people WHERE person_id=:pid FOR UPDATE WAIT 5', pid=actor.person_id)
        require_own_write(c, actor)
        demand(body.starts_on >= today(c),
               'Start date cannot be earlier than today.', 'INVALID_REQUEST', 422)
        duplicate = rows(c, """SELECT availability_id,status FROM availability WHERE person_id=:pid AND event_type=:kind
            AND starts_on=:firstDay AND ends_on=:lastDay AND title=:title""",
            pid=actor.person_id, kind=body.event_type, firstDay=body.starts_on, lastDay=body.ends_on, title=body.title)
        demand(not any(row['status'] == 'ACTIVE' for row in duplicate),
               'This availability event is already recorded.', 'CONFLICT', 409)
        values = dict(pid=actor.person_id, kind=body.event_type, firstDay=body.starts_on, lastDay=body.ends_on,
                      title=body.title, hours=body.allocated_hours, capacityKind=capacity_kind(body.event_type), subject=actor.subject)
        cancelled = next((row for row in duplicate if row['status'] == 'CANCELLED'), None)
        if cancelled:
            execute(c, """UPDATE availability SET allocated_hours=:hours,capacity_kind=:capacityKind,status='ACTIVE',
                cancelled_at=NULL,cancelled_by=NULL,updated_at=SYSTIMESTAMP WHERE availability_id=:availabilityId""",
                hours=body.allocated_hours, capacityKind=capacity_kind(body.event_type), availabilityId=cancelled['availability_id'])
        else:
            execute(c, """INSERT INTO availability(person_id,event_type,starts_on,ends_on,title,allocated_hours,capacity_kind,status,created_by)
                VALUES(:pid,:kind,:firstDay,:lastDay,:title,:hours,:capacityKind,'ACTIVE',:subject)""", **values)
        # Any invalid overlap/baseline rolls the event back too. Never just stamp
        # old capacity rows with a newer version or silently erase source hours.
        refresh_recorded_capacity(c, actor.person_id, actor.subject, body.starts_on, body.ends_on)
        audit(c, actor, actor.person_id, 'AVAILABILITY_CREATED', 'Availability and recorded capacity refreshed together.')
        return body.model_dump(mode='json', by_alias=True)


def update_availability(database, actor, availability_id, body):
    demand(actor.person_id == body.person_id,
           'You can only change availability for your own profile.', 'FORBIDDEN', 403)
    with database.write() as c:
        rows(c, 'SELECT person_id FROM people WHERE person_id=:pid FOR UPDATE WAIT 5', pid=actor.person_id)
        require_own_write(c, actor, 'update')
        saved = rows(c, """SELECT availability_id,person_id,event_type,starts_on,ends_on,title,allocated_hours,status
            FROM availability WHERE availability_id=:availabilityId FOR UPDATE WAIT 5""", availabilityId=availability_id)
        demand(len(saved) == 1 and saved[0]['person_id'] == actor.person_id,
               'Availability event not found.', 'AVAILABILITY_NOT_FOUND', 404)
        original = saved[0]
        demand(original['status'] == 'ACTIVE', 'Cancelled availability cannot be edited.', 'CONFLICT', 409)
        business_day = today(c)
        demand(calendar_date(original['starts_on']) >= business_day and body.starts_on >= business_day,
               'Past availability is retained as history and cannot be edited.', 'CONFLICT', 409)
        duplicate = rows(c, """SELECT availability_id FROM availability WHERE person_id=:pid AND event_type=:kind
            AND starts_on=:firstDay AND ends_on=:lastDay AND title=:title AND status='ACTIVE'
            AND availability_id<>:availabilityId""", pid=actor.person_id, kind=body.event_type,
            firstDay=body.starts_on, lastDay=body.ends_on, title=body.title, availabilityId=availability_id)
        demand(not duplicate, 'This availability event is already recorded.', 'CONFLICT', 409)
        execute(c, """UPDATE availability SET event_type=:kind,starts_on=:firstDay,ends_on=:lastDay,
            title=:title,allocated_hours=:hours,capacity_kind=:capacityKind,updated_at=SYSTIMESTAMP
            WHERE availability_id=:availabilityId""", kind=body.event_type, firstDay=body.starts_on,
            lastDay=body.ends_on, title=body.title, hours=body.allocated_hours,
            capacityKind=capacity_kind(body.event_type), availabilityId=availability_id)
        refresh_recorded_capacity(c, actor.person_id, actor.subject,
            min(calendar_date(original['starts_on']), body.starts_on), max(calendar_date(original['ends_on']), body.ends_on))
        audit(c, actor, str(availability_id), 'AVAILABILITY_UPDATED', 'Availability and recorded capacity refreshed together.')
        return {'availabilityId': availability_id, **body.model_dump(mode='json', by_alias=True)}


def cancel_availability(database, actor, availability_id):
    with database.write() as c:
        rows(c, 'SELECT person_id FROM people WHERE person_id=:pid FOR UPDATE WAIT 5', pid=actor.person_id)
        require_own_write(c, actor, 'update')
        saved = rows(c, """SELECT availability_id,person_id,starts_on,ends_on,status FROM availability
            WHERE availability_id=:availabilityId FOR UPDATE WAIT 5""", availabilityId=availability_id)
        demand(len(saved) == 1 and saved[0]['person_id'] == actor.person_id,
               'Availability event not found.', 'AVAILABILITY_NOT_FOUND', 404)
        original = saved[0]
        demand(original['status'] == 'ACTIVE', 'Availability event is already cancelled.', 'CONFLICT', 409)
        demand(calendar_date(original['starts_on']) >= today(c),
               'Past availability is retained as history and cannot be cancelled.', 'CONFLICT', 409)
        execute(c, """UPDATE availability SET status='CANCELLED',cancelled_at=SYSTIMESTAMP,
            cancelled_by=:subject,updated_at=SYSTIMESTAMP WHERE availability_id=:availabilityId""",
            subject=actor.subject, availabilityId=availability_id)
        refresh_recorded_capacity(c, actor.person_id, actor.subject,
            calendar_date(original['starts_on']), calendar_date(original['ends_on']))
        audit(c, actor, str(availability_id), 'AVAILABILITY_CANCELLED', 'Cancelled event removed from future capacity calculations.')
        return {'availabilityId': availability_id, 'status': 'CANCELLED'}


def calendar_date(value):
    return value.date() if isinstance(value, datetime) else value
