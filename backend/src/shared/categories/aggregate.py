"""Combining a stock's per-check headroom into one comparable number.

Kept apart from `rules.py` because it answers a different question. The rules say
whether a stock passes its own category's tests; this says how much room it has
against them, which is what ranks two stocks that both pass.
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from shared.categories.signals import Check

NEUTRAL = Decimal("1")


def overall_headroom(checks: Sequence[Check]) -> Decimal | None:
    """The geometric mean of every measurable check, shrunk toward 1.0.

    Geometric rather than arithmetic because these are ratios: a stock at 2x on
    one measure and 0.5x on another is at its target overall, and only the
    geometric mean says so — the arithmetic mean would call it 1.25.

    The shrink is the important part. A stock judged on ONE lenient check should
    not outrank one judged on three: CPLE3 scored 1.46 on dividend yield alone
    while ITSA4 scored 1.26 across P/E, ROE and leverage, and the raw means put
    the thinner evidence first. Raising the mean to the power n/(n+1) pulls a
    single check most of the way back to neutral and leaves five nearly
    untouched — confidence rising with evidence, which is what the ranking is
    short of.

    Computed with `Decimal.ln`/`Decimal.exp` rather than `float ** float`: the
    fractional power is the one place this would otherwise leave Decimal, and
    there is no reason to reintroduce binary floating point for it.
    """
    measurable = [c.headroom for c in checks if c.headroom is not None and c.headroom > 0]
    if not measurable:
        return None

    count = Decimal(len(measurable))
    mean_log = sum((value.ln() for value in measurable), Decimal(0)) / count
    confidence = count / (count + 1)
    return (mean_log * confidence).exp().quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
