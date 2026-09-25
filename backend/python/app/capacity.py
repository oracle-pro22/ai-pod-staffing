from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from pydantic import Field, model_validator

from app.contracts import Contract, DailyHours

ZERO = Decimal("0")
CENT = Decimal("0.01")


class CapacityLedger(Contract):
    weekly_hours: Decimal = Field(default=Decimal("40"), gt=0, le=80, decimal_places=2, allow_inf_nan=False)
    # Daily aggregates only. Repository must de-duplicate source events before building these lists.
    absences: tuple[DailyHours, ...] = ()
    # Approved scheduled work that still counts: open assignments plus closed
    # assignments' dates through their closure day. This is not actual time spent.
    confirmed_work: tuple[DailyHours, ...] = ()
    # Self-reported existing PODs count until linked/dismissed; not assignments.
    reported_pod_work: tuple[DailyHours, ...] = ()
    external_work: tuple[DailyHours, ...] = ()

    @model_validator(mode="after")
    def unique_daily_aggregates(self):
        for entries in (self.absences, self.confirmed_work, self.reported_pod_work, self.external_work):
            if len({row.day for row in entries}) != len(entries):
                raise ValueError("Duplicate dates: pass de-duplicated daily aggregates")
        return self


class WeeklyCapacity(Contract):
    week_start: date
    available_hours: Decimal
    committed_hours: Decimal
    proposed_hours: Decimal
    allocation_pct: Decimal | None


class CapacityResult(Contract):
    weeks: tuple[WeeklyCapacity, ...]
    overloaded_days: tuple[date, ...]
    no_working_days: bool
    feasible: bool


def dates_between(start: date, end: date):
    if end < start or (end - start).days > 380:
        raise ValueError("Invalid or excessive schedule")
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def spread_hours(hours: Decimal, start: date, end: date) -> tuple[DailyHours, ...]:
    """Even Mon–Fri distribution in cents of hours; totals never drift with rounding."""
    if not hours.is_finite() or hours <= 0 or hours > 100000 or hours != hours.quantize(CENT):
        raise ValueError("Provide positive hours with at most two decimal places")
    days = [day for day in dates_between(start, end) if day.weekday() < 5]
    if not days:
        raise ValueError("The schedule contains no working days")
    quotient, remainder = divmod(int(hours * 100), len(days))
    return tuple(DailyHours(day=day, hours=Decimal(quotient + (index < remainder)) / 100)
                 for index, day in enumerate(days))


def calculate_capacity(ledger: CapacityLedger, start: date, end: date, proposed: tuple[DailyHours, ...],
                       maximum_pct: Decimal = Decimal("100"), *, allow_empty_weeks: bool = False) -> CapacityResult:
    """Checks full weekly buckets AND individual days. No proposal reservations are included."""
    list(dates_between(start, end))  # Validate bounds before expanding full weeks.
    if not maximum_pct.is_finite() or not ZERO < maximum_pct <= 100:
        raise ValueError("Invalid capacity ceiling")
    if len({row.day for row in proposed}) != len(proposed) or any(not start <= row.day <= end for row in proposed):
        raise ValueError("Proposed dates must be unique and within the request period")
    week_start = start - timedelta(days=start.weekday())
    week_end = end + timedelta(days=6 - end.weekday())
    absence, confirmed, external, proposal = [{row.day: row.hours for row in entries}
        for entries in (ledger.absences, ledger.confirmed_work, ledger.external_work, proposed)]
    for row in ledger.reported_pod_work:
        confirmed[row.day] = confirmed.get(row.day, ZERO) + row.hours
    weeks = []
    overloaded = []
    daily_capacity = ledger.weekly_hours / 5
    current = week_start
    while current <= week_end:
        available = committed = planned = ZERO
        for day in dates_between(current, current + timedelta(days=6)):
            base = daily_capacity if day.weekday() < 5 else ZERO
            capacity = max(ZERO, base - absence.get(day, ZERO))
            work = confirmed.get(day, ZERO) + external.get(day, ZERO)
            addition = proposal.get(day, ZERO)
            available += capacity
            committed += work
            planned += addition
            if work + addition > capacity * maximum_pct / 100:
                overloaded.append(day)
        percent = ((committed + planned) / available * 100).quantize(CENT, rounding=ROUND_HALF_UP) if available else None
        weeks.append(WeeklyCapacity(week_start=current, available_hours=available,
                                    committed_hours=committed, proposed_hours=planned, allocation_pct=percent))
        current += timedelta(days=7)
    no_working_days = not any(day.weekday() < 5 for day in dates_between(start, end))
    # Explicit request-window check prevents a short, heavily loaded period
    # being hidden by quieter days elsewhere in the complete calendar week.
    window_available = window_committed = window_proposed = ZERO
    for day in dates_between(start, end):
        base = daily_capacity if day.weekday() < 5 else ZERO
        window_available += max(ZERO, base - absence.get(day, ZERO))
        window_committed += confirmed.get(day, ZERO) + external.get(day, ZERO)
        window_proposed += proposal.get(day, ZERO)
    window_feasible = window_committed + window_proposed <= window_available * maximum_pct / 100
    # Compare exact hours, not rounded displayed percentages.
    feasible = not no_working_days and not overloaded and window_feasible and all(
        (week.available_hours > 0 or allow_empty_weeks) and week.committed_hours + week.proposed_hours <= week.available_hours * maximum_pct / 100
        for week in weeks)
    return CapacityResult(weeks=tuple(weeks), overloaded_days=tuple(overloaded), no_working_days=no_working_days, feasible=feasible)


