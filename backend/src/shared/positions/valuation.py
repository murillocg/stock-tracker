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

    `None` when it cannot be computed — which today means anything priced in a
    currency other than the one the portfolio is totalled in. Mixing a USD
    holding into a BRL total without an exchange rate would not be an
    approximation, it would be an addition of unlike things.
    """


def value(position: Position, price: Decimal) -> Valuation:
    """Price one position. Pure: a position and a price in, a valuation out."""
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
    )


def with_weights(valuations: Mapping[str, Valuation]) -> dict[str, Valuation]:
    """Add each holding's share of the total.

    Weight is the number the whole of Phase 3 exists for: a green light on a
    stock says nothing useful if it is already a fifth of the portfolio.

    Returns new objects rather than mutating — `Valuation` is frozen, like every
    model here.
    """
    total = sum((v.market_value for v in valuations.values()), Decimal(0))
    if total == 0:
        return dict(valuations)

    return {
        ticker: valuation.model_copy(
            update={
                "weight": (valuation.market_value / total * 100).quantize(
                    PERCENT, rounding=ROUND_HALF_UP
                )
            }
        )
        for ticker, valuation in valuations.items()
    }
