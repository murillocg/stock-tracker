"""Per-category rulesets. The limits are the investment thesis, written as data.

Every threshold here is a judgement call, not a fact. They live in one place, as
named constants, so they are easy to find and argue with — which is the point.
"""

from dataclasses import dataclass
from decimal import Decimal

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
PAYOUT_BAND = Band(green=Decimal("60"), yellow=Decimal("80"))

PAYOUT_FLOOR = Decimal("20")
"""Below this, a SLOW_GROWER is not one.

The band above is monotonic — lower payout, safer dividend — which is right at
the top end and wrong at the bottom. A company paying out 0% scores "maximally
sustainable" on that logic, when what it actually means is that the income thesis
does not hold and the stock belongs in another category. AXIA3 reports 0.
"""


def payout_check(value: Decimal | None) -> Check:
    """Payout ratio, judged from both ends.

    Too high and the dividend is borrowed from the future; too low and there is
    no dividend to be here for. Only the high end is a matter of degree, so the
    floor is a flat RED rather than another band.
    """
    if value is not None and value < PAYOUT_FLOOR:
        return Check(
            name="Payout ratio",
            value=value,
            signal=Signal.RED,
            explanation=(
                f"Only {value}% of earnings paid out. A SLOW_GROWER is held for "
                "its income; at this level the category is the wrong one."
            ),
        )
    return check(
        "Payout ratio",
        value,
        PAYOUT_BAND,
        "Share of earnings paid out. Above 80% is hard to sustain.",
    )


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


def profitable(snapshot: DailySnapshot) -> bool:
    """Whether earnings-based ratios mean anything at all for this stock.

    A negative P/E is not a cheap stock, it is a loss-making one — MRVE3 in the
    current portfolio reports -3.59. Every earnings multiple has to be gated on
    this or the traffic light reads a loss as a bargain.
    """
    return snapshot.pe is not None and snapshot.pe > 0


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
