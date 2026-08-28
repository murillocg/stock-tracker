"""The DynamoDB item shape and the query parameters we build.

No AWS and no moto: a `FakeTable` records the calls. What is worth pinning down
here is our translation layer, not Amazon's implementation of DynamoDB.
"""

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from shared.models import DailySnapshot, ListType, Stock
from shared.repository import (
    LIST_TYPE_INDEX,
    DynamoDbSnapshotRepository,
    DynamoDbStockRepository,
    SnapshotRepository,
    StockRepository,
)
from tests.conftest import FakeTable

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


def as_table(fake: FakeTable) -> "Table":
    """`cast` is a compile-time-only assertion: it emits no runtime check.

    The fake implements the three methods we actually use, which is all duck
    typing requires; `cast` is only there to tell mypy so.
    """
    return cast("Table", fake)


def test_the_repositories_satisfy_the_protocols(fake_table: FakeTable) -> None:
    stocks: StockRepository = DynamoDbStockRepository(as_table(fake_table))
    snapshots: SnapshotRepository = DynamoDbSnapshotRepository(as_table(fake_table))

    assert stocks.get("PETR4") is None
    assert snapshots.get("PETR4", dt.date(2026, 8, 28)) is None


def test_saving_a_stock_writes_a_camel_case_item(fake_table: FakeTable, stock: Stock) -> None:
    DynamoDbStockRepository(as_table(fake_table)).save(stock)

    item = fake_table.put_items[0]

    assert item["ticker"] == "PETR4"
    assert item["listType"] == "PORTFOLIO"
    assert item["current"]["netDebtToEbitda"] == Decimal("1.2")


def test_numbers_reach_boto3_as_decimal_never_float(
    fake_table: FakeTable, snapshot: DailySnapshot
) -> None:
    """boto3 raises `TypeError: Float types are not supported` on a float."""
    DynamoDbSnapshotRepository(as_table(fake_table)).save(snapshot)

    item = fake_table.put_items[0]

    assert isinstance(item["price"], Decimal)
    assert isinstance(item["change1m"], Decimal)


def test_the_sort_key_is_written_as_an_iso_string(
    fake_table: FakeTable, snapshot: DailySnapshot
) -> None:
    DynamoDbSnapshotRepository(as_table(fake_table)).save(snapshot)

    assert fake_table.put_items[0]["date"] == "2026-08-28"


def test_a_missing_item_returns_none(fake_table: FakeTable) -> None:
    """DynamoDB omits `Item` entirely on a miss, rather than returning a null."""
    assert DynamoDbStockRepository(as_table(fake_table)).get("NOPE3") is None


def test_get_normalises_the_key(fake_table: FakeTable) -> None:
    DynamoDbStockRepository(as_table(fake_table)).get(" petr4 ")

    assert fake_table.get_item_calls[0]["Key"] == {"ticker": "PETR4"}


def test_get_parses_the_item_back_into_a_model(fake_table: FakeTable, stock: Stock) -> None:
    fake_table.get_item_response = {"Item": stock.model_dump(by_alias=True, exclude_none=True)}

    assert DynamoDbStockRepository(as_table(fake_table)).get("PETR4") == stock


def test_list_by_type_queries_the_gsi(fake_table: FakeTable) -> None:
    DynamoDbStockRepository(as_table(fake_table)).list_by_type(ListType.PORTFOLIO)

    assert fake_table.query_calls[0]["IndexName"] == LIST_TYPE_INDEX


def test_list_by_type_follows_the_pagination_cursor(fake_table: FakeTable, stock: Stock) -> None:
    """A 1 MB page limit silently truncating the portfolio would be a nasty bug."""
    item = stock.model_dump(by_alias=True, exclude_none=True)
    second = stock.model_copy(update={"ticker": "VALE3"}).model_dump(
        by_alias=True, exclude_none=True
    )
    fake_table.query_pages = [
        {"Items": [item], "LastEvaluatedKey": {"ticker": "PETR4"}},
        {"Items": [second]},
    ]

    found = DynamoDbStockRepository(as_table(fake_table)).list_by_type(ListType.PORTFOLIO)

    assert [s.ticker for s in found] == ["PETR4", "VALE3"]
    assert fake_table.query_calls[1]["ExclusiveStartKey"] == {"ticker": "PETR4"}


def test_history_parses_every_page(fake_table: FakeTable, snapshot: DailySnapshot) -> None:
    fake_table.query_pages = [
        {"Items": [snapshot.model_dump(by_alias=True, exclude_none=True)]},
    ]

    found = DynamoDbSnapshotRepository(as_table(fake_table)).history(
        "PETR4", since=dt.date(2026, 8, 1)
    )

    assert found == [snapshot]


def test_latest_reads_one_row_backwards(fake_table: FakeTable) -> None:
    """ScanIndexForward=False + Limit=1 is the newest day for one read unit."""
    DynamoDbSnapshotRepository(as_table(fake_table)).latest("PETR4")

    call = fake_table.query_calls[0]

    assert call["ScanIndexForward"] is False
    assert call["Limit"] == 1


def test_latest_returns_none_when_never_collected(fake_table: FakeTable) -> None:
    assert DynamoDbSnapshotRepository(as_table(fake_table)).latest("PETR4") is None
