"""The collection run, driven entirely through in-memory fakes."""

import datetime as dt
from decimal import Decimal

import pytest

from collector.handler import (
    CollectionReport,
    TickerOutcome,
    collect_all,
    collect_one,
)
from shared.models import (
    Currency,
    DailySnapshot,
    ListType,
    Market,
    ProviderName,
    Stock,
)
from shared.providers import (
    ProviderQuote,
    ProviderUnavailableError,
    QuoteProvider,
    TickerNotFoundError,
)
from shared.repository import InMemorySnapshotRepository, InMemoryStockRepository

AS_OF = dt.date(2026, 8, 28)


class StubProvider:
    """A `QuoteProvider` that answers from a script.

    Conforms structurally, like `BrapiProvider` does — no base class, no import
    of the Protocol. That is the whole point of the abstraction being a Protocol.
    """

    def __init__(self, quotes: dict[str, ProviderQuote | Exception]) -> None:
        self._quotes = quotes
        self.calls: list[str] = []

    @property
    def name(self) -> ProviderName:
        return ProviderName.BRAPI

    def fetch_quote(self, ticker: str) -> ProviderQuote:
        self.calls.append(ticker)
        answer = self._quotes[ticker]
        if isinstance(answer, Exception):
            raise answer
        return answer


def build_quote(ticker: str, price: str, pe: str | None = None) -> ProviderQuote:
    return ProviderQuote(
        ticker=ticker,
        price=Decimal(price),
        pe=None if pe is None else Decimal(pe),
    )


def build_stock(ticker: str, list_type: ListType = ListType.PORTFOLIO) -> Stock:
    return Stock(
        ticker=ticker,
        name=f"{ticker} SA",
        market=Market.B3,
        currency=Currency.BRL,
        provider=ProviderName.BRAPI,
        list_type=list_type,
    )


def build_history(ticker: str, days_back: int, price: str) -> list[DailySnapshot]:
    return [
        DailySnapshot(
            ticker=ticker,
            date=AS_OF - dt.timedelta(days=offset),
            price=Decimal(price),
        )
        for offset in range(days_back, 0, -1)
    ]


def run(
    *,
    stocks: InMemoryStockRepository,
    snapshots: InMemorySnapshotRepository,
    provider: StubProvider,
    **kwargs: object,
) -> CollectionReport:
    """Drive a whole run with no sleeping and no AWS."""
    return collect_all(
        stocks=stocks,
        snapshots=snapshots,
        registry={ProviderName.BRAPI: provider},
        as_of=AS_OF,
        delay_seconds=1.0,
        sleep=lambda _seconds: None,
        **kwargs,  # type: ignore[arg-type]
    )


def test_the_stub_satisfies_the_provider_protocol() -> None:
    provider: QuoteProvider = StubProvider({})

    assert provider.name is ProviderName.BRAPI


def test_a_collected_snapshot_carries_the_fetched_indicators() -> None:
    snapshots = InMemorySnapshotRepository()
    provider = StubProvider({"PETR4": build_quote("PETR4", "38.5", pe="4.5")})

    snapshot = collect_one(
        build_stock("PETR4"), provider=provider, snapshots=snapshots, as_of=AS_OF
    )

    assert snapshot.date == AS_OF
    assert snapshot.price == Decimal("38.5")
    assert snapshot.pe == Decimal("4.5")


def test_collect_one_computes_changes_from_history() -> None:
    snapshots = InMemorySnapshotRepository(build_history("PETR4", days_back=400, price="50"))
    provider = StubProvider({"PETR4": build_quote("PETR4", "40")})

    snapshot = collect_one(
        build_stock("PETR4"), provider=provider, snapshots=snapshots, as_of=AS_OF
    )

    assert snapshot.change_1m == Decimal("-20.00")
    assert snapshot.change_1y == Decimal("-20.00")


def test_derived_ratios_stay_empty_until_we_fetch_statements() -> None:
    """brapi's free tier has no statements, so roic/payout/peg cannot be honest yet."""
    provider = StubProvider({"PETR4": build_quote("PETR4", "38.5")})

    snapshot = collect_one(
        build_stock("PETR4"),
        provider=provider,
        snapshots=InMemorySnapshotRepository(),
        as_of=AS_OF,
    )

    assert snapshot.roic is None
    assert snapshot.peg is None


