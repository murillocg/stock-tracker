"""Folding a ledger into a position, including the rules that surprise people."""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from shared.models import Currency
from shared.models.transaction import Transaction, TransactionType
from shared.positions import (
    LedgerError,
    build_position,
    current_position,
    since_last_flat,
)


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


# --- splits and bonificações -------------------------------------------------


def bonus(day: int, quantity: str, ticker: str = "PETR4") -> Transaction:
    return Transaction(
        ticker=ticker,
        date=dt.date(2026, 3, day),
        type=TransactionType.BONUS,
        quantity=Decimal(quantity),
        unit_price=Decimal(0),
        currency=Currency.BRL,
    )


def test_a_two_for_one_split_halves_the_average_and_keeps_the_investment() -> None:
    """BBAS3 split 2:1 in 2024. A split is 'as many free shares as you hold'."""
    position = build_position("BBAS3", [trade(1, BUY, "200", "56.08"), bonus(5, "200", "BBAS3")])

    assert position is not None
    assert position.quantity == Decimal("400")
    assert position.average_price == Decimal("28.04")
    assert position.invested == Decimal("11216.00")  # unchanged by the split


def test_a_bonificacao_lowers_the_average_in_proportion() -> None:
    """ITSA4: 1,092 shares plus 8 free ones."""
    position = build_position("ITSA4", [trade(1, BUY, "1092", "12.33"), bonus(5, "8", "ITSA4")])

    assert position is not None
    assert position.quantity == Decimal("1100")
    assert position.average_price == Decimal("12.24")


def test_free_shares_do_not_change_what_you_paid() -> None:
    before = build_position("PETR4", [trade(1, BUY, "100", "40.00")])
    after = build_position("PETR4", [trade(1, BUY, "100", "40.00"), bonus(5, "900")])

    assert before is not None and after is not None
    assert before.invested == after.invested


def test_a_trade_at_no_price_is_rejected() -> None:
    """Only a BONUS may be free; a BUY or SELL at zero is a data error."""
    with pytest.raises(ValidationError):
        Transaction(
            ticker="PETR4",
            date=dt.date(2026, 3, 1),
            type=TransactionType.BUY,
            quantity=Decimal("100"),
            unit_price=Decimal(0),
            currency=Currency.BRL,
        )


# --- determinism -------------------------------------------------------------


def test_same_day_trades_fold_in_source_order_not_at_random() -> None:
    """VALE3 has a buy and a sell on 2024-08-27, and their order changes the
    average. Sorting by a random id gave 68.06 on some runs and 68.29 on others
    from identical input — invisible until two runs were compared."""
    buy = trade(1, BUY, "100", "60.00").model_copy(update={"sequence": 1, "id": "aaa"})
    sell = trade(1, SELL, "100", "60.02").model_copy(update={"sequence": 2, "id": "zzz"})
    opening = trade(1, BUY, "600", "70.00").model_copy(update={"sequence": 0, "id": "mmm"})

    forwards = build_position("VALE3", [opening, buy, sell])
    backwards = build_position("VALE3", [sell, buy, opening])

    assert forwards == backwards


def test_sequence_beats_the_id_when_both_disagree() -> None:
    """The id is only a tie-break for rows carrying no sequence at all."""
    first = trade(1, BUY, "100", "10.00").model_copy(update={"sequence": 0, "id": "zzz"})
    second = trade(1, BUY, "100", "30.00").model_copy(update={"sequence": 1, "id": "aaa"})

    position = build_position("PETR4", [second, first])

    assert position is not None
    assert position.average_price == Decimal("20.00")


# --- current position vs the whole ledger ------------------------------------


def test_a_closed_and_reopened_position_forgets_the_old_average() -> None:
    """BPAC11 closed in 2020 and again in 2024; today's 100 shares are one
    purchase in 2026, so nothing before it can move the average."""
    ledger = [
        trade(1, BUY, "100", "25.64"),
        trade(2, SELL, "100", "81.20"),  # flat
        trade(3, BUY, "100", "50.04"),
    ]

    assert current_position("BPAC11", ledger).average_price == Decimal("50.04")
    assert build_position("BPAC11", ledger).average_price == Decimal("50.04")


def test_a_short_excursion_also_resets() -> None:
    """B3's export starts in 2019, so a position opened earlier shows up as a
    sale of shares never bought. Treating that as a reset is what removes the
    need for an opening balance at a price nobody knows."""
    ledger = [
        trade(1, BUY, "100", "22.28"),
        trade(2, SELL, "170", "22.21"),  # short by 70 — bought before the data
        trade(3, BUY, "100", "32.25"),
        trade(4, BUY, "100", "34.15"),
    ]

    position = current_position("BBSE3", ledger)

    assert position is not None
    assert position.quantity == Decimal("200")
    assert position.average_price == Decimal("33.20")


def test_the_strict_fold_still_refuses_an_impossible_ledger() -> None:
    """`build_position` stays strict — that is how genuine gaps get noticed."""
    ledger = [trade(1, BUY, "100", "22.28"), trade(2, SELL, "170", "22.21")]

    with pytest.raises(LedgerError):
        build_position("BBSE3", ledger)


def test_trimming_keeps_the_ledger_intact() -> None:
    """Only the fold starts later; nothing is deleted."""
    ledger = [trade(1, BUY, "100", "10"), trade(2, SELL, "100", "20"), trade(3, BUY, "50", "30")]

    assert len(since_last_flat(ledger)) == 1
    assert len(ledger) == 3
