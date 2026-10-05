"""Business-date guard and explicit, revisioned rescheduling of unstaffed work."""
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from app.contracts import Contract
from app.errors import ServiceError
from app.capacity import spread_hours


def business_date(policy):
    return datetime.now(ZoneInfo(policy.scheduling_timezone)).date()


def require_future_schedule(request, policy):
    if request.starts_on < business_date(policy):
        raise ServiceError('SCHEDULE_DATES_EXPIRED',
            'This request starts in the past. Update its dates and remaining effort, then rerun fitment before approval.', 409)


class RescheduleInput(Contract):
    revision: int = Field(ge=1, strict=True)
    starts_on: date
    ends_on: date
    needed_by: date
    total_hours: Decimal = Field(gt=0, le=100000, decimal_places=2, allow_inf_nan=False)

    @model_validator(mode='after')
    def valid(self):
        if self.ends_on < self.starts_on or (self.ends_on-self.starts_on).days > 366:
            raise ValueError('Choose an ordered schedule of at most 366 days.')
        spread_hours(self.total_hours, self.starts_on, self.ends_on)
        return self


def reschedule(database, actor, request_id, body):
    from app.decisions import DecisionStore
    from app.policy_admin import active_policy_version
    from app.storage import rows, load_policy
    from app.accounts import execute
    from app.roster_lifecycle import audit, current_account
    actor.require('AI_FITMENT', 'approve', 'POD_CAPTAIN')
    with database.write() as c:
        policy = load_policy(c, active_policy_version(c, lock=True))
        records = rows(c, 'SELECT request_revision,responsible_captain_id,status FROM requests WHERE request_id=:rid FOR UPDATE WAIT 5', rid=request_id)
        if not records:
            raise ServiceError('REQUEST_NOT_FOUND', 'Request not found.', 404)
        row = records[0]
        current_account(c, actor)
        DecisionStore.authorize(c, actor, row['responsible_captain_id'])
        if row['request_revision'] != body.revision:
            raise ServiceError('STALE_REQUEST', 'Request changed. Refresh before updating dates.', 409)
        if row['status'] not in ('NEEDS_RECOMMENDATION', 'IN_REVIEW') or rows(c,
                "SELECT assignment_id FROM pod_assignments WHERE request_id=:rid AND status='CONFIRMED'", rid=request_id):
            raise ServiceError('ALREADY_ASSIGNED', 'Only unstaffed requests can be rescheduled here.', 409)
        if rows(c, "SELECT execution_id FROM agent_executions WHERE request_id=:rid AND status IN ('QUEUED','RUNNING')", rid=request_id):
            raise ServiceError('EXECUTION_ACTIVE', 'Wait for the current execution to finish before changing dates.', 409)
        require_future_schedule(body, policy)
        if body.needed_by < business_date(policy):
            raise ServiceError('INVALID_DATE', 'Needed-by date cannot be in the past.', 422)
        # The existing P2_REQUEST_REVISION trigger increments the revision. Old
        # proposals/drafts remain audit history and fail revision checks.
        execute(c, """UPDATE requests SET estimated_start_date=:firstDay,estimated_completion_date=:lastDay,
            needed_by=:neededBy,estimated_hours=:hours,estimated_effort_value=:hours,estimated_effort_unit='HOURS',
            status='NEEDS_RECOMMENDATION',updated_by=:actor WHERE request_id=:rid""",
            firstDay=body.starts_on, lastDay=body.ends_on, neededBy=body.needed_by, hours=body.total_hours,
            actor=actor.subject, rid=request_id)
        audit(c, actor, request_id, 'REQUEST_RESCHEDULED',
              f'Revision {body.revision}: new period {body.starts_on} to {body.ends_on}, remaining effort {body.total_hours} hours. Rerun required.')
        return {'request_id': request_id, 'rerun_required': True}