def test_a_run_stores_the_snapshot_and_denormalises_it_onto_the_stock() -> None:
    stocks = InMemoryStockRepository([build_stock("PETR4")])
    snapshots = InMemorySnapshotRepository()
    provider = StubProvider({"PETR4": build_quote("PETR4", "38.5")})

    report = run(stocks=stocks, snapshots=snapshots, provider=provider)

    stored = stocks.get("PETR4")
    assert report.summary[TickerOutcome.COLLECTED] == 1
    assert snapshots.get("PETR4", AS_OF) is not None
    assert stored is not None
    assert stored.current is not None
    assert stored.current.price == Decimal("38.5")


def test_the_watchlist_is_collected_too() -> None:
    """Watchlist prices are what the Phase 5 entry-point triggers will read."""
    stocks = InMemoryStockRepository(
        [build_stock("PETR4"), build_stock("VALE3", ListType.WATCHLIST)]
    )
    provider = StubProvider(
        {"PETR4": build_quote("PETR4", "38.5"), "VALE3": build_quote("VALE3", "60")}
    )

    report = run(stocks=stocks, snapshots=InMemorySnapshotRepository(), provider=provider)

    assert report.summary[TickerOutcome.COLLECTED] == 2


def test_an_explicit_ticker_list_narrows_the_run() -> None:
    """This is how the Phase 0 slice gets invoked by hand against one stock."""
    stocks = InMemoryStockRepository([build_stock("PETR4"), build_stock("VALE3")])
    provider = StubProvider({"PETR4": build_quote("PETR4", "38.5")})

    report = run(
        stocks=stocks,
        snapshots=InMemorySnapshotRepository(),
        provider=provider,
        tickers=["PETR4"],
    )

    assert provider.calls == ["PETR4"]
    assert [result.ticker for result in report.results] == ["PETR4"]


def test_an_unregistered_ticker_is_ignored() -> None:
    report = run(
        stocks=InMemoryStockRepository(),
        snapshots=InMemorySnapshotRepository(),
        provider=StubProvider({}),
        tickers=["NOPE3"],
    )

    assert report.results == []


def test_an_already_collected_ticker_is_skipped() -> None:
    """A retry must not re-spend the free-tier quota on work already done."""
    existing = DailySnapshot(ticker="PETR4", date=AS_OF, price=Decimal("38.5"))
    provider = StubProvider({})

    report = run(
        stocks=InMemoryStockRepository([build_stock("PETR4")]),
        snapshots=InMemorySnapshotRepository([existing]),
        provider=provider,
    )

    assert provider.calls == []
    assert report.summary[TickerOutcome.SKIPPED] == 1


def test_skip_existing_can_be_turned_off() -> None:
    existing = DailySnapshot(ticker="PETR4", date=AS_OF, price=Decimal("1"))
    snapshots = InMemorySnapshotRepository([existing])

    run(
        stocks=InMemoryStockRepository([build_stock("PETR4")]),
        snapshots=snapshots,
        provider=StubProvider({"PETR4": build_quote("PETR4", "38.5")}),
        skip_existing=False,
    )

    refreshed = snapshots.get("PETR4", AS_OF)
    assert refreshed is not None
    assert refreshed.price == Decimal("38.5")


def test_an_unknown_ticker_does_not_stop_the_run() -> None:
    stocks = InMemoryStockRepository([build_stock("AAAA3"), build_stock("PETR4")])
    provider = StubProvider(
        {
            "AAAA3": TickerNotFoundError("unknown"),
            "PETR4": build_quote("PETR4", "38.5"),
        }
    )

    report = run(stocks=stocks, snapshots=InMemorySnapshotRepository(), provider=provider)

    assert report.summary[TickerOutcome.NOT_FOUND] == 1
    assert report.summary[TickerOutcome.COLLECTED] == 1


