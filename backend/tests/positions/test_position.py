"""Folding a ledger into a position, including the rules that surprise people."""

import datetime as dt
from decimal import Decimal

import pytest

from shared.models import Currency
from shared.models.transaction import Transaction, TransactionType
from shared.positions import LedgerError, build_position


def trade(
    day: int,
    kind: TransactionType,
    quantity: str,
    price: str,
    ticker: str = "PETR4",
    currency: Currency = Currency.BRL,
) -> Transaction:
    return Transaction(
        ticker=ticker,
        date=dt.date(2026, 3, day),
        type=kind,
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        currency=currency,
    )


BUY = TransactionType.BUY
SELL = TransactionType.SELL


def test_an_empty_ledger_is_no_position_rather_than_a_zero_one() -> None:
    assert build_position("PETR4", []) is None


def test_one_buy_sets_the_average_to_the_price_paid() -> None:
    position = build_position("PETR4", [trade(1, BUY, "100", "38.20")])

    assert position is not None
    assert position.quantity == Decimal("100")
    assert position.average_price == Decimal("38.20")
    assert position.invested == Decimal("3820.00")


def test_a_second_buy_moves_the_average_in_proportion_to_size() -> None:
    """100 at 38.20 then 300 at 42.00 -> 41.05, not the midpoint of 40.10."""
    position = build_position(
        "PETR4", [trade(1, BUY, "100", "38.20"), trade(5, BUY, "300", "42.00")]
    )

    assert position is not None
    assert position.quantity == Decimal("400")
    assert position.average_price == Decimal("41.05")


def test_a_sale_leaves_the_average_untouched() -> None:
    """The rule that surprises anyone expecting FIFO.

    Under FIFO a sale consumes specific lots and shifts what remains. Under the
    Brazilian weighted-average convention it cannot — which is why a long-held
    average is stable no matter how much you trade around it.
    """
    position = build_position(
        "PETR4",
        [
            trade(1, BUY, "100", "38.20"),
            trade(5, BUY, "300", "42.00"),
            trade(9, SELL, "200", "50.00"),
        ],
    )

    assert position is not None
    assert position.quantity == Decimal("200")
    assert position.average_price == Decimal("41.05")


def test_a_sale_books_the_gain_against_the_average() -> None:
    position = build_position(
        "PETR4", [trade(1, BUY, "100", "40.00"), trade(5, SELL, "40", "55.00")]
    )

    assert position is not None
    assert position.realised_gain == Decimal("600.00")  # (55 - 40) * 40


def test_a_loss_is_booked_as_a_negative_gain() -> None:
    position = build_position(
        "PETR4", [trade(1, BUY, "100", "40.00"), trade(5, SELL, "40", "31.00")]
    )

    assert position is not None
    assert position.realised_gain == Decimal("-360.00")


def test_a_closed_position_has_no_average_price() -> None:
    """None, not zero — zero would read as "bought at nothing" in any ratio."""
    position = build_position(
        "PETR4", [trade(1, BUY, "100", "40.00"), trade(5, SELL, "100", "45.00")]
    )

    assert position is not None
    assert position.quantity == Decimal("0")
    assert position.average_price is None
    assert position.invested == Decimal("0.00")
    assert position.realised_gain == Decimal("500.00")


def test_trades_are_folded_oldest_first_whatever_order_they_arrive_in() -> None:
    """DynamoDB returns sorted, but nothing in the signature promises that."""
    scrambled = [trade(9, SELL, "50", "50.00"), trade(1, BUY, "100", "38.20")]

    position = build_position("PETR4", scrambled)

    assert position is not None
    assert position.quantity == Decimal("50")
    assert position.average_price == Decimal("38.20")


def test_selling_more_than_is_held_is_rejected() -> None:
    """Usually a missing buy, or a split nobody adjusted the quantities for."""
    with pytest.raises(LedgerError, match="only"):
        build_position("PETR4", [trade(1, BUY, "100", "38.20"), trade(5, SELL, "150", "40.00")])


def test_a_ledger_cannot_span_two_currencies() -> None:
    with pytest.raises(LedgerError, match="two currencies"):
        build_position(
            "PETR4",
            [trade(1, BUY, "100", "38.20"), trade(5, BUY, "10", "500", currency=Currency.USD)],
        )


def test_fractional_quantities_survive() -> None:
    """US brokers issue fractional shares; an int quantity would truncate them."""
    position = build_position(
        "MSFT", [trade(1, BUY, "1.5", "500.00", ticker="MSFT", currency=Currency.USD)]
    )

    assert position is not None
    assert position.quantity == Decimal("1.5")
    assert position.invested == Decimal("750.00")


def test_the_average_is_money_rounded_not_left_at_full_precision() -> None:
    """100 at 10 plus 3 at 10 divides to 10.0 exactly; 1 at 10 plus 3 at 20 does not."""
    position = build_position("PETR4", [trade(1, BUY, "1", "10.00"), trade(2, BUY, "3", "20.00")])

    assert position is not None
    assert position.average_price == Decimal("17.50")


def test_same_day_trades_are_both_counted() -> None:
    """The sort key pairs date with an id precisely so these do not collide."""
    position = build_position(
        "PETR4", [trade(1, BUY, "100", "38.00"), trade(1, BUY, "100", "40.00")]
    )

    assert position is not None
    assert position.quantity == Decimal("200")
    assert position.average_price == Decimal("39.00")


def test_a_whole_quantity_is_not_rendered_in_scientific_notation() -> None:
    """Decimal("400.00000000").normalize() is Decimal("4E+2") — same number,
    useless in front of a person. Found by running a real B3 export through it."""
    position = build_position("PETR4", [trade(1, BUY, "400", "25.51")])

    assert position is not None
    assert str(position.quantity) == "400"


def test_a_fractional_quantity_keeps_its_digits() -> None:
    position = build_position("MSFT", [trade(1, BUY, "1.25", "500", ticker="MSFT")])

    assert position is not None
    assert str(position.quantity) == "1.25"


def test_the_same_ticker_at_two_brokers_is_one_position() -> None:
    """PRIO3 is held at BTG and Nu Invest. Brazilian IRPF averages cost per
    security across custodians, so splitting it would produce two averages that
    the tax treatment does not recognise."""
    btg = trade(1, BUY, "300", "24.00")
    nu = trade(5, BUY, "300", "26.00")
    position = build_position(
        "PRIO3",
        [btg.model_copy(update={"broker": "BTG"}), nu.model_copy(update={"broker": "NU INVEST"})],
    )

    assert position is not None
    assert position.quantity == Decimal("600")
    assert position.average_price == Decimal("25.00")
