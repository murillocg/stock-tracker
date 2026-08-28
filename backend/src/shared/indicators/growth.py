"""Year-over-year growth from two statement figures."""

from decimal import Decimal

from shared.indicators.arithmetic import as_percentage, safe_divide


def year_over_year(*, current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    """Growth from `previous` to `current`, as a percentage.

    Returns `None` when the base year is zero or negative. Growth measured from a
    loss is arithmetically computable and economically nonsense: a swing from
    -100 to +50 is not "150% growth". That case is precisely a TURNAROUND, which
    CLAUDE.md reserves for human judgement — so we emit nothing rather than a
    number that would feed a ruleset a lie.
    """
    if current is None or previous is None or previous <= 0:
        return None
    return as_percentage(safe_divide(current - previous, previous))
