"""One evaluator per Lynch category, and the dispatch that picks between them.

Each function takes a snapshot and returns the checks that matter *for that
category*. That is the whole idea: a P/E of 32 is alarming for a STALWART and
irrelevant for a CYCLICAL at the bottom of its cycle.
"""

from decimal import Decimal

from shared.categories.rules import (
    ASSET_PLAY_PB_BAND,
    CYCLICAL_PB_BAND,
    DIVIDEND_YIELD_BAND,
    GROWTH_BAND,
    PEG_BAND,
    STALWART_ROE_BAND,
    Band,
    Earnings,
    check,
    earnings_status,
    leverage_check,
    payout_check,
    stalwart_pe_band,
)
from shared.categories.signals import Check, Evaluation, Signal, worst
from shared.indicators import peg
from shared.models import DailySnapshot, LynchCategory, Stock

LOSS_MAKING = Check(
    name="Earnings",
    value=None,
    signal=Signal.NEEDS_REVIEW,
    explanation=(
        "The company is loss-making, so every earnings multiple is undefined. "
        "That is a TURNAROUND question, and a human one."
    ),
)

NO_EARNINGS_DATA = Check(
    name="Earnings",
    value=None,
    signal=Signal.INSUFFICIENT_DATA,
    explanation=(
        "No P/E available from this stock's provider, so nothing earnings-based "
        "can be judged. Not the same as a loss — we simply do not know."
    ),
)


def _earnings_gate(snapshot: DailySnapshot) -> list[Check] | None:
    """The check that replaces a ruleset when earnings cannot carry it."""
    status = earnings_status(snapshot)
    if status is Earnings.LOSS_MAKING:
        return [LOSS_MAKING]
    if status is Earnings.UNKNOWN:
        return [NO_EARNINGS_DATA]
    return None


def fast_grower(stock: Stock, snapshot: DailySnapshot) -> list[Check]:
    """PEG below 1 is the whole thesis: growth you are not overpaying for."""
    gate = _earnings_gate(snapshot)
    if gate is not None:
        return gate

    ratio = peg(pe=snapshot.pe, earnings_growth=snapshot.earnings_cagr_5y)
    return [
        check(
            "PEG",
            ratio,
            PEG_BAND,
            "Lynch's test: under 1 means you are not paying more for the company "
            "than it is growing.",
        ),
        check(
            "Earnings CAGR 5y",
            snapshot.earnings_cagr_5y,
            GROWTH_BAND,
            "A fast grower has to actually be growing; below 10% it belongs in another category.",
            unit="%",
        ),
    ]


def stalwart(stock: Stock, snapshot: DailySnapshot) -> list[Check]:
    """Steady compounder: a fair price, real returns, debt under control."""
    gate = _earnings_gate(snapshot)
    if gate is not None:
        return gate

    return [
        check(
            "P/E",
            snapshot.pe,
            stalwart_pe_band(stock.market),
            "A stalwart is bought for steady compounding, so overpaying for it "
            "spends years of that return up front. The limit follows the market: "
            "a lower risk-free rate supports a higher multiple.",
        ),
        check(
            "ROE",
            snapshot.roe,
            STALWART_ROE_BAND,
            "Return on shareholder capital. Steady returns are the whole reason to "
            "hold a stalwart; without them it is just a large company.",
            unit="%",
        ),
        leverage_check(snapshot, applicable=stock.uses_operating_leverage),
    ]


def slow_grower(stock: Stock, snapshot: DailySnapshot) -> list[Check]:
    """Bought for the dividend, so the dividend has to be real and sustainable.

    Neither input is available on any free plan, so both fall back to the manual
    figures on the stock. A provider value always wins when one exists: the point
    of the manual fields is to fill a gap, not to override live data.
    """
    yield_value = (
        snapshot.dividend_yield
        if snapshot.dividend_yield is not None
        else stock.manual_dividend_yield
    )
    payout_value = (
        snapshot.payout_ratio if snapshot.payout_ratio is not None else stock.manual_payout_ratio
    )
    provenance = (
        f" Entered by hand on {stock.manual_updated_on.isoformat()}."
        if stock.manual_updated_on is not None
        else ""
    )

    return [
        check(
            "Dividend yield",
            yield_value,
            DIVIDEND_YIELD_BAND,
            "The income on today's price — the only reason to hold a slow grower." + provenance,
            unit="%",
        ),
        payout_check(payout_value),
    ]


