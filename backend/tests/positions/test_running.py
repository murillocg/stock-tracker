"""The fold made visible: every transaction with the position after it."""

import datetime as dt
from decimal import Decimal

from shared.models import Currency, Transaction, TransactionType
from shared.positions import current_position, running


def trade(
    day: int,
    type_: TransactionType,
    quantity: str,
    price: str,
    sequence: int = 0,
) -> Transaction:
    return Transaction(
        ticker="VALE3",
        date=dt.date(2026, 1, day),
        type=type_,
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        currency=Currency.BRL,
        sequence=sequence,
        id=f"t{day}-{sequence}",
    )


def test_the_average_moves_only_on_a_buy() -> None:
    """The Brazilian rule, seen row by row: buying at 80 pulls the average up,
    selling at any price leaves it exactly where it was."""
    entries = running(
        "VALE3",
        [
            trade(1, TransactionType.BUY, "100", "60.00"),
            trade(2, TransactionType.BUY, "100", "80.00"),
            trade(3, TransactionType.SELL, "50", "90.00"),
        ],
    )

    averages = [e.position.average_price for e in entries if e.position]
    assert averages == [Decimal("60.00"), Decimal("70.00"), Decimal("70.00")]

    last = entries[-1].position
    assert last is not None
    assert last.quantity == Decimal("150")
    assert last.realised_gain == Decimal("1000.00")  # (90 - 70) x 50


def test_a_bonus_lowers_the_average_without_costing_anything() -> None:
    entries = running(
        "VALE3",
        [
            trade(1, TransactionType.BUY, "100", "60.00"),
            trade(2, TransactionType.BONUS, "100", "0"),
        ],
    )

    after = entries[-1].position
    assert after is not None
    assert after.quantity == Decimal("200")
    assert after.average_price == Decimal("30.00")
    assert after.invested == Decimal("6000.00")


def test_rows_before_the_last_flat_point_carry_no_position() -> None:
    """They are real trades and belong on screen, but a running total across a
    reset would imply a continuity that is not there."""
    entries = running(
        "VALE3",
        [
            trade(1, TransactionType.BUY, "100", "10.00"),
            trade(2, TransactionType.SELL, "100", "20.00"),  # flat here
            trade(3, TransactionType.BUY, "50", "40.00"),
        ],
    )

    assert [e.position is None for e in entries] == [True, True, False]

    after = entries[-1].position
    assert after is not None
    # The 10.00 purchase is behind the reset, so it cannot drag the average down.
    assert after.average_price == Decimal("40.00")


def test_it_ends_where_current_position_ends() -> None:
    """The guarantee that makes the table trustworthy: the last row of the ledger
    is the number shown at the top of the page."""
    transactions = [
        trade(1, TransactionType.BUY, "100", "60.00"),
        trade(2, TransactionType.BUY, "200", "75.00"),
        trade(2, TransactionType.SELL, "50", "80.00", sequence=1),
        trade(9, TransactionType.BONUS, "10", "0"),
    ]

    entries = running("VALE3", transactions)
    assert entries[-1].position == current_position("VALE3", transactions)


def test_an_empty_ledger_has_no_rows() -> None:
    assert running("VALE3", []) == []


def test_it_is_ordered_oldest_first_regardless_of_input_order() -> None:
    entries = running(
        "VALE3",
        [
            trade(9, TransactionType.BUY, "10", "90.00"),
            trade(1, TransactionType.BUY, "10", "10.00"),
        ],
    )

    assert [e.transaction.date.day for e in entries] == [1, 9]
