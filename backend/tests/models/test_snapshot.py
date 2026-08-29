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


def test_the_reference_date_is_stored_as_a_date_not_a_quarter_label() -> None:
    """The statement date is the fact; `2026Q2` is presentation, derived later.

    A calendar-quarter label would be wrong for US tickers whose fiscal year does
    not match the calendar, and the mistake would be unrecoverable once written.
    """
    snapshot = DailySnapshot(
        ticker="PETR4",
        date=dt.date(2026, 8, 28),
        price=Decimal(1),
        reference_date=dt.date(2026, 6, 30),
    )

    item = snapshot.model_dump(by_alias=True, exclude_none=True)

    assert snapshot.reference_date == dt.date(2026, 6, 30)
    assert item["referenceDate"] == "2026-06-30"


def test_the_reference_date_is_optional() -> None:
    """Price collection runs daily; fundamentals only land when earnings do."""
    snapshot = DailySnapshot(ticker="PETR4", date=dt.date(2026, 8, 28), price=Decimal(1))

    assert snapshot.reference_date is None
    assert "referenceDate" not in snapshot.model_dump(by_alias=True, exclude_none=True)


@pytest.mark.parametrize("bad_date", ["2026-13-01", "not-a-date", "2026-06-31"])
def test_a_malformed_reference_date_is_rejected(bad_date: str) -> None:
    with pytest.raises(ValidationError):
        DailySnapshot(
            ticker="PETR4",
            date=dt.date(2026, 8, 28),
            price=Decimal(1),
            reference_date=bad_date,  # type: ignore[arg-type]
        )


def test_a_non_positive_price_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DailySnapshot(ticker="PETR4", date=dt.date(2026, 8, 28), price=Decimal(0))


def test_snapshots_are_immutable(snapshot: DailySnapshot) -> None:
    with pytest.raises(ValidationError):
        snapshot.price = Decimal("99")  # type: ignore[misc]