def asset_play(stock: Stock, snapshot: DailySnapshot) -> list[Check]:
    """Below book value, where the assets are the thesis rather than earnings."""
    return [
        check(
            "P/B",
            snapshot.pb,
            ASSET_PLAY_PB_BAND,
            "Under 1 means paying less than the assets are carried at, which is the "
            "entire asset-play thesis.",
        )
    ]


def cyclical(stock: Stock, snapshot: DailySnapshot) -> list[Check]:
    """P/B against its own band. P/E actively misleads here.

    At the bottom of a cycle earnings collapse and P/E looks *expensive* exactly
    when the stock is cheapest; at the top the reverse. So P/E is deliberately
    absent from this list.
    """
    return [
        check(
            "P/B",
            snapshot.pb,
            CYCLICAL_PB_BAND,
            "Book value is the honest lens across a cycle — earnings collapse at the "
            "bottom, which makes P/E look expensive exactly when the stock is cheapest.",
        )
    ]


def turnaround(stock: Stock, snapshot: DailySnapshot) -> list[Check]:
    """Falling debt and inflecting margins — mostly qualitative."""
    return [
        leverage_check(snapshot, applicable=stock.uses_operating_leverage),
        check(
            "EBITDA margin",
            snapshot.ebitda_margin,
            Band(green=Decimal("20"), yellow=Decimal("10"), lower_is_better=False),
            "For a turnaround the direction matters more than the level: the thesis "
            "is margins inflecting, which one snapshot cannot show.",
            unit="%",
        ),
    ]


_RULESETS = {
    LynchCategory.FAST_GROWER: fast_grower,
    LynchCategory.STALWART: stalwart,
    LynchCategory.SLOW_GROWER: slow_grower,
    LynchCategory.ASSET_PLAY: asset_play,
    LynchCategory.CYCLICAL: cyclical,
    LynchCategory.TURNAROUND: turnaround,
}

HUMAN_JUDGEMENT = frozenset({LynchCategory.CYCLICAL, LynchCategory.TURNAROUND})
"""Categories the app flags but never decides.

Both depend on where you are in a cycle or whether a recovery is real, and
neither is visible in a single snapshot. CLAUDE.md: "the app flags, it does not
decide". So their checks are computed and shown, but the overall signal is always
NEEDS_REVIEW — the numbers inform you, they do not answer for you.
"""


def evaluate(stock: Stock, snapshot: DailySnapshot | None = None) -> Evaluation:
    """Judge one stock by its own category's rules.

    `snapshot` defaults to the denormalised `current` on the registry item, which
    is what the read API will pass.

    Rulesets receive the whole `Stock`, not just the snapshot, because some rules
    turn on facts about the company rather than its numbers — `uses_operating
    _leverage` being the first of them.
    """
    latest = snapshot if snapshot is not None else stock.current

    if latest is None:
        return Evaluation(
            ticker=stock.ticker,
            category=stock.category,
            signal=Signal.INSUFFICIENT_DATA,
            checks=[],
        )

    if stock.category is None:
        return Evaluation(
            ticker=stock.ticker,
            category=None,
            signal=Signal.NEEDS_REVIEW,
            checks=[
                Check(
                    name="Category",
                    value=None,
                    signal=Signal.NEEDS_REVIEW,
                    explanation=(
                        "Not classified yet. The Lynch tag is set by hand, and no "
                        "ruleset applies until it is."
                    ),
                )
            ],
        )

    checks = _RULESETS[stock.category](stock, latest)
    signal = (
        Signal.NEEDS_REVIEW
        if stock.category in HUMAN_JUDGEMENT
        else worst([item.signal for item in checks])
    )
    return Evaluation(
        ticker=stock.ticker,
        category=stock.category,
        signal=signal,
        checks=checks,
    )
