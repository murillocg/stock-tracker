"""Price changes over time, computed from our own DynamoDB history."""

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal
from enum import StrEnum

from shared.indicators.arithmetic import as_percentage, safe_divide
from shared.models import DailySnapshot

DEFAULT_MAX_STALENESS = dt.timedelta(days=7)
"""How far *before* the target date a reference price may sit.

Markets close on weekends and holidays, so there is rarely a snapshot exactly N
days back and we take the nearest one at or before the target. But if collection
was broken for a month, the nearest prior snapshot could be wildly older than the
window — and reporting a 5-week move as `change1w` would be a lie. Beyond this
tolerance we emit nothing instead.
"""


class ChangeWindow(StrEnum):
    """The four look-back windows stored on a snapshot."""

    ONE_WEEK = "ONE_WEEK"
    ONE_MONTH = "ONE_MONTH"
    SIX_MONTHS = "SIX_MONTHS"
    ONE_YEAR = "ONE_YEAR"

    @property
    def delta(self) -> dt.timedelta:
        """How far back this window looks.

        Fixed day counts rather than calendar months: it keeps the module free of
        a `dateutil` dependency, and for a buy-and-hold app the difference between
        30 days and one calendar month is noise.

        A property on an enum member is Python's answer to a Java enum with a
        constructor argument and a getter — same idea, less ceremony.
        """
        return _WINDOW_DELTAS[self]

    @property
    def field_name(self) -> str:
        """The `DailySnapshot` attribute this window populates."""
        return _WINDOW_FIELDS[self]


_WINDOW_DELTAS: dict[ChangeWindow, dt.timedelta] = {
    ChangeWindow.ONE_WEEK: dt.timedelta(days=7),
    ChangeWindow.ONE_MONTH: dt.timedelta(days=30),
    ChangeWindow.SIX_MONTHS: dt.timedelta(days=182),
    ChangeWindow.ONE_YEAR: dt.timedelta(days=365),
}

_WINDOW_FIELDS: dict[ChangeWindow, str] = {
    ChangeWindow.ONE_WEEK: "change_1w",
    ChangeWindow.ONE_MONTH: "change_1m",
    ChangeWindow.SIX_MONTHS: "change_6m",
    ChangeWindow.ONE_YEAR: "change_1y",
}


def percentage_change(*, previous: Decimal | None, current: Decimal | None) -> Decimal | None:
    """Move from `previous` to `current`, as a percentage. -3.25 means a 3.25% fall."""
    if current is None or previous is None or previous <= 0:
        return None
    return as_percentage(safe_divide(current - previous, previous))


def reference_snapshot(
    history: Sequence[DailySnapshot],
    target: dt.date,
    max_staleness: dt.timedelta = DEFAULT_MAX_STALENESS,
) -> DailySnapshot | None:
    """The newest snapshot at or before `target`, if one is close enough.

    Takes a `Sequence` rather than a `list` so any ordered collection works, and
    makes no assumption about ordering — the repositories happen to return oldest
    first, but relying on that would be a trap for the next caller.
    """
    earliest_allowed = target - max_staleness
    candidates = [s for s in history if earliest_allowed <= s.date <= target]
    if not candidates:
        return None
    return max(candidates, key=lambda snapshot: snapshot.date)


def compute_changes(
    history: Sequence[DailySnapshot],
    *,
    as_of: dt.date,
    current_price: Decimal,
    max_staleness: dt.timedelta = DEFAULT_MAX_STALENESS,
) -> dict[ChangeWindow, Decimal]:
    """Every change we can honestly compute for `as_of`.

    `current_price` is passed in rather than read from `history` because today's
    snapshot is still being built when the collector calls this — it is not in
    DynamoDB yet.

    Windows we cannot cover are **omitted** rather than mapped to `None`, so two
    months of history yields 1w and 1m and simply says nothing about 1y.
    """
    changes: dict[ChangeWindow, Decimal] = {}
    for window in ChangeWindow:
        reference = reference_snapshot(history, as_of - window.delta, max_staleness)
        if reference is None:
            continue
        change = percentage_change(previous=reference.price, current=current_price)
        if change is not None:
            changes[window] = change
    return changes


def apply_changes(
    snapshot: DailySnapshot,
    changes: Mapping[ChangeWindow, Decimal],
) -> DailySnapshot:
    """Return a new snapshot carrying `changes`. The original is untouched.

    `DailySnapshot` is frozen, so `model_copy(update=...)` is how you "modify"
    one — the same move as a Java record's wither. Be aware that `update` skips
    validation, which is fine here because the values are already `Decimal`.
    """
    return snapshot.model_copy(
        update={window.field_name: value for window, value in changes.items()}
    )
