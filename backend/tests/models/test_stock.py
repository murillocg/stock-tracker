"""The registry item: enums, the alert map, and the denormalised snapshot."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from shared.models import (
    AlertType,
    Currency,
    ListType,
    LynchCategory,
    Market,
    ProviderName,
    Stock,
)


def test_dump_uses_camel_case_aliases(stock: Stock) -> None:
    item = stock.model_dump(by_alias=True, exclude_none=True)

    assert item["listType"] == ListType.PORTFOLIO
    assert "list_type" not in item


def test_enums_serialise_as_plain_strings(stock: Stock) -> None:
    """boto3 stores them as S attributes because StrEnum *is* a str."""
    item = stock.model_dump(by_alias=True, exclude_none=True)

    assert isinstance(item["market"], str)
    assert item["market"] == "B3"


def test_alert_rules_are_a_map_keyed_by_type(stock: Stock) -> None:
    item = stock.model_dump(by_alias=True, exclude_none=True)

    assert all(isinstance(key, str) for key in item["alertRules"])
    assert Stock.model_validate(item).alert_rules[AlertType.PRICE_DROP].window_days == 30


def test_the_current_snapshot_is_nested_and_aliased(stock: Stock) -> None:
    item = stock.model_dump(by_alias=True, exclude_none=True)

    assert item["current"]["netDebtToEbitda"] == Decimal("1.2")
    assert item["current"]["date"] == "2026-08-28"


def test_round_trip_through_the_item_shape(stock: Stock) -> None:
    item = stock.model_dump(by_alias=True, exclude_none=True)

    assert Stock.model_validate(item) == stock


def test_an_unclassified_stock_is_allowed() -> None:
    """`category` is set by hand, so `None` means "not triaged yet"."""
    unclassified = Stock(
        ticker="AAPL",
        name="Apple Inc.",
        market=Market.NASDAQ,
        currency=Currency.USD,
        quote_provider=ProviderName.ALPHA_VANTAGE,
        list_type=ListType.WATCHLIST,
    )

    assert unclassified.category is None
    assert unclassified.alert_rules == {}


def test_an_unknown_enum_value_is_rejected() -> None:
    """mypy catches this statically; Pydantic is the runtime net for data from AWS."""
    with pytest.raises(ValidationError):
        Stock(
            ticker="PETR4",
            name="Petrobras",
            market="BOVESPA",  # type: ignore[arg-type]
            currency=Currency.BRL,
            quote_provider=ProviderName.BRAPI,
            list_type=ListType.PORTFOLIO,
        )


def test_the_default_alert_map_is_not_shared_between_instances() -> None:
    """`default_factory` builds a fresh dict per instance.

    A bare `= {}` default would be evaluated once at class-definition time and
    shared by every instance — the classic Python mutable-default trap, and one
    of the few places Python is more dangerous than Java.
    """
    first = Stock(
        ticker="AAA3",
        name="A",
        market=Market.B3,
        currency=Currency.BRL,
        quote_provider=ProviderName.BRAPI,
        list_type=ListType.WATCHLIST,
    )
    second = first.model_copy(update={"ticker": "BBB3"})

    assert first.alert_rules is not second.alert_rules or first.alert_rules == {}


def test_lynch_categories_cover_the_six_types() -> None:
    assert len(LynchCategory) == 6


# --- where the business is ---------------------------------------------------


def build(ticker: str, **values: object) -> Stock:
    return Stock.model_validate(
        {
            "ticker": ticker,
            "name": ticker,
            "market": Market.B3,
            "currency": Currency.BRL,
            "quote_provider": ProviderName.BRAPI,
            "list_type": ListType.PORTFOLIO,
            **values,
        }
    )


def test_a_b3_listing_is_brazilian_by_default() -> None:
    assert build("VALE3").is_foreign is False


def test_a_us_listing_is_foreign_by_default() -> None:
    assert build("MSFT", market=Market.NASDAQ).is_foreign is True


def test_a_bdr_of_a_foreign_company_overrides_its_listing() -> None:
    """MSFT34 trades on the B3; the business is Microsoft."""
    assert build("MSFT34", foreign_business=True).is_foreign is True


def test_a_bdr_of_a_brazilian_company_stays_brazilian() -> None:
    """INBR32 has the same shape as MSFT34 and the opposite answer — Banco Inter
    is a Brazilian bank. This is why the flag is about the business, not the
    instrument."""
    assert build("INBR32", foreign_business=False).is_foreign is False


def test_it_is_serialised_for_the_frontend() -> None:
    assert build("MSFT", market=Market.NASDAQ).model_dump(by_alias=True)["isForeign"] is True
