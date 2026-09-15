"""Explicit operator capacity refresh. Dry-run by default; never invent working hours or event types."""
import argparse
import json
from datetime import date, timedelta
from decimal import Decimal

from app.capacity import dates_between, spread_hours
from app.errors import ServiceError
from app.execution_store import execute
from app.storage import rows, calendar_day


def build_days(weekly_hours, start, end, events):
    weekly = Decimal(str(weekly_hours)) if weekly_hours is not None else Decimal(0)
    if not weekly.is_finite() or weekly <= 0 or weekly > 80:
        raise ServiceError("CAPACITY_UNKNOWN", "Set reviewed weekly working hours before refreshing capacity.", 409)
    first, last = start - timedelta(days=start.weekday()), end + timedelta(days=6-end.weekday())
    if (last-first).days > 90:
        raise ServiceError("DATE_RANGE", "Refresh at most 13 complete weeks per operation.", 422)
    result = {d: {"available": weekly/5 if d.weekday() < 5 else Decimal(0), "external": Decimal(0)} for d in dates_between(first, last)}
    for event in events:
        if event["capacity_kind"] not in ("NON_AVAILABILITY", "EXTERNAL_WORK"):
            raise ServiceError("EVENT_CLASSIFICATION", "Classify overlapping legacy availability events before refresh.", 409)
        hours = Decimal(str(event["allocated_hours"]))
        if hours <= 0:
            raise ServiceError("EVENT_HOURS", "Overlapping availability events need explicit positive total hours.", 409)
        for work in spread_hours(hours, calendar_day(event["starts_on"]), calendar_day(event["ends_on"])):
            if work.day in result:
                if event["capacity_kind"] == "NON_AVAILABILITY":
                    result[work.day]["available"] -= work.hours
                else:
                    result[work.day]["external"] += work.hours
    if any(v["available"] < 0 or v["external"] > 24 for v in result.values()):
        raise ServiceError("EVENT_OVERLAP", "Resolve overlapping absence hours or excessive external hours.", 409)
    return result


def refresh(database, person_id, start, end, operator, commit=False):
    context = database.write if commit else database.read
    with context() as connection:
        person = rows(connection, "SELECT weekly_work_hours,availability_version FROM people WHERE person_id=:personId AND active_flag='Y'" + (" FOR UPDATE WAIT 5" if commit else ""), personId=person_id)
        if not person:
            raise ServiceError("PERSON_NOT_FOUND", "Active person not found.", 404)
        # Fresh read after acquiring the same person lock used by approvals and availability writes.
        if commit:
            person = rows(connection, "SELECT weekly_work_hours,availability_version FROM people WHERE person_id=:personId", personId=person_id)
        first, last = start-timedelta(days=start.weekday()), end+timedelta(days=6-end.weekday())
        events = rows(connection, "SELECT availability_id,capacity_kind,starts_on,ends_on,allocated_hours FROM availability WHERE person_id=:personId AND starts_on<=:endDay AND ends_on>=:startDay", personId=person_id, startDay=first, endDay=last)
        days = build_days(person[0]["weekly_work_hours"], start, end, events)
        existing = rows(connection, "SELECT work_date,available_hours,external_committed_hours,source_version FROM person_capacity_days WHERE person_id=:personId AND work_date BETWEEN :startDay AND :endDay", personId=person_id, startDay=first, endDay=last)
        for saved in existing:
            value = days[calendar_day(saved['work_date'])]
            if saved['source_version'] != 'capacity-refresh-v1' and (
                Decimal(str(saved['available_hours'])) < value['available'] or Decimal(str(saved['external_committed_hours'])) > value['external']):
                raise ServiceError('CAPACITY_BASELINE_REVIEW', 'Existing capacity contains additional absence or external work. Preserve and reconcile those inputs before refreshing.', 409)
        if commit:
            for day, value in days.items():
                execute(connection, """MERGE INTO person_capacity_days target USING (SELECT :personId person_id,:workDay work_date FROM dual) src
                    ON (target.person_id=src.person_id AND target.work_date=src.work_date)
                    WHEN MATCHED THEN UPDATE SET available_hours=:availableHours,external_committed_hours=:externalHours,
                        availability_version=:versionNumber,input_refs_json=:refsJson,source_version='capacity-refresh-v1',verified_by=:operatorName,verified_at=SYSTIMESTAMP
                    WHEN NOT MATCHED THEN INSERT(person_id,work_date,available_hours,external_committed_hours,availability_version,input_refs_json,source_version,verified_by,verified_at)
                        VALUES(:personId,:workDay,:availableHours,:externalHours,:versionNumber,:refsJson,'capacity-refresh-v1',:operatorName,SYSTIMESTAMP)""",
                    {"personId": person_id, "workDay": day, "availableHours": value["available"], "externalHours": value["external"],
                     "versionNumber": person[0]["availability_version"], "refsJson": json.dumps({"method": "Mon-Fri equal event hours", "availability_ids": [e["availability_id"] for e in events]}), "operatorName": operator}, ("refsJson",))
        return {"person_id": person_id, "days": len(days), "committed": commit}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--person', required=True)
    parser.add_argument('--start', type=date.fromisoformat, required=True)
    parser.add_argument('--end', type=date.fromisoformat, required=True)
    parser.add_argument('--operator', required=True)
    parser.add_argument('--commit', action='store_true')
    args = parser.parse_args()
    if not args.operator.strip() or len(args.operator) > 255 or args.end < args.start:
        parser.error('Provide a named operator and an ordered date range.')
    from app.database import OracleDatabase
    from app.config import Settings
    database = OracleDatabase(Settings(_env_file=args.env_file))
    try:
        print(json.dumps(refresh(database, args.person, args.start, args.end, args.operator, args.commit)))
    except ServiceError as error:
        print(json.dumps({"error": error.code, "message": error.message}))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"error": "CAPACITY_REFRESH_FAILED", "message": "Operation rolled back. Check configuration and reviewed input data."}))
        raise SystemExit(1) from None
    finally:
        database.close()


if __name__ == '__main__':
    main()
