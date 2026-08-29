"""Fold a transaction ledger into a position. Pure: data in, data out."""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from shared.models import CamelModel, Currency
from shared.models.transaction import Transaction, TransactionType
from shared.models.types import Ticker

MONEY = Decimal("0.01")
QUANTITY = Decimal("0.00000001")
"""Quantities are Decimal, not int: B3 trades whole shares, but US brokers issue
fractional ones, and a position built from int would silently truncate them."""


class Position(CamelModel):
    """What you hold in one ticker, derived from every trade in it."""

    ticker: Ticker
    currency: Currency
    quantity: Decimal
    average_price: Decimal | None
    """`None` once the position is closed. Not zero — zero would read as "bought
    at nothing" in any ratio built on it."""

    invested: Decimal
    """Quantity times average price: what the shares you still hold cost."""

    realised_gain: Decimal
    """Accumulated across sales. Phase 4 reports on this; nothing reads it yet."""


def _tidy(quantity: Decimal) -> Decimal:
    """Trim a quantity without letting it turn into scientific notation.

    `Decimal("400.00000000").normalize()` is `Decimal("4E+2")` — the same number,
    useless in front of a person. `to_integral_value()` does not help either; it
    keeps the exponent. Only `quantize(Decimal(1))` re-expands the digits.
    """
    trimmed = quantity.quantize(QUANTITY, rounding=ROUND_HALF_UP).normalize()
    return trimmed.quantize(Decimal(1)) if trimmed == trimmed.to_integral_value() else trimmed


class LedgerError(ValueError):
    """The ledger cannot be folded — it describes something impossible."""


def build_position(ticker: str, transactions: Sequence[Transaction]) -> Position | None:
    """Fold trades, oldest first, into the current position.

    Weighted average cost, the Brazilian convention:

    - a BUY moves the average toward the new price, in proportion to size
    - a SELL reduces the quantity and **leaves the average untouched**, booking
      `(price - average) x quantity` as a realised gain
    - a BONUS adds free shares, leaving the invested amount alone, so the average
      falls in proportion — which is what a split does

    That second rule is the one that surprises people used to FIFO. Under FIFO a
    sale consumes specific lots and the remaining average shifts; here it cannot,
    which is why the average price of a long-held position is stable no matter
    how much you trade around it.

    Returns `None` for an empty ledger — no transactions is not a zero position,
    it is no position.
    """
    if not transactions:
        return None

    ordered = sorted(transactions, key=lambda t: (t.date, t.id))
    currency = ordered[0].currency

    quantity = Decimal(0)
    average = Decimal(0)
    realised = Decimal(0)

    for transaction in ordered:
        if transaction.currency is not currency:
            raise LedgerError(
                f"{ticker} has trades in both {currency} and {transaction.currency}; "
                "a single position cannot span two currencies."
            )

        if transaction.type is TransactionType.BONUS:
            # Free shares: the amount invested does not move, so dividing it over
            # a larger quantity lowers the average by itself. A 2:1 split is
            # exactly "as many free shares as you already hold".
            invested = quantity * average
            quantity += transaction.quantity
            average = invested / quantity
            continue

        if transaction.type is TransactionType.BUY:
            cost = quantity * average + transaction.quantity * transaction.unit_price
            quantity += transaction.quantity
            average = cost / quantity
            continue

        if transaction.quantity > quantity:
            raise LedgerError(
                f"{ticker}: selling {transaction.quantity} on {transaction.date} but only "
                f"{quantity} held. A missing buy, or a split that was not adjusted for."
            )
        realised += (transaction.unit_price - average) * transaction.quantity
        quantity -= transaction.quantity

    closed = quantity == 0
    return Position(
        ticker=ticker,
        currency=currency,
        quantity=_tidy(quantity),
        average_price=None if closed else average.quantize(MONEY, rounding=ROUND_HALF_UP),
        invested=(quantity * average).quantize(MONEY, rounding=ROUND_HALF_UP),
        realised_gain=realised.quantize(MONEY, rounding=ROUND_HALF_UP),
    )
