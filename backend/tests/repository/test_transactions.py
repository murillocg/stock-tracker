"""The transaction ledger, in memory and against a fake DynamoDB table."""

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from shared.models import Currency, Transaction, TransactionType
from shared.repository import (
    DynamoDbTransactionRepository,
    InMemoryTransactionRepository,
    TransactionRepository,
)
from tests.conftest import FakeTable

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


def trade(ticker: str, day: int, quantity: str, price: str, tid: str | None = None) -> Transaction:
    return Transaction.model_validate(
        {
            "ticker": ticker,
            "date": dt.date(2026, 3, day),
            "type": TransactionType.BUY,
            "quantity": Decimal(quantity),
            "unit_price": Decimal(price),
            "currency": Currency.BRL,
            **({"id": tid} if tid else {}),
        }
    )


def as_table(fake: FakeTable) -> "Table":
    return cast("Table", fake)


def test_both_implementations_satisfy_the_protocol(fake_table: FakeTable) -> None:
    memory: TransactionRepository = InMemoryTransactionRepository()
    dynamo: TransactionRepository = DynamoDbTransactionRepository(as_table(fake_table))

    assert memory.for_ticker("PETR4") == []
    assert dynamo.for_ticker("PETR4") == []


def test_the_ledger_comes_back_oldest_first() -> None:
    repo = InMemoryTransactionRepository(
        [trade("PETR4", 9, "50", "42"), trade("PETR4", 1, "100", "38")]
    )

    assert [t.date.day for t in repo.for_ticker("PETR4")] == [1, 9]


def test_two_trades_on_one_day_both_survive() -> None:
    """A date-only sort key would have silently overwritten one of them."""
    repo = InMemoryTransactionRepository(
        [trade("PETR4", 1, "100", "38", tid="aaa"), trade("PETR4", 1, "100", "40", tid="bbb")]
    )

    assert len(repo.for_ticker("PETR4")) == 2


def test_re_saving_the_same_trade_does_not_duplicate_it() -> None:
    """Idempotent by (ticker, date, id), so a re-run of an import is safe."""
    one = trade("PETR4", 1, "100", "38", tid="aaa")
    repo = InMemoryTransactionRepository([one, one])

    assert len(repo.for_ticker("PETR4")) == 1


def test_tickers_do_not_bleed_into_each_other() -> None:
    repo = InMemoryTransactionRepository(
        [trade("PETR4", 1, "100", "38"), trade("VALE3", 1, "10", "78")]
    )

    assert [t.ticker for t in repo.for_ticker("VALE3")] == ["VALE3"]
    assert len(repo.all()) == 2


def test_the_written_item_carries_the_composite_sort_key(fake_table: FakeTable) -> None:
    """`dateId` is derived, not a model field — the repository owns the key shape."""
    DynamoDbTransactionRepository(as_table(fake_table)).save(
        trade("PETR4", 1, "100", "38", tid="aaa")
    )

    item = fake_table.put_items[0]

    assert item["dateId"] == "2026-03-01#aaa"
    assert item["ticker"] == "PETR4"
    assert isinstance(item["unitPrice"], Decimal)


def test_a_scan_walks_every_page(fake_table: FakeTable) -> None:
    first = trade("PETR4", 1, "100", "38", tid="aaa").model_dump(by_alias=True, exclude_none=True)
    second = trade("VALE3", 2, "10", "78", tid="bbb").model_dump(by_alias=True, exclude_none=True)
    fake_table.scan_pages = [
        {"Items": [first], "LastEvaluatedKey": {"ticker": "PETR4"}},
        {"Items": [second]},
    ]

    found = DynamoDbTransactionRepository(as_table(fake_table)).all()

    assert [t.ticker for t in found] == ["PETR4", "VALE3"]
