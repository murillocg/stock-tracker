"""Shared test fixtures and fakes."""

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from shared.config import Config
from shared.models import (
    AlertRule,
    AlertType,
    Currency,
    DailySnapshot,
    ListType,
    LynchCategory,
    Market,
    ProviderName,
    Stock,
)


class FakeTable:
    """Stand-in for a boto3 DynamoDB Table resource.

    Records what it was called with and replays canned responses, which is enough
    to pin down the item shape and the query parameters we build.
    """

    def __init__(self) -> None:
        self.put_items: list[dict[str, Any]] = []
        self.get_item_calls: list[dict[str, Any]] = []
        self.query_calls: list[dict[str, Any]] = []
        self.get_item_response: dict[str, Any] = {}
        self.query_pages: list[dict[str, Any]] = []

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.put_items.append(kwargs["Item"])
        return {}

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        self.get_item_calls.append(kwargs)
        return self.get_item_response

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.query_calls.append(kwargs)
        if self.query_pages:
            return self.query_pages.pop(0)
        return {"Items": []}


@pytest.fixture
def fake_table() -> FakeTable:
    return FakeTable()


@pytest.fixture
def config() -> Config:
    return Config.from_env(
        {
            "STOCKS_TABLE": "Stocks",
            "SNAPSHOTS_TABLE": "DailySnapshots",
            "BRAPI_TOKEN": "test-token",
            "BOLSAI_API_KEY": "test-key",
            "ALPHA_VANTAGE_API_KEY": "test-av-key",
            "ALERT_SENDER": "alerts@example.com",
            "ALERT_RECIPIENT": "me@example.com",
        }
    )


@pytest.fixture
def snapshot() -> DailySnapshot:
    return DailySnapshot(
        ticker="PETR4",
        date=dt.date(2026, 8, 28),
        price=Decimal("38.50"),
        pe=Decimal("4.5"),
        net_debt_to_ebitda=Decimal("1.2"),
        reference_date=dt.date(2026, 6, 30),
        change_1m=Decimal("-3.25"),
    )


@pytest.fixture
def stock(snapshot: DailySnapshot) -> Stock:
    return Stock(
        ticker="PETR4",
        name="Petrobras PN",
        market=Market.B3,
        currency=Currency.BRL,
        quote_provider=ProviderName.BRAPI,
        fundamentals_provider=ProviderName.BOLSAI,
        sector="Oil & Gas",
        category=LynchCategory.CYCLICAL,
        list_type=ListType.PORTFOLIO,
        alert_rules={
            AlertType.PRICE_DROP: AlertRule(threshold=Decimal("20"), window_days=30),
        },
        current=snapshot,
    )
