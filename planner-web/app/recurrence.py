"""Pure recurrence-date logic, ported from the Swift app's RecurrenceEngine.

Weekday convention matches Python's stdlib: date.weekday() returns
0=Monday .. 6=Sunday, and recurrence_custom_days uses the same numbering.
"""

from datetime import date, timedelta

MATERIALIZATION_WINDOW_DAYS = 60
FREQUENCIES = {"daily", "weekly", "weekdays", "custom"}


def occurrence_dates(
    start_date: date,
    frequency: str,
    custom_days: list[int] | None = None,
    end_date: date | None = None,
    window_days: int = MATERIALIZATION_WINDOW_DAYS,
) -> list[date]:
    """Dates (including start_date) matching the recurrence pattern, within
    `window_days` of start_date and capped by `end_date` if set."""
    custom_days = custom_days or []
    last_day = start_date + timedelta(days=window_days - 1)
    if end_date is not None:
        last_day = min(last_day, end_date)

    dates: list[date] = []
    current = start_date
    while current <= last_day:
        if _matches(current, frequency, custom_days):
            dates.append(current)
        current += timedelta(days=1)
    return dates


def _matches(d: date, frequency: str, custom_days: list[int]) -> bool:
    if frequency == "daily":
        return True
    if frequency == "weekly":
        return True  # caller always starts iteration at start_date's weekday cycle
    if frequency == "weekdays":
        return d.weekday() < 5
    if frequency == "custom":
        return d.weekday() in custom_days
    return False


def occurrence_dates_weekly_fixed(
    start_date: date,
    end_date: date | None,
    window_days: int = MATERIALIZATION_WINDOW_DAYS,
) -> list[date]:
    """Weekly needs the anchor weekday, not just "any day" - step by 7 days."""
    last_day = start_date + timedelta(days=window_days - 1)
    if end_date is not None:
        last_day = min(last_day, end_date)
    dates = []
    current = start_date
    while current <= last_day:
        dates.append(current)
        current += timedelta(days=7)
    return dates


def generate_series_dates(
    start_date: date,
    frequency: str,
    custom_days: list[int] | None = None,
    end_date: date | None = None,
    window_days: int = MATERIALIZATION_WINDOW_DAYS,
) -> list[date]:
    """Entry point used by callers: dispatches weekly to its own stepped
    implementation (every-7-days) since day-by-day matching can't express
    "same weekday as start" on its own."""
    if frequency == "weekly":
        return occurrence_dates_weekly_fixed(start_date, end_date, window_days)
    return occurrence_dates(start_date, frequency, custom_days, end_date, window_days)
