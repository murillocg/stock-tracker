"""Fold a transaction ledger into a position. Pure: data in, data out."""

from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _State:
    """The running total mid-fold, before it is rounded for display."""

    quantity: Decimal = Decimal(0)
    average: Decimal = Decimal(0)
    realised: Decimal = Decimal(0)


def _apply(ticker: str, currency: Currency, state: _State, t: Transaction) -> _State:
    """Advance the fold by one transaction. The rules live here and only here.

    Extracted so `build_position` and `running` cannot drift: the second would
    otherwise be a copy of the averaging rules, and a copy of the Brazilian
    average is exactly the kind of thing that stays subtly wrong for months.
    """
    if t.currency is not currency:
        raise LedgerError(
            f"{ticker} has trades in both {currency} and {t.currency}; "
            "a single position cannot span two currencies."
        )

    if t.type is TransactionType.TRANSFER_OUT:
        # Leaves at cost: no gain is realised, and the average of whatever stays
        # behind is unchanged.
        if t.quantity > state.quantity:
            raise LedgerError(
                f"{ticker}: transferring {t.quantity} out on "
                f"{t.date} but only {state.quantity} held."
            )
        return _State(state.quantity - t.quantity, state.average, state.realised)

    if t.type is TransactionType.BONUS or (
        t.type is TransactionType.TRANSFER_IN and t.unit_price == 0
    ):
        # Free shares: the amount invested does not move, so dividing it over a
        # larger quantity lowers the average by itself. A 2:1 split is exactly
        # "as many free shares as you already hold".
        invested = state.quantity * state.average
        quantity = state.quantity + t.quantity
        return _State(quantity, invested / quantity, state.realised)

    if t.type in (TransactionType.BUY, TransactionType.TRANSFER_IN):
        cost = state.quantity * state.average + t.quantity * t.unit_price
        quantity = state.quantity + t.quantity
        return _State(quantity, cost / quantity, state.realised)

    if t.quantity > state.quantity:
        raise LedgerError(
            f"{ticker}: selling {t.quantity} on {t.date} but only {state.quantity} held. "
            "A missing buy, or a split that was not adjusted for."
        )
    return _State(
        state.quantity - t.quantity,
        state.average,
        state.realised + (t.unit_price - state.average) * t.quantity,
    )


def _to_position(ticker: str, currency: Currency, state: _State) -> Position:
    closed = state.quantity == 0
    return Position(
        ticker=ticker,
        currency=currency,
        quantity=_tidy(state.quantity),
        average_price=None if closed else state.average.quantize(MONEY, rounding=ROUND_HALF_UP),
        invested=(state.quantity * state.average).quantize(MONEY, rounding=ROUND_HALF_UP),
        realised_gain=state.realised.quantize(MONEY, rounding=ROUND_HALF_UP),
    )


class LedgerEntry(CamelModel):
    """One transaction and the position it produced.

    `position` is `None` for rows before the last flat point: they are real
    trades and belong on screen, but they do not bear on today's average, and
    showing a running total across a reset would imply a continuity that is not
    there.
    """

    transaction: Transaction
    position: Position | None


def running(ticker: str, transactions: Sequence[Transaction]) -> list[LedgerEntry]:
    """Every transaction, oldest first, each with the position after it.

    This is the fold made visible — the answer to "how did the average get to
    68.06?", which a single number cannot give you.
    """
    ordered = sorted(transactions, key=lambda t: (t.date, t.sequence, t.id))
    if not ordered:
        return []

    # `since_last_flat` returns a suffix, so its length locates the reset.
    start = len(ordered) - len(since_last_flat(ordered))
    currency = ordered[start].currency if start < len(ordered) else ordered[0].currency

    entries = [LedgerEntry(transaction=t, position=None) for t in ordered[:start]]
    state = _State()
    for transaction in ordered[start:]:
        state = _apply(ticker, currency, state, transaction)
        entries.append(
            LedgerEntry(transaction=transaction, position=_to_position(ticker, currency, state))
        )
    return entries


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

    state = _State()
    for transaction in ordered:
        state = _apply(ticker, currency, state, transaction)

    return _to_position(ticker, currency, state)


class BrokerLedger(CamelModel):
    """One custodian's rows for a ticker, folded on their own.

    The unit the Brazilian tax return actually asks for: each institution is a
    separate entry in Bens e Direitos, with its own quantity and average cost.
    A single blended average across brokers is the right number for a portfolio
    weight and the wrong number for the declaration.
    """

    broker: str | None
    entries: list[LedgerEntry]
    position: Position | None
    """This broker's holding today. `None` once they hold none of it — the
    account is kept on screen because a closed position still had a year in which
    it was declared."""


def running_by_broker(ticker: str, transactions: Sequence[Transaction]) -> list[BrokerLedger]:
    """Fold each custodian's rows separately, oldest first.

    Transfers make this work rather than break it: a TRANSFER_OUT leaves one
    broker at cost and the matching TRANSFER_IN arrives at the other carrying
    that same cost, so both averages stay true. Folding the ledger as one series
    would net them out and lose exactly the split the tax return needs.

    `since_last_flat` applies per broker, since an account can close and reopen
    independently of the others.
    """
    grouped: dict[str | None, list[Transaction]] = {}
    for transaction in transactions:
        grouped.setdefault(transaction.broker, []).append(transaction)

    ledgers = []
    # Named brokers alphabetically, then the unattributed rows last.
    for broker in sorted(grouped, key=lambda b: (b is None, b or "")):
        entries = running(ticker, grouped[broker])
        ledgers.append(
            BrokerLedger(
                broker=broker,
                entries=entries,
                position=entries[-1].position if entries else None,
            )
        )
    return ledgers
