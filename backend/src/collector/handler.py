"""Lambda 1: fetch -> compute -> store. Triggered once a day by EventBridge.

The AWS entry point is `lambda_handler`, which does nothing but build real
resources and hand them to `collect_all`. All the logic lives in `collect_all`,
which takes every dependency as a parameter and never imports boto3 — so the
whole collection run is testable against in-memory fakes.
"""

import datetime as dt
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any

import boto3
import httpx
from pydantic import computed_field

from shared.config import Config
from shared.indicators import apply_changes, compute_changes
from shared.models import CamelModel, DailySnapshot, ListType, ProviderName, Stock
from shared.providers import (
    AuthenticationError,
    ProviderError,
    QuoteProvider,
    TickerNotFoundError,
    get_provider,
)
from shared.providers.factory import build_registry
from shared.repository import (
    DynamoDbSnapshotRepository,
    DynamoDbStockRepository,
    SnapshotRepository,
    StockRepository,
)

logger = logging.getLogger(__name__)

HISTORY_LOOKBACK = dt.timedelta(days=400)
"""How far back to read before computing changes.

The widest window is 365 days, plus the 7-day staleness tolerance, plus margin.
Reading less would silently drop `change1y`; reading a lot more just costs read
units for rows nothing looks at.
"""

HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
"""Bounded so one hanging provider cannot burn the whole Lambda timeout."""


class TickerOutcome(StrEnum):
    """What happened to one ticker. Every run reports one of these per stock."""

    COLLECTED = "COLLECTED"
    SKIPPED = "SKIPPED"
    """Already collected for this date — a retry must not re-spend API quota."""

    NOT_FOUND = "NOT_FOUND"
    """The provider does not know this ticker. Retrying will not help."""

    FAILED = "FAILED"
    """Transport error, rate limit, or an unmappable response. Retryable."""


class TickerResult(CamelModel):
    ticker: str
    outcome: TickerOutcome
    detail: str | None = None


class CollectionReport(CamelModel):
    """The Lambda's return value, and the thing you read in CloudWatch."""

    as_of: dt.date
    results: list[TickerResult]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> dict[str, int]:
        """Counts per outcome.

        `computed_field` makes a derived property part of the serialised output —
        Jackson's `@JsonGetter`. A plain `@property` would be invisible to
        `model_dump`.
        """
        counts = dict.fromkeys(TickerOutcome, 0)
        for result in self.results:
            counts[result.outcome] += 1
        return {outcome.value: count for outcome, count in counts.items()}


def collect_one(
    stock: Stock,
    *,
    provider: QuoteProvider,
    snapshots: SnapshotRepository,
    as_of: dt.date,
) -> DailySnapshot:
    """FETCH then COMPUTE for a single stock. Does not persist anything.

    The derived ratios (roic, payout, peg, growth) stay `None` for now: they need
    figures from the financial statements, and no provider we have implemented
    returns those yet. The changes are computed here because they come from our
    own history, which we do have.
    """
    quote = provider.fetch_quote(stock.ticker)

    history = snapshots.history(
        stock.ticker,
        since=as_of - HISTORY_LOOKBACK,
        until=as_of - dt.timedelta(days=1),
    )
    changes = compute_changes(history, as_of=as_of, current_price=quote.price)

    # `**` splats the dict into keyword arguments — the FETCH indicators carry
    # across without naming all nine. `ticker` and `date` are set explicitly
    # because the snapshot is keyed on them.
    snapshot = DailySnapshot(
        ticker=stock.ticker,
        date=as_of,
        **quote.model_dump(exclude={"ticker"}),
    )
    return apply_changes(snapshot, changes)


def _targets(stocks: StockRepository, tickers: Sequence[str] | None) -> list[Stock]:
    """Which stocks this run covers.

    Both lists by default: the watchlist needs prices too, for entry-point alerts.
    An explicit ticker list is what makes the Phase 0 slice runnable by hand
    against a single stock.
    """
    if tickers:
        found = (stocks.get(ticker) for ticker in tickers)
        return [stock for stock in found if stock is not None]
    return [
        *stocks.list_by_type(ListType.PORTFOLIO),
        *stocks.list_by_type(ListType.WATCHLIST),
    ]


