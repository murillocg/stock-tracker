"""The snake_case <-> camelCase bridge, and the value semantics of a snapshot."""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from shared.models import DailySnapshot


def test_dump_uses_camel_case_aliases(snapshot: DailySnapshot) -> None:
    item = snapshot.model_dump(by_alias=True, exclude_none=True)

    assert item["netDebtToEbitda"] == Decimal("1.2")
    assert "net_debt_to_ebitda" not in item


def test_change_fields_keep_a_lowercase_suffix(snapshot: DailySnapshot) -> None:
    """`to_camel` would produce `change1M`; the explicit alias must win."""
    item = snapshot.model_dump(by_alias=True, exclude_none=True)

    assert "change1m" in item
    assert "change1M" not in item


def test_accepts_both_the_alias_and_the_python_name() -> None:
    """Reading back from DynamoDB uses aliases; tests use the Python names."""
    from_db = DailySnapshot.model_validate(
        {"ticker": "PETR4", "date": "2026-08-28", "price": "38.5", "evEbitda": "3.1"}
    )

    assert from_db.ev_ebitda == Decimal("3.1")
    assert from_db.date == dt.date(2026, 8, 28)


def test_date_is_serialised_as_an_iso_string(snapshot: DailySnapshot) -> None:
    """DynamoDB has no date type, and ISO 8601 sorts chronologically as a string."""
    item = snapshot.model_dump(by_alias=True, exclude_none=True)

    assert item["date"] == "2026-08-28"


def test_absent_indicators_are_dropped_entirely(snapshot: DailySnapshot) -> None:
    item = snapshot.model_dump(by_alias=True, exclude_none=True)

    assert "roic" not in item
    assert "change1y" not in item


def test_prices_stay_decimal_not_float(snapshot: DailySnapshot) -> None:
    """boto3 rejects float outright, so the dump must hand it Decimal."""
    item = snapshot.model_dump(by_alias=True, exclude_none=True)

    assert isinstance(item["price"], Decimal)


def test_ticker_is_normalised_to_upper_case() -> None:
    parsed = DailySnapshot(ticker=" petr4 ", date=dt.date(2026, 8, 28), price=Decimal(1))

    assert parsed.ticker == "PETR4"


def test_round_trip_through_the_item_shape(snapshot: DailySnapshot) -> None:
    item = snapshot.model_dump(by_alias=True, exclude_none=True)

    assert DailySnapshot.model_validate(item) == snapshot


@pytest.mark.parametrize("quarter", ["2026Q5", "26Q2", "2026-Q2", "Q2"])
def test_malformed_quarters_are_rejected(quarter: str) -> None:
    with pytest.raises(ValidationError):
        DailySnapshot(
            ticker="PETR4",
            date=dt.date(2026, 8, 28),
            price=Decimal(1),
            quarter=quarter,
        )


def test_a_non_positive_price_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DailySnapshot(ticker="PETR4", date=dt.date(2026, 8, 28), price=Decimal(0))


def test_snapshots_are_immutable(snapshot: DailySnapshot) -> None:
    with pytest.raises(ValidationError):
        snapshot.price = Decimal("99")  # type: ignore[misc]
