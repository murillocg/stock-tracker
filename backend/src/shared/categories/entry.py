"""The price at which a stock would satisfy its own category's rules.

The watchlist question — *has it fallen far enough to be interesting?* — has an
answer already implied by the thresholds. A price-based ratio moves in step with
the price, so a limit can be turned around into the price that would meet it.

Pure functions: an evaluation and a price in, an entry price out. No repository,
no clock, nothing to stub.
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from pydantic import Field

from shared.categories.signals import Check, Elasticity, Signal
from shared.models import CamelModel

MONEY = Decimal("0.01")

SANITY_MULTIPLE = Decimal("5")
"""How far past its limit a ratio may sit and still be worth inverting.

KLBN4 shows a P/E of 133 against a limit of 15 — nearly nine times over. That
inverts to an entry price of R$ 0,43, which is not a target but an artefact of
one depressed quarter's earnings. Beyond this multiple the ratio itself is not
describing the business, so no price derived from it means anything.
"""


class EntryPrice(CamelModel):
    """Where this stock's own rules would turn green, and what stands in the way."""

    price: Decimal | None = None
    """The highest price at which every price-based check would be green.

    `None` when nothing could be inverted — no price-based check had a value, or
    the only ones that did were too far out to be meaningful.
    """

    discount_needed: Decimal | None = None
    """Percentage move from today's price to the entry price.

    Negative means a fall is needed; positive means the price is already below
    the entry and the stock is cheap on these tests today. Expressed as a signed
    percentage so it sorts naturally.
    """

    blocked_by: list[str] = Field(default_factory=list)
    """Checks that are failing and that price cannot repair.

    A low return on equity does not become high because the shares got cheaper.
    When this is non-empty the entry price is still reported — the price tests
    are a real fact — but it is not a buy signal, and the screen must say so.
    """

    unbounded: list[str] = Field(default_factory=list)
    """Price-based checks skipped for being too far past their limit to invert."""


def _target_for(check: Check, price: Decimal) -> Decimal | None:
    """The price at which one check would turn green, or `None` if not invertible."""
    if check.value is None or check.green is None or check.green <= 0 or price <= 0:
        return None

    if check.elasticity is Elasticity.PROPORTIONAL:
        if check.value <= 0:
            return None
        if check.value > check.green * SANITY_MULTIPLE:
            return None
        # ratio = price / metric, so price = ratio x metric.
        return price * check.green / check.value

    if check.elasticity is Elasticity.INVERSE:
        if check.value <= 0:
            return None
        # yield = income / price, so a lower price raises it.
        return price * check.value / check.green

    return None


def entry_price(checks: Sequence[Check], price: Decimal) -> EntryPrice:
    """Where `price` would have to be for every price-based check to be green.

    The minimum across those checks, because all of them have to pass: a stock
    cheap enough on P/E but not on P/B is not cheap enough.

    A price-based check already green contributes a target ABOVE today's price,
    which is correct and is what makes `discount_needed` positive for a stock
    that is already interesting.
    """
    targets: list[Decimal] = []
    blocked: list[str] = []
    unbounded: list[str] = []

    for item in checks:
        if item.elasticity is Elasticity.INDEPENDENT:
            # Price cannot move it, so a failure here is structural. YELLOW is a
            # caveat rather than a bar and is deliberately not listed.
            if item.signal is Signal.RED:
                blocked.append(item.name)
            continue

        target = _target_for(item, price)
        if target is None:
            if item.value is not None:
                unbounded.append(item.name)
            continue
        targets.append(target)

    if not targets:
        return EntryPrice(blocked_by=blocked, unbounded=unbounded)

    entry = min(targets).quantize(MONEY, rounding=ROUND_HALF_UP)
    move = ((entry - price) / price * 100).quantize(MONEY, rounding=ROUND_HALF_UP)
    return EntryPrice(
        price=entry,
        discount_needed=move,
        blocked_by=blocked,
        unbounded=unbounded,
    )
