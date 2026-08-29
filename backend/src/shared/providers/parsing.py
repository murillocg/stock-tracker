"""Shared coercion for values arriving off the wire. Used by every provider."""

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any

from shared.indicators.arithmetic import as_ratio


def to_decimal(value: Any) -> Decimal | None:
    """Coerce one JSON number to `Decimal`, or `None` if it is unusable.

    JSON numbers arrive as `float`, which cannot represent 0.1 exactly. Going
    through `str` first is what stops 4.5 from becoming 4.4999999999999996 — the
    same reason you would never hold money in a Java `double`.

    `bool` is rejected explicitly because in Python `bool` is a *subclass of
    `int`*, so `Decimal(str(True))` would otherwise be a confusing failure and
    `isinstance(True, int)` is `True`. That surprises everyone once.

    A field we cannot parse becomes `None` rather than an exception: one bad
    indicator must not cost us the whole response.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def to_ratio(value: Any) -> Decimal | None:
    """Coerce a JSON number to `Decimal` and round it to 4 places.

    Providers hand back whatever precision their own arithmetic produced —
    brapi's P/E arrived as 4.208420706782756, sixteen significant digits of
    which about four are meaningful. Rounding here keeps the fetched indicators
    on the same footing as the ones `shared.indicators` computes, and keeps the
    DynamoDB items small.

    Ratios only. Prices keep their full precision.
    """
    return as_ratio(to_decimal(value))


def to_date(value: Any) -> dt.date | None:
    """Coerce an ISO 8601 date string to `date`, or `None` if it is unusable.

    Accepts a full timestamp too, since some APIs send `2026-06-30T00:00:00Z`
    where they document a date.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None
