"""Persistence abstractions. Nothing above this layer ever sees boto3."""

import datetime as dt
from typing import Protocol

from shared.models import DailySnapshot, ListType, Stock


class StockRepository(Protocol):
    """The `Stocks` table: registry plus denormalised current state."""

    def get(self, ticker: str) -> Stock | None:
        """One stock, or `None` if it is not registered.

        `None` rather than an exception: "not tracked" is an ordinary answer.
        Unlike Java, mypy forces every caller to narrow the `| None` before use,
        so this cannot become a NullPointerException at 3am in a Lambda.
        """
        ...

    def list_by_type(self, list_type: ListType) -> list[Stock]:
        """Everything in the portfolio, or everything on the watchlist.

        Backed by the `listType` GSI, so the frontend renders a whole list from a
        single query — that is what the denormalised `current` field buys.
        """
        ...

    def save(self, stock: Stock) -> None:
        """Insert or overwrite. Idempotent: re-running the collector is safe."""
        ...


class SnapshotRepository(Protocol):
    """The `DailySnapshots` time series. PK=`ticker`, SK=`date`."""

    def get(self, ticker: str, on: dt.date) -> DailySnapshot | None:
        """One specific day, or `None`. Used to skip a ticker already collected."""
        ...

    def save(self, snapshot: DailySnapshot) -> None:
        """Insert or overwrite one day. Idempotent by (ticker, date)."""
        ...

    def history(
        self,
        ticker: str,
        since: dt.date,
        until: dt.date | None = None,
    ) -> list[DailySnapshot]:
        """Snapshots in `[since, until]`, oldest first.

        This is what the COMPUTE step reads to derive change1w/1m/6m/1y — those
        percentages come from our own history, not from any provider.
        """
        ...

    def latest(self, ticker: str) -> DailySnapshot | None:
        """The most recent snapshot, or `None` if we have never collected it."""
        ...
