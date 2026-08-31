"""The fold made visible: every transaction with the position after it."""

import datetime as dt
from decimal import Decimal

from shared.models import Currency, Transaction, TransactionType
from shared.positions import (
    combined_position,
    current_position,
    running,
    running_by_broker,
)


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


# --- per custodian, which is how the tax return asks for it ------------------


def at(broker: str, day: int, type_: TransactionType, quantity: str, price: str) -> Transaction:
    return Transaction(
        ticker="PRIO3",
        date=dt.date(2026, 1, day),
        type=type_,
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        currency=Currency.BRL,
        broker=broker,
        id=f"{broker}-{day}",
    )


def test_each_broker_keeps_its_own_average() -> None:
    """The same security at two custodians is two declarations, each with its own
    cost — not one blended position."""
    ledgers = running_by_broker(
        "PRIO3",
        [
            at("BTG PACTUAL", 1, TransactionType.BUY, "100", "40.00"),
            at("NU INVEST", 2, TransactionType.BUY, "100", "60.00"),
        ],
    )

    assert [ledger.broker for ledger in ledgers] == ["BTG PACTUAL", "NU INVEST"]
    averages = [ledger.position.average_price for ledger in ledgers if ledger.position]
    assert averages == [Decimal("40.00"), Decimal("60.00")]


def test_a_transfer_carries_the_cost_to_the_receiving_broker() -> None:
    """The reason TRANSFER_IN and TRANSFER_OUT exist. Folding the ledger as one
    series would net these two rows out and lose the split entirely."""
    ledgers = running_by_broker(
        "PRIO3",
        [
            at("INTER", 1, TransactionType.BUY, "100", "27.01"),
            at("INTER", 2, TransactionType.TRANSFER_OUT, "100", "0"),
            at("BTG PACTUAL", 2, TransactionType.TRANSFER_IN, "100", "27.01"),
        ],
    )

    by_broker = {ledger.broker: ledger for ledger in ledgers}
    # Inter holds none of it any more, and must not still appear to.
    assert by_broker["INTER"].position is None
    btg = by_broker["BTG PACTUAL"].position
    assert btg is not None
    assert btg.quantity == Decimal("100")
    assert btg.average_price == Decimal("27.01")


def test_the_brokers_sum_to_the_combined_position() -> None:
    """Both readings come off the same rows: per broker for the declaration,
    totalled for the portfolio weight."""
    transactions = [
        at("BTG PACTUAL", 1, TransactionType.BUY, "100", "40.00"),
        at("NU INVEST", 2, TransactionType.BUY, "300", "60.00"),
    ]

    ledgers = running_by_broker("PRIO3", transactions)
    combined = current_position("PRIO3", transactions)

    assert combined is not None
    held = sum((ledger.position.quantity for ledger in ledgers if ledger.position), Decimal(0))
    assert held == combined.quantity == Decimal("400")
    # The blended average is the weighted mean of the two, not either of them.
    assert combined.average_price == Decimal("55.00")


def test_rows_with_no_broker_sort_last() -> None:
    ledgers = running_by_broker(
        "PRIO3",
        [
            Transaction(
                ticker="PRIO3",
                date=dt.date(2026, 1, 1),
                type=TransactionType.BUY,
                quantity=Decimal("10"),
                unit_price=Decimal("10"),
                currency=Currency.BRL,
                id="none-1",
            ),
            at("NU INVEST", 2, TransactionType.BUY, "10", "10.00"),
        ],
    )

    assert [ledger.broker for ledger in ledgers] == ["NU INVEST", None]


def test_the_combined_position_sums_the_accounts_rather_than_pooling_them() -> None:
    """Pooling every broker's buys into one average and then letting sales leave
    it untouched yields a number belonging to no real account.

    Here: 100 bought at 40 in one account and 100 at 60 in another, then 100 sold
    from the cheap one. What remains is 100 at 40 plus nothing at 60 — an average
    of 40. The pooled fold would average the buys to 50 and leave it there.
    """
    transactions = [
        at("BTG PACTUAL", 1, TransactionType.BUY, "100", "40.00"),
        at("NU INVEST", 2, TransactionType.BUY, "100", "60.00"),
        at("NU INVEST", 3, TransactionType.SELL, "100", "70.00"),
    ]

    combined = combined_position("PRIO3", transactions)
    pooled = current_position("PRIO3", transactions)

    assert combined is not None and pooled is not None
    assert combined.quantity == pooled.quantity == Decimal("100")
    assert combined.average_price == Decimal("40.00")
    assert pooled.average_price == Decimal("50.00")  # the fiction


def test_quantity_is_unaffected_so_portfolio_weights_do_not_move() -> None:
    """Quantity is linear, so both readings agree on it. Only the cost basis —
    and the unrealised gain derived from it — was wrong."""
    transactions = [
        at("BTG PACTUAL", 1, TransactionType.BUY, "300", "24.09"),
        at("NU INVEST", 2, TransactionType.BUY, "400", "25.66"),
        at("BTG PACTUAL", 3, TransactionType.SELL, "100", "32.22"),
    ]

    combined = combined_position("PRIO3", transactions)
    pooled = current_position("PRIO3", transactions)

    assert combined is not None and pooled is not None
    assert combined.quantity == pooled.quantity == Decimal("600")


def test_it_is_none_when_every_account_is_closed() -> None:
    assert (
        combined_position(
            "PRIO3",
            [
                at("NU INVEST", 1, TransactionType.BUY, "100", "10.00"),
                at("NU INVEST", 2, TransactionType.SELL, "100", "20.00"),
            ],
        )
        is None
    )
