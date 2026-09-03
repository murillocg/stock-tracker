"""Per-category rulesets. The limits are the investment thesis, written as data.

Every threshold here is a judgement call, not a fact. They live in one place, as
named constants, so they are easy to find and argue with — which is the point.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from shared.categories.signals import Check, Elasticity, Signal
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
BRAZILIAN_PE_BAND = Band(green=Decimal("15"), yellow=Decimal("25"))
INTERNATIONAL_PE_BAND = Band(green=Decimal("25"), yellow=Decimal("35"))
"""P/E limits by where the BUSINESS is, not where the ticker trades.

A P/E is roughly 1 / (discount rate - growth), and the discount rate is set by
the local risk-free rate. Brazil's Selic runs in double digits; US Treasuries are
around 4%. That one input compresses every Brazilian multiple, which is why
BBDC3 at 6.55 is genuinely cheap while MSFT at 28.64 is unremarkable.

Judging both against a single band would mark half the US portfolio as expensive
and flatter the Brazilian half, in a way that looks like analysis but is really
just a currency of measurement error.

Keyed on the business rather than the listing because of BDRs. MSFT34 is a
B3-listed receipt for Microsoft: its earnings are American and its multiple has
to be read against American rates. Judged by its listing it scored RED at a P/E
of 28.04 while MSFT itself scored YELLOW at 28.64 — the same company, opposite
verdicts, decided by which exchange the paper trades on.
"""


def stalwart_pe_band(is_foreign: bool) -> Band:
    """The band to judge a P/E against. `Stock.is_foreign` is the input, so a BDR
    is measured against the country its earnings come from."""
    return INTERNATIONAL_PE_BAND if is_foreign else BRAZILIAN_PE_BAND


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


HEADROOM_FLOOR = Decimal("0.2")
HEADROOM_CEILING = Decimal("4")
"""Clamps on a single check's headroom.

Without them one extreme swamps the rest: MU's P/B of 10.49 against a limit of 1
is a headroom of 0.095, and a PEG of 0.31 against 1 is 3.2. Both are true and
neither deserves to decide a whole stock's number on its own.
"""


def headroom(value: Decimal | None, band: Band) -> Decimal | None:
    """How far `value` sits from its target, normalised so directions compare.

    Lower-is-better divides the target by the value, higher-is-better does the
    reverse, so both give "multiples of room" and a P/E can be weighed against an
    ROE. 1.0 is exactly at target.

    `None` where the question does not apply — a missing value, or a band with a
    green threshold of zero, which is how the payout rule is expressed. Payout is
    unhealthy at BOTH ends (a company paying 15% is hoarding, one paying 110% is
    borrowing to pay you), and a range has no single direction to measure from.
    """
    if value is None or band.green == 0:
        return None

    if not band.lower_is_better:
        if value <= 0:
            return HEADROOM_FLOOR
        return _clamp(value / band.green)

    # Zero or negative beats any ceiling: BPAC11's net debt / EBITDA of -6 is net
    # cash, which is not "infinitely good" but is certainly at the top of the
    # scale rather than off the bottom of it, where a raw division would put it.
    if value <= 0:
        return HEADROOM_CEILING
    return _clamp(band.green / value)


def _clamp(ratio: Decimal) -> Decimal:
    bounded = min(max(ratio, HEADROOM_FLOOR), HEADROOM_CEILING)
    return bounded.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _verdict(value: Decimal, band: Band, signal: Signal, unit: str) -> str:
    """State the number against the limit it was judged by.

    Generated from the band rather than written by hand, so a threshold and the
    sentence describing it cannot drift apart — change the constant and every
    explanation that quotes it changes with it.
    """
    shown = f"{value}{unit}"
    green, yellow = f"{band.green}{unit}", f"{band.yellow}{unit}"

    if band.lower_is_better:
        if signal is Signal.GREEN:
            return f"{shown}, within the {green} limit."
        if signal is Signal.YELLOW:
            return f"{shown}, past the {green} target but still under {yellow}."
        return f"{shown}, over the {yellow} limit."

    if signal is Signal.GREEN:
        return f"{shown}, at or above the {green} mark."
    if signal is Signal.YELLOW:
        return f"{shown}, short of {green} though still above {yellow}."
    return f"{shown}, below {yellow}."


def check(
    name: str,
    value: Decimal | None,
    band: Band,
    meaning: str,
    *,
    unit: str = "",
    elasticity: Elasticity = Elasticity.INDEPENDENT,
) -> Check:
    """Build a `Check` whose explanation answers "why is this that colour?".

    `meaning` says why the indicator matters for this category; the verdict clause
    in front of it is derived from the band. "Return on equity." was a definition,
    not a reason — and a reason is the only thing a traffic light owes you.
    """
    signal = band_signal(value, band)
    if signal is Signal.INSUFFICIENT_DATA or value is None:
        return Check(
            name=name,
            value=None,
            signal=Signal.INSUFFICIENT_DATA,
            explanation=f"{name} is not available from any free data source for this stock.",
            elasticity=elasticity,
            green=band.green,
        )
    return Check(
        name=name,
        value=value,
        signal=signal,
        explanation=f"{_verdict(value, band, signal, unit)} {meaning}",
        elasticity=elasticity,
        green=band.green,
        headroom=headroom(value, band),
    )


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
        "Debt against the cash the business generates. Past 3x, one bad year turns "
        "into a solvency question rather than a profit one.",
        unit="x",
    )
