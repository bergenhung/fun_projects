"""Open-now and today's hours, worked out in the restaurant's own time zone.

Done when each response is sent (not when it's cached), so a result cached at lunchtime still
says "Closed" at midnight.
"""
from datetime import datetime, timedelta, timezone

from app.models import Hours, ResultTable

WEEK = 7 * 24 * 60


def _minute_of_week(point: dict) -> int:
    # Google: day 0 = Sunday.
    return point.get("day", 0) * 1440 + point.get("hour", 0) * 60 + point.get("minute", 0)


def is_open(hours: Hours, now_utc: datetime) -> bool | None:
    if not hours.periods or hours.utc_offset_minutes is None:
        return None
    local = now_utc + timedelta(minutes=hours.utc_offset_minutes)
    now = ((local.weekday() + 1) % 7) * 1440 + local.hour * 60 + local.minute  # Sunday = 0
    for period in hours.periods:
        if "close" not in period:
            return True  # open 24 hours
        start, end = _minute_of_week(period["open"]), _minute_of_week(period["close"])
        if end <= start:
            end += WEEK  # crosses midnight on Saturday night
        if start <= now < end or start <= now + WEEK < end:
            return True
    return False


def today_text(hours: Hours, now_utc: datetime) -> str | None:
    if len(hours.weekday_text) != 7:
        return None
    offset = hours.utc_offset_minutes or 0
    line = hours.weekday_text[(now_utc + timedelta(minutes=offset)).weekday()]  # Monday first
    for sep in (": ", "：", ":"):
        if sep in line:
            return line.split(sep, 1)[1].strip()
    return line


def refresh(table: ResultTable, now_utc: datetime | None = None) -> ResultTable:
    now_utc = now_utc or datetime.now(timezone.utc)
    for row in table.rows:
        if row.hours:
            row.hours.open_now = is_open(row.hours, now_utc)
            row.hours.today = today_text(row.hours, now_utc)
    return table
