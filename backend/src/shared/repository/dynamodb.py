"""DynamoDB implementations. The only files in the codebase that know boto3."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import ConditionBase, Key

from shared.models import DailySnapshot, ListType, Stock, Transaction

if TYPE_CHECKING:
    # Imported for typing only. `boto3-stubs` is a dev dependency and is not in the
    # Lambda Layer, so this import must never execute at runtime — `from __future__
    # import annotations` above turns every annotation into a string, which is what
    # makes that safe. It also saves the import cost on a cold start.
    from mypy_boto3_dynamodb.service_resource import Table

LIST_TYPE_INDEX = "listType-index"
"""GSI on the Stocks table: partition key `listType`, sort key `ticker`."""


def _to_item(model: Stock | DailySnapshot) -> dict[str, Any]:
    """Pydantic model -> DynamoDB item.

    `by_alias=True` emits camelCase attribute names. `exclude_none=True` drops
    absent indicators entirely instead of storing nulls — DynamoDB bills by item
    size, and a sparse item is the natural representation of "the free tier did
    not give us this one".

    Note the dump stays in *python* mode: `Decimal` must reach boto3 as `Decimal`,
    because boto3 refuses `float` outright ("Float types are not supported").
    JSON mode would stringify it.
    """
    return model.model_dump(by_alias=True, exclude_none=True)


class DynamoDbStockRepository:
    """`Stocks` table. Conforms to `StockRepository` structurally."""

    def __init__(self, table: Table) -> None:
        """The boto3 Table resource is injected, not built here.

        Constructing it outside means the Lambda handler creates it once per cold
        start and reuses it across warm invocations, and tests pass a fake.
        """
        self._table = table

    def get(self, ticker: str) -> Stock | None:
        response = self._table.get_item(Key={"ticker": ticker.strip().upper()})
        item = response.get("Item")
        return None if item is None else Stock.model_validate(item)

    def list_by_type(self, list_type: ListType) -> list[Stock]:
        condition = Key("listType").eq(list_type.value)
        items: list[dict[str, Any]] = []
        start_key: dict[str, Any] | None = None

        # DynamoDB caps a query response at 1 MB and hands back a cursor. A personal
        # portfolio will never reach that, but a silently truncated list is the kind
        # of bug you only find once it matters.
        while True:
            if start_key is None:
                response = self._table.query(
                    IndexName=LIST_TYPE_INDEX,
                    KeyConditionExpression=condition,
                )
            else:
                response = self._table.query(
                    IndexName=LIST_TYPE_INDEX,
                    KeyConditionExpression=condition,
                    ExclusiveStartKey=start_key,
                )
            items.extend(response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break

        return [Stock.model_validate(item) for item in items]

    def save(self, stock: Stock) -> None:
        self._table.put_item(Item=_to_item(stock))


class DynamoDbSnapshotRepository:
    """`DailySnapshots` table. Conforms to `SnapshotRepository` structurally."""

    def __init__(self, table: Table) -> None:
        self._table = table

    def get(self, ticker: str, on: dt.date) -> DailySnapshot | None:
        response = self._table.get_item(
            Key={"ticker": ticker.strip().upper(), "date": on.isoformat()}
        )
        item = response.get("Item")
        return None if item is None else DailySnapshot.model_validate(item)

    def save(self, snapshot: DailySnapshot) -> None:
        self._table.put_item(Item=_to_item(snapshot))

    def history(
        self,
        ticker: str,
        since: dt.date,
        until: dt.date | None = None,
    ) -> list[DailySnapshot]:
        key = Key("ticker").eq(ticker.strip().upper())
        # ISO 8601 sorts lexicographically the same way it sorts chronologically,
        # which is what lets a plain string sort key answer a date-range query.
        date_key = Key("date")
        condition = (
            key & date_key.gte(since.isoformat())
            if until is None
            else key & date_key.between(since.isoformat(), until.isoformat())
        )

        items: list[dict[str, Any]] = []
        start_key: dict[str, Any] | None = None
        while True:
            if start_key is None:
                response = self._table.query(KeyConditionExpression=condition)
            else:
                response = self._table.query(
                    KeyConditionExpression=condition,
                    ExclusiveStartKey=start_key,
                )
            items.extend(response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break

        return [DailySnapshot.model_validate(item) for item in items]

    def latest(self, ticker: str) -> DailySnapshot | None:
        # ScanIndexForward=False walks the sort key backwards, so Limit=1 is the
        # newest day. One read unit, no scan.
        response = self._table.query(
            KeyConditionExpression=Key("ticker").eq(ticker.strip().upper()),
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("Items", [])
        return None if not items else DailySnapshot.model_validate(items[0])


class DynamoDbTransactionRepository:
    """`Transactions` table. Conforms to `TransactionRepository` structurally."""

    def __init__(self, table: Table) -> None:
        self._table = table

    def save(self, transaction: Transaction) -> None:
        item = transaction.model_dump(by_alias=True, exclude_none=True)
        # The sort key is derived rather than stored on the model, so it is added
        # here — the only place that knows the table's key shape.
        item["dateId"] = transaction.sort_key
        self._table.put_item(Item=item)

    def for_ticker(self, ticker: str) -> list[Transaction]:
        return self._query(Key("ticker").eq(ticker.strip().upper()))

    def all(self) -> list[Transaction]:
        """The one scan in this codebase.

        A ledger has no natural partition to query across, and the alternative —
        a GSI keyed on a constant — would burn write units on every trade to save
        a read of a few hundred rows a few times a day. Revisit if it ever grows
        past a few thousand.
        """
        items: list[dict[str, Any]] = []
        start_key: dict[str, Any] | None = None
        while True:
            if start_key is None:
                response = self._table.scan()
            else:
                response = self._table.scan(ExclusiveStartKey=start_key)
            items.extend(response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
        return [Transaction.model_validate(item) for item in items]

    def _query(self, condition: ConditionBase) -> list[Transaction]:
        items: list[dict[str, Any]] = []
        start_key: dict[str, Any] | None = None
        while True:
            if start_key is None:
                response = self._table.query(KeyConditionExpression=condition)
            else:
                response = self._table.query(
                    KeyConditionExpression=condition, ExclusiveStartKey=start_key
                )
            items.extend(response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
        # The sort key orders them by date already; sorting again costs nothing
        # and removes the caller's dependence on that being true.
        return sorted(
            (Transaction.model_validate(item) for item in items),
            key=lambda t: (t.date, t.id),
        )
