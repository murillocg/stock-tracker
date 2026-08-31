"""When the collector next runs, derived from its own EventBridge schedule.

The schedule lives in Terraform, and the API is told about it through an
environment variable rather than by querying EventBridge: the read Lambda has no
business holding scheduler permissions, and one variable is cheaper than an IAM
policy plus an API call on every page load.

Only the shape this project actually uses is parsed — `cron(m h ? * DAYS *)`.
Anything else returns `None` rather than a guess, and the screen simply says
nothing about the next run. A wrong time would be worse than no time: the whole
point of the line is knowing whether your data is about to refresh.
"""

import datetime as dt
import re
from zoneinfo import ZoneInfo

DEFAULT_SCHEDULE = "cron(0 20 ? * MON-FRI *)"
DEFAULT_TIMEZONE = "America/Sao_Paulo"
"""Defaults in one place, so `Config` and the API agree without repeating
themselves. They mirror `var.collection_schedule` in Terraform."""

CRON = re.compile(r"^cron\(\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*\)$")

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
"""Indexed to match `date.weekday()`, where Monday is 0."""

HORIZON = 8
"""Days to look ahead. A weekly schedule recurs within seven, so anything that
finds nothing in eight is a pattern we cannot honour — say nothing instead."""


def _weekdays(field: str) -> set[int] | None:
    """The days a `MON-FRI`, `MON,WED` or `*` field selects, as weekday numbers."""
    if field in ("*", "?"):
        return set(range(7))

    selected: set[int] = set()
    for part in field.upper().split(","):
        if "-" in part:
            start, _, end = part.partition("-")
            if start not in WEEKDAYS or end not in WEEKDAYS:
                return None
            first, last = WEEKDAYS.index(start), WEEKDAYS.index(end)
            # A range can wrap: FRI-MON is Friday through Monday.
            selected |= {(first + step) % 7 for step in range((last - first) % 7 + 1)}
        elif part in WEEKDAYS:
            selected.add(WEEKDAYS.index(part))
        else:
            return None
    return selected or None


def next_run(expression: str, timezone: str, now: dt.datetime) -> dt.datetime | None:
    """The first firing strictly after `now`, in the schedule's own timezone.

    `now` is a parameter rather than read from the clock so this stays a pure
    function — the same call twice gives the same answer, and the tests do not
    have to wait for 20:00 to come round.
    """
    match = CRON.match(expression.strip())
    if match is None:
        return None
    minute, hour, _day_of_month, month, day_of_week, _year = match.groups()

    if month not in ("*", "?"):
        return None  # a monthly restriction this parser does not model
    if not (minute.isdigit() and hour.isdigit()):
        return None  # steps, ranges and lists in the time fields are not modelled

    days = _weekdays(day_of_week)
    if days is None:
        return None

    try:
        zone = ZoneInfo(timezone)
    except Exception:
        return None

    local = now.astimezone(zone)
    candidate = local.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    if candidate <= local:
        candidate += dt.timedelta(days=1)

    for _ in range(HORIZON):
        if candidate.weekday() in days:
            return candidate
        candidate += dt.timedelta(days=1)
    return None
