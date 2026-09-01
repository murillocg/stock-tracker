"""Persistence abstractions. Nothing above this layer ever sees boto3."""

import datetime as dt
from typing import Protocol

from shared.models import DailySnapshot, ListType, Stock, Transaction


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

    def earliest(self, ticker: str) -> DailySnapshot | None:
        """The oldest snapshot we hold. `None` if we have never collected it.

        Exists so the UI can say how much history a change window still needs.
        A 1-month change is not "missing" three days after collection began — it
        is not due yet, and a bare dash cannot tell those apart.
        """
        ...


class TransactionRepository(Protocol):
    """The `Transactions` ledger. PK=`ticker`, SK=`<date>#<id>`.

    Append-only in practice: `save` exists, nothing updates or deletes. A trade
    that was entered wrongly is corrected by recording the correction, which is
    what keeps the derived average price reproducible from the ledger alone.
    """

    def save(self, transaction: Transaction) -> None:
        """Record one trade. Idempotent by (ticker, date, id)."""
        ...

    def for_ticker(self, ticker: str) -> list[Transaction]:
        """Every trade in one ticker, oldest first. The input to `build_position`."""
        ...

    def all(self) -> list[Transaction]:
        """Every trade across every ticker.

        A scan, which is the one place this codebase does one. The alternative —
        a GSI keyed on something constant — would cost write units on every trade
        to avoid a table read of a few hundred rows a few times a day.
        """
        ...
