"""Per-category rulesets. The limits are the investment thesis, written as data.

Every threshold here is a judgement call, not a fact. They live in one place, as
named constants, so they are easy to find and argue with — which is the point.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from shared.categories.signals import Check, Signal
from shared.models import DailySnapshot


@dataclass(frozen=True, slots=True)
class Band:
    """A green/yellow boundary pair for one indicator.

    `lower_is_better` flips the comparison, so a P/E band and an ROE band are the
    same shape rather than two near-identical functions.
    """

    green: Decimal
    yellow: Decimal
    lower_is_better: bool = True


# --- FAST_GROWER: Lynch's PEG test -------------------------------------------
PEG_BAND = Band(green=Decimal("1"), yellow=Decimal("1.5"))
GROWTH_BAND = Band(green=Decimal("20"), yellow=Decimal("10"), lower_is_better=False)

# --- STALWART: pay a fair price for steady quality ----------------------------
STALWART_PE_BAND = Band(green=Decimal("15"), yellow=Decimal("25"))
STALWART_ROE_BAND = Band(green=Decimal("15"), yellow=Decimal("10"), lower_is_better=False)
LEVERAGE_BAND = Band(green=Decimal("2"), yellow=Decimal("3"))

# --- SLOW_GROWER: the dividend, and whether it survives -----------------------
DIVIDEND_YIELD_BAND = Band(green=Decimal("5"), yellow=Decimal("3"), lower_is_better=False)
PAYOUT_COMFORTABLE = Decimal("80")
PAYOUT_UNSUSTAINABLE = Decimal("100")
PAYOUT_FLOOR = Decimal("20")
"""Payout ratio boundaries, judged from both ends.

A high payout is not itself a problem — that was the original mistake here. If a
company has no way to earn a decent return on retained earnings, distributing
them is the *right* capital allocation, and Lynch is scathing about firms that
hoard cash and spend it badly. BBSE3 pays out 96% on an 82% ROE: an asset-light
broker with nothing capital-intensive to reinvest in. That is the business model
working, not a warning.

What actually threatens the dividend is paying out more than you earn, which no
business model sustains — it comes from debt, reserves or asset sales.

So: below 20% the income thesis does not hold and the category is wrong; up to
80% is a comfortable cushion; 80-100% is thin but legitimate; above 100% fails.

The honest caveat is that all of this is a proxy for what really matters, which
is earnings *volatility* — 90% of stable broker fees is safe, 90% of commodity
earnings is not. Once there are a few quarters of history we can measure that
directly instead.
"""


def payout_check(value: Decimal | None) -> Check:
    """Payout ratio, with a reason attached to every verdict."""
    if value is None:
        return check("Payout ratio", None, Band(green=Decimal(0), yellow=Decimal(0)), "")

    if value < PAYOUT_FLOOR:
        signal, why = (
            Signal.RED,
            (
                f"Only {value}% of earnings paid out. A SLOW_GROWER is held for its "
                "income; at this level the category is the wrong one."
            ),
        )
    elif value <= PAYOUT_COMFORTABLE:
        signal, why = (
            Signal.GREEN,
            (f"{value}% of earnings paid out, leaving a comfortable cushion if earnings dip."),
        )
    elif value <= PAYOUT_UNSUSTAINABLE:
        signal, why = (
            Signal.YELLOW,
            (
                f"{value}% of earnings paid out — a thin cushion. Fine for an "
                "asset-light business with nothing worth reinvesting in; worth "
                "watching for anyone else."
            ),
        )
    else:
        signal, why = (
            Signal.RED,
            (
                f"{value}% — paying out more than it earns. Funded by debt, reserves "
                "or asset sales, so it cannot continue indefinitely."
            ),
        )

    return Check(name="Payout ratio", value=value, signal=signal, explanation=why)


# --- ASSET_PLAY: Lynch buys the assets below book -----------------------------
ASSET_PLAY_PB_BAND = Band(green=Decimal("1"), yellow=Decimal("1.5"))

# --- CYCLICAL: P/B against its own history, never P/E -------------------------
CYCLICAL_PB_BAND = Band(green=Decimal("1"), yellow=Decimal("2"))


def band_signal(value: Decimal | None, band: Band) -> Signal:
    """Place one value on a band. Missing input is INSUFFICIENT_DATA, never RED."""
    if value is None:
        return Signal.INSUFFICIENT_DATA
    if band.lower_is_better:
        if value <= band.green:
            return Signal.GREEN
        return Signal.YELLOW if value <= band.yellow else Signal.RED
    if value >= band.green:
        return Signal.GREEN
    return Signal.YELLOW if value >= band.yellow else Signal.RED


def check(name: str, value: Decimal | None, band: Band, explanation: str) -> Check:
    """Build a `Check`, with a fallback explanation when the input is missing."""
    signal = band_signal(value, band)
    if signal is Signal.INSUFFICIENT_DATA:
        return Check(
            name=name,
            value=None,
            signal=signal,
            explanation=f"{name} is not available from any free data source.",
        )
    return Check(name=name, value=value, signal=signal, explanation=explanation)


class Earnings(StrEnum):
    """Whether earnings-based ratios mean anything for this stock."""

    PROFITABLE = "PROFITABLE"
    LOSS_MAKING = "LOSS_MAKING"
    UNKNOWN = "UNKNOWN"


def earnings_status(snapshot: DailySnapshot) -> Earnings:
    """Classify the earnings picture before any multiple is trusted.

    Three states, not two. A negative P/E is a loss-making company — MRVE3 reports
    -3.59, and reading that as a cheap stock is the failure this guards against.
    But a *missing* P/E is something else entirely: SPCX has none because Alpha
    Vantage does not supply one, and telling the user "this company is loss-making"
    on that basis would be asserting a fact we do not have.
    """
    if snapshot.pe is None:
        return Earnings.UNKNOWN
    return Earnings.PROFITABLE if snapshot.pe > 0 else Earnings.LOSS_MAKING


def leverage_check(snapshot: DailySnapshot, *, applicable: bool = True) -> Check:
    """Net debt / EBITDA, the one check financials break.

    Banks, insurers and holdings have no operating net debt — deposits and float
    are raw material, not leverage. BPAC11 collected at -6 and BBAS3 at 12.73;
    both are arithmetic noise, and judging on them is worse than not judging.

    `applicable` comes from `Stock.uses_operating_leverage`, set by hand.
    """
    if not applicable:
        return Check(
            name="Net debt / EBITDA",
            value=snapshot.net_debt_to_ebitda,
            signal=Signal.NOT_APPLICABLE,
            explanation=(
                "Not meaningful for a bank, insurer or holding company: deposits "
                "and float are raw material, not leverage."
            ),
        )
    return check(
        "Net debt / EBITDA",
        snapshot.net_debt_to_ebitda,
        LEVERAGE_BAND,
        "Leverage against operating cash generation.",
    )
