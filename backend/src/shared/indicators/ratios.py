"""Ratios derived from the financial statements. Pure: data in, data out."""

from decimal import Decimal

from shared.indicators.arithmetic import as_percentage, as_ratio, safe_divide


def roic(
    *,
    ebit: Decimal | None,
    tax_rate: Decimal | None,
    equity: Decimal | None,
    net_debt: Decimal | None,
) -> Decimal | None:
    """Return on invested capital, as a percentage.

    NOPAT / invested capital, where NOPAT is EBIT after tax and invested capital
    is equity plus net debt. `tax_rate` is a fraction (0.34), not a percentage.

    Returns `None` when invested capital is zero or negative: a company funded
    entirely by net cash has no meaningful "capital invested" to earn a return
    on, and the resulting number would be noise dressed up as a signal.

    Note the leading `*`: every argument is keyword-only, so `roic(ebit=...,
    tax_rate=...)` is the only way to call it. Four same-typed parameters in a row
    is exactly where a positional call silently transposes two of them — Java has
    no equivalent guard short of a builder.
    """
    if ebit is None or tax_rate is None or equity is None or net_debt is None:
        return None
    if not (0 <= tax_rate < 1):
        return None

    invested_capital = equity + net_debt
    if invested_capital <= 0:
        return None

    nopat = ebit * (1 - tax_rate)
    return as_percentage(safe_divide(nopat, invested_capital))


def payout_ratio(
    *,
    dividends_paid: Decimal | None,
    net_income: Decimal | None,
) -> Decimal | None:
    """Share of earnings paid out as dividends, as a percentage.

    Returns `None` on a loss. A payout ratio against negative earnings is not a
    high number, it is an undefined one — and for SLOW_GROWER the whole question
    is whether the dividend is *sustainable*, which a loss-making year cannot
    answer. Above 100 is left as-is: paying out more than you earn is a real and
    important signal, not an error to clamp away.
    """
    if net_income is None or net_income <= 0:
        return None
    return as_percentage(safe_divide(dividends_paid, net_income))


def peg(*, pe: Decimal | None, earnings_growth: Decimal | None) -> Decimal | None:
    """P/E divided by the earnings growth rate. The FAST_GROWER test (PEG < 1).

    `earnings_growth` is a percentage, matching what `year_over_year` returns, so
    a P/E of 15 against 15% growth gives exactly 1.

    Returns `None` unless both inputs are positive: PEG against shrinking or flat
    earnings is meaningless, and a negative P/E means the company is loss-making,
    which puts it in TURNAROUND territory where the app flags rather than judges.
    """
    if pe is None or pe <= 0 or earnings_growth is None or earnings_growth <= 0:
        return None
    return as_ratio(safe_divide(pe, earnings_growth))