def test_a_provider_outage_is_contained_to_one_ticker() -> None:
    stocks = InMemoryStockRepository([build_stock("AAAA3"), build_stock("PETR4")])
    snapshots = InMemorySnapshotRepository()
    provider = StubProvider(
        {
            "AAAA3": ProviderUnavailableError("rate limited"),
            "PETR4": build_quote("PETR4", "38.5"),
        }
    )

    report = run(stocks=stocks, snapshots=snapshots, provider=provider)

    assert report.summary[TickerOutcome.FAILED] == 1
    assert snapshots.get("PETR4", AS_OF) is not None
    assert snapshots.get("AAAA3", AS_OF) is None


def test_a_failed_ticker_leaves_the_previous_state_alone() -> None:
    """No partial writes: a failure must not blank out yesterday's `current`."""
    yesterday = DailySnapshot(
        ticker="PETR4", date=AS_OF - dt.timedelta(days=1), price=Decimal("40")
    )
    stocks = InMemoryStockRepository(
        [build_stock("PETR4").model_copy(update={"current": yesterday})]
    )
    provider = StubProvider({"PETR4": ProviderUnavailableError("down")})

    run(stocks=stocks, snapshots=InMemorySnapshotRepository(), provider=provider)

    stored = stocks.get("PETR4")
    assert stored is not None
    assert stored.current == yesterday


def test_an_unimplemented_provider_is_reported_not_raised() -> None:
    stock = build_stock("AAPL").model_copy(
        update={"provider": ProviderName.ALPHA_VANTAGE, "market": Market.NASDAQ}
    )

    report = run(
        stocks=InMemoryStockRepository([stock]),
        snapshots=InMemorySnapshotRepository(),
        provider=StubProvider({}),
    )

    assert report.summary[TickerOutcome.FAILED] == 1


def test_collection_pauses_between_upstream_calls() -> None:
    """Sequential with a delay: free-tier rate limits, never parallelism."""
    slept: list[float] = []
    stocks = InMemoryStockRepository([build_stock("PETR4"), build_stock("VALE3")])

    collect_all(
        stocks=stocks,
        snapshots=InMemorySnapshotRepository(),
        registry={
            ProviderName.BRAPI: StubProvider(
                {"PETR4": build_quote("PETR4", "38.5"), "VALE3": build_quote("VALE3", "60")}
            )
        },
        as_of=AS_OF,
        delay_seconds=1.5,
        sleep=slept.append,
    )

    assert slept == [1.5]


def test_a_skipped_ticker_costs_no_delay() -> None:
    """Nothing was fetched, so there is no rate limit to respect."""
    slept: list[float] = []
    existing = DailySnapshot(ticker="PETR4", date=AS_OF, price=Decimal("38.5"))

    collect_all(
        stocks=InMemoryStockRepository([build_stock("PETR4"), build_stock("VALE3")]),
        snapshots=InMemorySnapshotRepository([existing]),
        registry={ProviderName.BRAPI: StubProvider({"VALE3": build_quote("VALE3", "60")})},
        as_of=AS_OF,
        delay_seconds=1.5,
        sleep=slept.append,
    )

    assert slept == []


def test_a_repository_outage_is_allowed_to_fail_the_run() -> None:
    """DynamoDB being down makes the run worthless — let EventBridge retry it."""

    class BrokenSnapshots(InMemorySnapshotRepository):
        def save(self, snapshot: DailySnapshot) -> None:
            raise RuntimeError("DynamoDB unavailable")

    with pytest.raises(RuntimeError):
        run(
            stocks=InMemoryStockRepository([build_stock("PETR4")]),
            snapshots=BrokenSnapshots(),
            provider=StubProvider({"PETR4": build_quote("PETR4", "38.5")}),
        )


def test_the_report_serialises_for_cloudwatch() -> None:
    report = run(
        stocks=InMemoryStockRepository([build_stock("PETR4")]),
        snapshots=InMemorySnapshotRepository(),
        provider=StubProvider({"PETR4": build_quote("PETR4", "38.5")}),
    )

    payload = report.model_dump(mode="json", by_alias=True)

    assert payload["asOf"] == "2026-08-28"
    assert payload["summary"]["COLLECTED"] == 1
    assert payload["results"][0]["ticker"] == "PETR4"
