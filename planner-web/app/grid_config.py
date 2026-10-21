"""Grid layout constants, mirroring the original Swift app's GridConfig."""

GRID_START_HOUR = 7
GRID_END_HOUR = 19  # exclusive; last visible row is 6 PM - 7 PM

HOUR_HEIGHT_PX = 64
HOUR_GUTTER_PX = 60

DURATION_OPTIONS = [15, 30, 45, 60, 75, 90, 105, 120]
MINUTE_OPTIONS = [0, 15, 30, 45]

# Below this rendered block height (px), a task's content can't fit the
# normal two-line (title + time) layout without overflowing its slot -
# render single-line instead. Learned the hard way in the Swift version
# (see CLAUDE.md "Past bug": short tasks looked misaligned because nothing
# clipped overflowing content) - porting that fix in from day one here.
TWO_LINE_MIN_HEIGHT_PX = 40


def hour_label(hour: int) -> str:
    normalized = hour % 24
    period = "AM" if normalized < 12 else "PM"
    display_hour = normalized % 12
    if display_hour == 0:
        display_hour = 12
    return f"{display_hour} {period}"


def time_label(hour: int, minute: int) -> str:
    if minute == 0:
        return hour_label(hour)
    normalized = hour % 24
    period = "AM" if normalized < 12 else "PM"
    display_hour = normalized % 12
    if display_hour == 0:
        display_hour = 12
    return f"{display_hour}:{minute:02d} {period}"


def duration_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, remainder = divmod(minutes, 60)
    if remainder == 0:
        return f"{hours} hr"
    return f"{hours} hr {remainder} min"
