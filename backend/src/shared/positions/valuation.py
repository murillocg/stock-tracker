"""What a position is worth now, and how much of the portfolio it is."""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from shared.models import CamelModel
from shared.positions.position import Position

MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")


class Valuation(CamelModel):
    """A position priced at today's close."""

    market_value: Decimal
    unrealised_gain: Decimal
    unrealised_gain_percent: Decimal

    weight: Decimal | None = None
    """Share of the portfolio, as a percentage.

    `None` only when the holding could not be expressed in the base currency —
    i.e. no exchange rate was collected for it. Mixing a USD holding into a BRL
    total without a rate would not be an approximation, it would be an addition
    of unlike things.
    """

    base_market_value: Decimal | None = None
    """`market_value` in the portfolio's base currency, at today's rate.

    The row itself stays in its own currency — MSFT is worth $1,800, and showing
    it as R$9,361 on its own line would not match what Avenue reports. This field
    exists so the totals and the weights can add USD and BRL together.
    """

    base_invested: Decimal | None = None
    """`invested` converted at TODAY's rate — which is NOT the cost in reais.

    The real BRL cost is each purchase converted at the rate on ITS OWN date, and
    those rates are not in our history: collection began in 2026 and the Avenue
    ledger starts in 2020. So the difference between this and `base_market_value`
    is the USD gain expressed in today's reais, and it deliberately excludes the
    FX movement on the principal.

    That is a coherent number for a buy-and-hold investor who thinks of the US
    sleeve in dollars, and it is the wrong number for tax. Phase 4 needs the
    purchase-date rates, and until it has them nothing here should be presented
    as a cost basis.
    """


def value(position: Position, price: Decimal, rate: Decimal | None = Decimal(1)) -> Valuation:
    """Price one position. Pure: a position, a price and a rate in, a valuation out.

    `rate` converts into the portfolio's base currency, and defaults to 1 because
    a holding already in that currency converts to itself. Pass `None` — never a
    guessed 1 — when the rate is genuinely unknown: it propagates as a `None`
    weight and keeps the holding out of the totals, which is the whole point of
    tracking it separately.
    """
    market_value = (position.quantity * price).quantize(MONEY, rounding=ROUND_HALF_UP)
    gain = market_value - position.invested
    percent = (
        Decimal(0)
        if position.invested == 0
        else (gain / position.invested * 100).quantize(PERCENT, rounding=ROUND_HALF_UP)
    )
    return Valuation(
        market_value=market_value,
        unrealised_gain=gain,
        unrealised_gain_percent=percent,
        base_market_value=(
            None if rate is None else (market_value * rate).quantize(MONEY, ROUND_HALF_UP)
        ),
        base_invested=(
            None if rate is None else (position.invested * rate).quantize(MONEY, ROUND_HALF_UP)
        ),
    )


def with_weights(valuations: Mapping[str, Valuation]) -> dict[str, Valuation]:
    """Add each holding's share of the total.

    Weight is the number the whole of Phase 3 exists for: a green light on a
    stock says nothing useful if it is already a fifth of the portfolio.

    Computed on `base_market_value`, so a BRL and a USD holding are compared in
    one currency. A holding with no rate is left at `weight=None` and excluded
    from the denominator: the remaining weights then describe the part of the
    portfolio we can actually measure, and they still sum to 100.

    Returns new objects rather than mutating — `Valuation` is frozen, like every
    model here.
    """
    total = sum(
        (v.base_market_value for v in valuations.values() if v.base_market_value is not None),
        Decimal(0),
    )
    if total == 0:
        return dict(valuations)

    return {
        ticker: (
            valuation
            if valuation.base_market_value is None
            else valuation.model_copy(
                update={
                    "weight": (valuation.base_market_value / total * 100).quantize(
                        PERCENT, rounding=ROUND_HALF_UP
                    )
                }
            )
        )
        for ticker, valuation in valuations.items()
    }
