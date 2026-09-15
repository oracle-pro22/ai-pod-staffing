"""SQLite adapter for Oracle's one timezone expression; predicates stay unchanged.

The native Oracle expression must also be checked against Oracle before release.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.storage import CLOSURE_DAY_SQL


def register_closure_day(connection):
    def closure_day(timestamp, zone):
        if timestamp is None:
            return None
        instant = datetime.fromisoformat(timestamp)
        if instant.tzinfo is None:
            raise ValueError("Closure requires a timezone-aware timestamp")
        return instant.astimezone(ZoneInfo(zone)).date().isoformat()
    connection.create_function("closure_day", 2, closure_day)


def sqlite_closure_sql(sql):
    return sql.replace(CLOSURE_DAY_SQL, "closure_day(a.closed_at, closure_policy.scheduling_timezone)")
