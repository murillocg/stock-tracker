"""In-memory fakes. Same shape as the DynamoDB repositories, no AWS."""

import datetime as dt

from shared.models import DailySnapshot, ListType, Stock


class InMemoryStockRepository:
    """Fake `StockRepository` backed by a dict.

    A hand-written fake rather than a mock: it actually behaves like the real
    thing (upsert semantics, filtering by list type), so a test that passes here
    is testing behaviour, not the call sequence it happens to expect.
    """

    def __init__(self, stocks: list[Stock] | None = None) -> None:
        self._items: dict[str, Stock] = {}
        for stock in stocks or []:
            self.save(stock)

    def get(self, ticker: str) -> Stock | None:
        return self._items.get(ticker.strip().upper())

    def list_by_type(self, list_type: ListType) -> list[Stock]:
        return [s for s in self._items.values() if s.list_type is list_type]

    def save(self, stock: Stock) -> None:
        self._items[stock.ticker] = stock


class InMemorySnapshotRepository:
    """Fake `SnapshotRepository` keyed by (ticker, date), like the real sort key."""

    def __init__(self, snapshots: list[DailySnapshot] | None = None) -> None:
        self._items: dict[str, dict[dt.date, DailySnapshot]] = {}
        for snapshot in snapshots or []:
            self.save(snapshot)

    def get(self, ticker: str, on: dt.date) -> DailySnapshot | None:
        return self._items.get(ticker.strip().upper(), {}).get(on)

    def save(self, snapshot: DailySnapshot) -> None:
        # setdefault inserts the inner dict only if the key is absent, then returns
        # it either way — Java's Map.computeIfAbsent, in one call.
        self._items.setdefault(snapshot.ticker, {})[snapshot.date] = snapshot

    def history(
        self,
        ticker: str,
        since: dt.date,
        until: dt.date | None = None,
    ) -> list[DailySnapshot]:
        by_date = self._items.get(ticker.strip().upper(), {})
        selected = [
            snapshot
            for date, snapshot in by_date.items()
            if date >= since and (until is None or date <= until)
        ]
        return sorted(selected, key=lambda s: s.date)

    def latest(self, ticker: str) -> DailySnapshot | None:
        by_date = self._items.get(ticker.strip().upper(), {})
        if not by_date:
            return None
        return by_date[max(by_date)]