def collect_all(
    *,
    stocks: StockRepository,
    snapshots: SnapshotRepository,
    registry: Mapping[ProviderName, QuoteProvider],
    as_of: dt.date,
    delay_seconds: float,
    tickers: Sequence[str] | None = None,
    skip_existing: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectionReport:
    """Collect every target sequentially, one ticker at a time.

    Sequential with a pause between upstream calls, never parallel — free-tier
    rate limits are the binding constraint, not wall-clock time.

    Provider failures are contained per ticker: one dead symbol must not cost the
    other nineteen. Two kinds are deliberately *not* contained, because both make
    the rest of the run pointless and should fail loudly instead:

    - `AuthenticationError` — every remaining ticker would fail identically.
    - repository errors — if DynamoDB is down there is nowhere to put the data.

    `sleep` is injected so tests run instantly instead of actually waiting.
    """
    results: list[TickerResult] = []
    called_provider = False

    for stock in _targets(stocks, tickers):
        if skip_existing and snapshots.get(stock.ticker, as_of) is not None:
            results.append(TickerResult(ticker=stock.ticker, outcome=TickerOutcome.SKIPPED))
            continue

        if called_provider:
            sleep(delay_seconds)

        try:
            provider = get_provider(registry, stock.provider)
            called_provider = True
            snapshot = collect_one(stock, provider=provider, snapshots=snapshots, as_of=as_of)
        except AuthenticationError:
            # Listed first because it is a subclass of ProviderError and `except`
            # clauses are tried in order — the generic handler below would
            # otherwise swallow it. Same rule as Java's catch blocks.
            logger.error("Provider credentials rejected — aborting the run at %s", stock.ticker)
            raise
        except TickerNotFoundError as exc:
            logger.warning("Ticker %s unknown to %s: %s", stock.ticker, stock.provider, exc)
            results.append(
                TickerResult(ticker=stock.ticker, outcome=TickerOutcome.NOT_FOUND, detail=str(exc))
            )
            continue
        except ProviderError as exc:
            logger.error("Collection failed for %s: %s", stock.ticker, exc)
            results.append(
                TickerResult(ticker=stock.ticker, outcome=TickerOutcome.FAILED, detail=str(exc))
            )
            continue

        snapshots.save(snapshot)
        # Denormalise onto the registry item so the frontend renders the whole
        # portfolio from one GSI query.
        stocks.save(stock.model_copy(update={"current": snapshot}))
        results.append(TickerResult(ticker=stock.ticker, outcome=TickerOutcome.COLLECTED))

    report = CollectionReport(as_of=as_of, results=results)
    logger.info("Collection finished for %s: %s", as_of, report.summary)
    return report


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS entry point. Wiring only — no logic lives here.

    Resources are built per invocation rather than cached at module scope. This
    Lambda runs once a day, so every invocation is a cold start anyway and the
    usual warm-reuse trick would buy nothing.

    Accepts two optional overrides in the event, for manual runs:
      `{"tickers": ["PETR4"], "asOf": "2026-08-28"}`
    """
    config = Config.from_env()

    raw_as_of = event.get("asOf")
    as_of = dt.date.fromisoformat(raw_as_of) if raw_as_of else dt.date.today()
    tickers = event.get("tickers")

    dynamodb = boto3.resource("dynamodb", region_name=config.aws_region)
    stocks = DynamoDbStockRepository(dynamodb.Table(config.stocks_table))
    snapshots = DynamoDbSnapshotRepository(dynamodb.Table(config.snapshots_table))

    # One connection pool for the whole run, closed on the way out.
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        report = collect_all(
            stocks=stocks,
            snapshots=snapshots,
            registry=build_registry(client, config),
            as_of=as_of,
            delay_seconds=config.provider_delay_seconds,
            tickers=tickers,
        )

    return report.model_dump(mode="json", by_alias=True)
