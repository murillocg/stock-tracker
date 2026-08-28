"""Shared numeric helpers. Every indicator is built on these two rules."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PERCENT_PRECISION = Decimal("0.01")
"""Percentages are stored to 2 decimal places: -3.25 means "fell 3.25%"."""

RATIO_PRECISION = Decimal("0.0001")
"""Bare ratios (PEG) keep 4 places — the FAST_GROWER cut-off sits at exactly 1."""


def safe_divide(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    """Divide, or return `None` if the result would be meaningless.

    Missing input and division by zero are the normal case here, not an error:
    free-tier APIs omit fields constantly. Returning `None` lets one indicator
    degrade without costing us the whole snapshot.
    """
    if numerator is None or denominator is None or denominator == 0:
        return None
    try:
        return numerator / denominator
    except (InvalidOperation, ArithmeticError):
        return None


def _quantize(value: Decimal | None, precision: Decimal) -> Decimal | None:
    if value is None:
        return None
    try:
        return value.quantize(precision, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ArithmeticError):
        # `quantize` raises rather than silently losing digits when the result
        # exceeds the context precision (28 significant digits by default).
        return None


def as_percentage(fraction: Decimal | None) -> Decimal | None:
    """Fraction -> percentage rounded to 2 places. 0.1532 -> 15.32."""
    return _quantize(None if fraction is None else fraction * 100, PERCENT_PRECISION)


def as_ratio(value: Decimal | None) -> Decimal | None:
    """Round a bare ratio to 4 places, leaving its scale alone."""
    return _quantize(value, RATIO_PRECISION)
