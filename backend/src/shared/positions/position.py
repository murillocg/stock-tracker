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


def since_last_flat(transactions: Sequence[Transaction]) -> list[Transaction]:
    """Drop everything up to the last point the holding was flat or short.

    What you own today depends only on trades since the position last went to
    zero. BPAC11 closed twice — in 2020 and again in 2024 — and the 100 shares
    held now are a single purchase in August 2026, so nothing before it can move
    the average.

    "Or short" matters as much as "or zero": B3's export begins in November 2019,
    so a position opened earlier shows up as a sale of shares that were never
    bought. Treating that dip below zero as a reset is what lets the real trades
    stand on their own instead of being propped up by an invented opening
    balance at a price nobody knows.

    The history is kept in the ledger either way — this only decides where the
    fold starts.
    """
    ordered = sorted(transactions, key=lambda t: (t.date, t.sequence, t.id))
    running = Decimal(0)
    start = 0
    for index, transaction in enumerate(ordered):
        if transaction.type in (TransactionType.SELL, TransactionType.TRANSFER_OUT):
            running -= transaction.quantity
        else:
            running += transaction.quantity
        if running <= 0:
            running = Decimal(0)
            start = index + 1
    return ordered[start:]


def current_position(ticker: str, transactions: Sequence[Transaction]) -> Position | None:
    """Today's position, folding only what still bears on it.

    `build_position` stays strict — it refuses a ledger describing something
    impossible, which is how genuine gaps get noticed. This is the reading used
    for display, where a closed episode from six years ago is simply not part of
    the answer.
    """
    return build_position(ticker, since_last_flat(transactions))


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
    - a TRANSFER carries shares between custodians at their existing cost, so it
      moves quantity without touching the average or realising anything

    That second rule is the one that surprises people used to FIFO. Under FIFO a
    sale consumes specific lots and the remaining average shifts; here it cannot,
    which is why the average price of a long-held position is stable no matter
    how much you trade around it.

    Returns `None` for an empty ledger — no transactions is not a zero position,
    it is no position.
    """
    if not transactions:
        return None

    # (date, sequence) is the deterministic order; the id only breaks ties for
    # rows that carry no sequence at all.
    ordered = sorted(transactions, key=lambda t: (t.date, t.sequence, t.id))
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

        if transaction.type is TransactionType.TRANSFER_OUT:
            # Leaves at cost: no gain is realised, and the average of whatever
            # stays behind is unchanged.
            if transaction.quantity > quantity:
                raise LedgerError(
                    f"{ticker}: transferring {transaction.quantity} out on "
                    f"{transaction.date} but only {quantity} held."
                )
            quantity -= transaction.quantity
            continue

        if transaction.type is TransactionType.BONUS or (
            transaction.type is TransactionType.TRANSFER_IN and transaction.unit_price == 0
        ):
            # Free shares: the amount invested does not move, so dividing it over
            # a larger quantity lowers the average by itself. A 2:1 split is
            # exactly "as many free shares as you already hold".
            invested = quantity * average
            quantity += transaction.quantity
            average = invested / quantity
            continue

        if transaction.type in (TransactionType.BUY, TransactionType.TRANSFER_IN):
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
