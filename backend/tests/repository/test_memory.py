"""The in-memory fakes must behave like the real repositories, not just compile."""

import datetime as dt
from decimal import Decimal

from shared.models import DailySnapshot, ListType, Stock
from shared.repository import (
    InMemorySnapshotRepository,
    InMemoryStockRepository,
    SnapshotRepository,
    StockRepository,
)


def build_snapshot(ticker: str, day: int, price: str) -> DailySnapshot:
    return DailySnapshot(
        ticker=ticker,
        date=dt.date(2026, 8, day),
        price=Decimal(price),
    )


def test_it_satisfies_the_repository_protocols(stock: Stock) -> None:
    """mypy checks these two annotations structurally; no base class involved."""
    stocks: StockRepository = InMemoryStockRepository([stock])
    snapshots: SnapshotRepository = InMemorySnapshotRepository()

    assert stocks.get("PETR4") == stock
    assert snapshots.latest("PETR4") is None


def test_an_unknown_ticker_returns_none() -> None:
    assert InMemoryStockRepository().get("NOPE3") is None


def test_lookups_are_case_insensitive(stock: Stock) -> None:
    assert InMemoryStockRepository([stock]).get(" petr4 ") == stock


def test_save_is_an_upsert(stock: Stock) -> None:
    repo = InMemoryStockRepository([stock])
    repo.save(stock.model_copy(update={"name": "Petrobras PN (renamed)"}))

    assert repo.get("PETR4") is not None
    assert len(repo.list_by_type(ListType.PORTFOLIO)) == 1


def test_list_by_type_partitions_the_registry(stock: Stock) -> None:
    watched = stock.model_copy(update={"ticker": "VALE3", "list_type": ListType.WATCHLIST})
    repo = InMemoryStockRepository([stock, watched])

    assert [s.ticker for s in repo.list_by_type(ListType.PORTFOLIO)] == ["PETR4"]
    assert [s.ticker for s in repo.list_by_type(ListType.WATCHLIST)] == ["VALE3"]


def test_snapshots_are_keyed_by_ticker_and_date() -> None:
    repo = InMemorySnapshotRepository([build_snapshot("PETR4", 27, "37")])
    repo.save(build_snapshot("PETR4", 27, "39"))

    stored = repo.get("PETR4", dt.date(2026, 8, 27))

    assert stored is not None
    assert stored.price == Decimal("39")


def test_history_is_bounded_and_ordered_oldest_first() -> None:
    repo = InMemorySnapshotRepository(
        [build_snapshot("PETR4", day, "38") for day in (28, 25, 26, 27)]
    )

    window = repo.history("PETR4", since=dt.date(2026, 8, 26), until=dt.date(2026, 8, 27))

    assert [s.date.day for s in window] == [26, 27]


def test_history_is_open_ended_without_an_until() -> None:
    repo = InMemorySnapshotRepository(
        [build_snapshot("PETR4", day, "38") for day in (25, 26, 27, 28)]
    )

    assert len(repo.history("PETR4", since=dt.date(2026, 8, 26))) == 3


def test_latest_returns_the_newest_day() -> None:
    repo = InMemorySnapshotRepository([build_snapshot("PETR4", day, "38") for day in (25, 28, 26)])

    newest = repo.latest("PETR4")

    assert newest is not None
    assert newest.date == dt.date(2026, 8, 28)


def test_history_of_an_untracked_ticker_is_empty() -> None:
    assert InMemorySnapshotRepository().history("NOPE3", since=dt.date(2026, 1, 1)) == []
