"""Expressing holdings priced in different currencies in one of them.

Only conversion lives here — no rate fetching. The USDBRL rate is collected like
any other price (Banco Central, stored as a REFERENCE ticker) and handed in. That
split is what lets the portfolio maths be tested with a rate of 5.20 and no
network at all.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from shared.models import Currency

MONEY = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ExchangeRates:
    """Rates into one base currency.

    A dataclass rather than a Pydantic model: CLAUDE.md puts Pydantic at the
    boundaries, and this never crosses one — it is assembled in the handler from
    a snapshot that was already validated on the way in. (For a Java eye:
    `frozen=True` gives the immutability of a record, and `slots=True` drops the
    per-instance `__dict__`, which is roughly what a record does for free.)
    """

    base: Currency
    rates: Mapping[Currency, Decimal] = field(default_factory=dict)
    """Units of `base` per one unit of the key. USD -> 5.20 reads as $1 = R$5.20.

    A missing currency is not an error and not a zero: it means the rate was
    never collected, and the caller has to decide what to do about that. Every
    method here therefore returns `None` rather than guessing at 1:1.
    """

    def rate_for(self, currency: Currency) -> Decimal | None:
        """The multiplier for `currency`, or `None` if it is not known.

        The base converts to itself at exactly 1, which is what lets callers
        treat BRL and USD holdings through the same code path instead of
        branching on currency everywhere.
        """
        if currency is self.base:
            return Decimal(1)
        return self.rates.get(currency)

    def convert(self, amount: Decimal, currency: Currency) -> Decimal | None:
        rate = self.rate_for(currency)
        if rate is None:
            return None
        return (amount * rate).quantize(MONEY, rounding=ROUND_HALF_UP)