def distribute_cents(total: int, caps: list[int], minimum: int = 0) -> list[int] | None:
    """Bounded deterministic water-fill, preserving every hundredth of an hour."""
    if (type(total) is not int or type(minimum) is not int or total < 0 or minimum < 0
            or any(type(cap) is not int or cap < 0 for cap in caps)):
        raise ValueError("Hour budgets must be nonnegative integer cents")
    if not caps or min(caps) < minimum or total < minimum * len(caps) or sum(caps) < total:
        return None
    result = [minimum] * len(caps)
    remaining = total - sum(result)
    while remaining:
        available = [i for i, cap in enumerate(caps) if result[i] < cap]
        increment = max(1, remaining // len(available))
        for index in available:
            addition = min(increment, caps[index] - result[index], remaining)
            result[index] += addition
            remaining -= addition
    return result


def available_day_caps(ledger: CapacityLedger, start: date, end: date,
                       maximum_pct: Decimal = Decimal(100)) -> dict[date, int]:
    """Free daily cents AFTER absence, external work and confirmed assignments.

    Check complete touched weeks first, including commitments outside the request
    interval. Pending proposals are intentionally absent from CapacityLedger.
    """
    base = calculate_capacity(ledger, start, end, (), maximum_pct, allow_empty_weeks=True)
    if not base.feasible:
        return {}
    absence = {item.day: item.hours for item in ledger.absences}
    work = {}
    for item in (*ledger.external_work, *ledger.confirmed_work, *ledger.reported_pod_work):
        work[item.day] = work.get(item.day, ZERO) + item.hours
    result = {}
    for day in dates_between(start, end):
        available = max(ZERO, ledger.weekly_hours / 5 - absence.get(day, ZERO)) if day.weekday() < 5 else ZERO
        free = available * maximum_pct / 100 - work.get(day, ZERO)
        if free > 0:
            cents = int((free * 100).to_integral_value(rounding=ROUND_DOWN))
            if cents:
                result[day] = cents
    return result


def schedule_available_hours(ledger: CapacityLedger, hours: Decimal, start: date, end: date,
                             maximum_pct: Decimal = Decimal(100)) -> tuple[DailyHours, ...]:
    """Spread a contribution over only dates with real available headroom."""
    if not hours.is_finite() or hours <= 0 or hours > 100000 or hours != hours.quantize(CENT):
        raise ValueError("Provide positive hours with at most two decimal places")
    caps = available_day_caps(ledger, start, end, maximum_pct)
    days = sorted(caps)
    assigned = distribute_cents(int(hours * 100), [caps[day] for day in days])
    if assigned is None:
        raise ValueError("Requested contribution does not fit available dates")
    return tuple(DailyHours(day=day, hours=Decimal(value) / 100)
                 for day, value in zip(days, assigned, strict=True) if value)
