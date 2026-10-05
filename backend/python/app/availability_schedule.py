"""An event's original distribution is immutable when its remaining work ends."""
from datetime import date, datetime
from decimal import Decimal

from app.capacity import spread_hours


def day(value):
    return value.date() if isinstance(value, datetime) else value


def event_days(event):
    cutoff = day(event.get('effective_until'))
    return tuple(entry for entry in spread_hours(Decimal(str(event['allocated_hours'])),
        day(event['starts_on']), day(event['ends_on'])) if cutoff is None or entry.day <= cutoff)


def retained_hours(event, before: date):
    return sum((entry.hours for entry in event_days(event) if entry.day < before), Decimal(0))
