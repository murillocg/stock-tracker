"""The collection run, driven entirely through in-memory fakes."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfoNotFoundError

import pytest

from collector.handler import (
    CollectionReport,
    TickerOutcome,
    collect_all,
    collect_one,
    market_today,
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
    AuthenticationError,
    FeatureUnavailableError,
    ProviderFundamentals,
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


class StubFundamentalsProvider:
    """A `FundamentalsProvider` that answers from a script.

    A separate stub for a separate Protocol — and note it is a different class
    from `StubProvider` with no common base, which is exactly how the two real
    providers relate.
    """

    def __init__(self, answers: dict[str, ProviderFundamentals | Exception]) -> None:
        self._answers = answers
        self.calls: list[str] = []

    @property
    def name(self) -> ProviderName:
        return ProviderName.BOLSAI

    def fetch_fundamentals(self, ticker: str) -> ProviderFundamentals:
        self.calls.append(ticker)
        answer = self._answers[ticker]
        if isinstance(answer, Exception):
            raise answer
        return answer


def build_fundamentals(ticker: str, **overrides: object) -> ProviderFundamentals:
    payload: dict[str, object] = {
        "ticker": ticker,
        "reference_date": dt.date(2026, 6, 30),
        "pe": Decimal("4.05"),
        "pb": Decimal("1.14"),
        "roe": Decimal("28.26"),
        "roic": Decimal("19.72"),
        "net_debt_to_ebitda": Decimal("1.12"),
        "earnings_cagr_5y": Decimal("77.68"),
        **overrides,
    }
    return ProviderFundamentals.model_validate(payload)


def build_quote(ticker: str, price: str, pe: str | None = None) -> ProviderQuote:
    return ProviderQuote(
        ticker=ticker,
        price=Decimal(price),
        pe=None if pe is None else Decimal(pe),
    )


def build_stock(
    ticker: str,
    list_type: ListType = ListType.PORTFOLIO,
    fundamentals_provider: ProviderName | None = None,
) -> Stock:
    return Stock(
        ticker=ticker,
        name=f"{ticker} SA",
        market=Market.B3,
        currency=Currency.BRL,
        quote_provider=ProviderName.BRAPI,
        fundamentals_provider=fundamentals_provider,
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
    fundamentals: StubFundamentalsProvider | None = None,
    **kwargs: object,
) -> CollectionReport:
    """Drive a whole run with no sleeping and no AWS."""
    return collect_all(
        stocks=stocks,
        snapshots=snapshots,
        quote_registry={ProviderName.BRAPI: provider},
        fundamentals_registry=({} if fundamentals is None else {ProviderName.BOLSAI: fundamentals}),
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
        build_stock("PETR4"),
        quotes=provider,
        fundamentals=None,
        snapshots=snapshots,
        as_of=AS_OF,
    )

    assert snapshot.date == AS_OF
    assert snapshot.price == Decimal("38.5")
    assert snapshot.pe == Decimal("4.5")


def test_collect_one_computes_changes_from_history() -> None:
    snapshots = InMemorySnapshotRepository(build_history("PETR4", days_back=400, price="50"))
    provider = StubProvider({"PETR4": build_quote("PETR4", "40")})

    snapshot = collect_one(
        build_stock("PETR4"),
        quotes=provider,
        fundamentals=None,
        snapshots=snapshots,
        as_of=AS_OF,
    )

    assert snapshot.change_1m == Decimal("-20.00")
    assert snapshot.change_1y == Decimal("-20.00")


def test_derived_ratios_stay_empty_until_we_fetch_statements() -> None:
    """brapi's free tier has no statements, so roic/payout/peg cannot be honest yet."""
    provider = StubProvider({"PETR4": build_quote("PETR4", "38.5")})

    snapshot = collect_one(
        build_stock("PETR4"),
        quotes=provider,
        fundamentals=None,
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


def test_an_unregistered_ticker_is_reported_not_silently_dropped() -> None:
    """Asking for a stock by name and getting an empty report reads as "it ran
    and did nothing", when the real answer is "you have not seeded that yet"."""
    report = run(
        stocks=InMemoryStockRepository(),
        snapshots=InMemorySnapshotRepository(),
        provider=StubProvider({}),
        tickers=["itsa4"],
    )

    assert report.summary[TickerOutcome.NOT_REGISTERED] == 1
    assert report.results[0].ticker == "ITSA4"
    assert report.results[0].detail is not None


def test_a_full_run_can_never_report_unregistered() -> None:
    """Without a ticker filter we iterate the registry, so every stock exists."""
    report = run(
        stocks=InMemoryStockRepository([build_stock("PETR4")]),
        snapshots=InMemorySnapshotRepository(),
        provider=StubProvider({"PETR4": build_quote("PETR4", "38.5")}),
    )

    assert report.summary[TickerOutcome.NOT_REGISTERED] == 0


def test_a_mixed_request_collects_what_it_can() -> None:
    report = run(
        stocks=InMemoryStockRepository([build_stock("PETR4")]),
        snapshots=InMemorySnapshotRepository(),
        provider=StubProvider({"PETR4": build_quote("PETR4", "38.5")}),
        tickers=["PETR4", "ITSA4"],
    )

    assert report.summary[TickerOutcome.COLLECTED] == 1
    assert report.summary[TickerOutcome.NOT_REGISTERED] == 1


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


def test_rejected_credentials_abort_the_whole_run() -> None:
    """A dead token is a run-level problem — do not spend 19 more calls proving it."""
    provider = StubProvider(
        {
            "AAAA3": AuthenticationError("MISSING_TOKEN"),
            "PETR4": build_quote("PETR4", "38.5"),
        }
    )

    with pytest.raises(AuthenticationError):
        run(
            stocks=InMemoryStockRepository([build_stock("AAAA3"), build_stock("PETR4")]),
            snapshots=InMemorySnapshotRepository(),
            provider=provider,
        )

    assert provider.calls == ["AAAA3"]


def test_both_sources_land_in_one_snapshot() -> None:
    stocks = InMemoryStockRepository(
        [build_stock("PETR4", fundamentals_provider=ProviderName.BOLSAI)]
    )
    snapshots = InMemorySnapshotRepository()

    run(
        stocks=stocks,
        snapshots=snapshots,
        provider=StubProvider({"PETR4": build_quote("PETR4", "43.55", pe="4.21")}),
        fundamentals=StubFundamentalsProvider({"PETR4": build_fundamentals("PETR4")}),
    )

    stored = snapshots.get("PETR4", AS_OF)

    assert stored is not None
    assert stored.price == Decimal("43.55")
    assert stored.roe == Decimal("28.26")
    assert stored.roic == Decimal("19.72")
    assert stored.reference_date == dt.date(2026, 6, 30)


def test_the_quotes_pe_wins_over_the_fundamentals_pe() -> None:
    """Both supply P/E. The quote's uses today's price; bolsai's is quarter-end."""
    snapshot = collect_one(
        build_stock("PETR4", fundamentals_provider=ProviderName.BOLSAI),
        quotes=StubProvider({"PETR4": build_quote("PETR4", "43.55", pe="4.21")}),
        fundamentals=build_fundamentals("PETR4", pe=Decimal("4.05")),
        snapshots=InMemorySnapshotRepository(),
        as_of=AS_OF,
    )

    assert snapshot.pe == Decimal("4.21")


def test_an_empty_quote_field_does_not_erase_the_fundamentals() -> None:
    """The quote carries nine mostly-empty indicator fields; they must not win."""
    snapshot = collect_one(
        build_stock("PETR4", fundamentals_provider=ProviderName.BOLSAI),
        quotes=StubProvider({"PETR4": build_quote("PETR4", "43.55")}),
        fundamentals=build_fundamentals("PETR4"),
        snapshots=InMemorySnapshotRepository(),
        as_of=AS_OF,
    )

    assert snapshot.pe == Decimal("4.05")
    assert snapshot.pb == Decimal("1.14")


def test_a_stock_without_a_fundamentals_provider_is_price_only() -> None:
    """Correct for the USDBRL FX rate and for US tickers until that provider exists."""
    fundamentals = StubFundamentalsProvider({})

    report = run(
        stocks=InMemoryStockRepository([build_stock("USDBRL")]),
        snapshots=InMemorySnapshotRepository(),
        provider=StubProvider({"USDBRL": build_quote("USDBRL", "5.42")}),
        fundamentals=fundamentals,
    )

    assert fundamentals.calls == []
    assert report.summary[TickerOutcome.COLLECTED] == 1
    assert report.summary[TickerOutcome.PARTIAL] == 0


def test_failing_fundamentals_still_stores_the_price() -> None:
    """Fundamentals move quarterly; the price is what the drop alert watches."""
    snapshots = InMemorySnapshotRepository()

    report = run(
        stocks=InMemoryStockRepository(
            [build_stock("PETR4", fundamentals_provider=ProviderName.BOLSAI)]
        ),
        snapshots=snapshots,
        provider=StubProvider({"PETR4": build_quote("PETR4", "43.55")}),
        fundamentals=StubFundamentalsProvider(
            {"PETR4": ProviderUnavailableError("bolsai quota exhausted")}
        ),
    )

    stored = snapshots.get("PETR4", AS_OF)

    assert report.summary[TickerOutcome.PARTIAL] == 1
    assert stored is not None
    assert stored.price == Decimal("43.55")
    assert stored.roe is None


def test_a_gated_fundamentals_endpoint_does_not_abort_the_run() -> None:
    """403 means our plan lacks the feature, not that the key is bad."""
    report = run(
        stocks=InMemoryStockRepository(
            [build_stock("PETR4", fundamentals_provider=ProviderName.BOLSAI)]
        ),
        snapshots=InMemorySnapshotRepository(),
        provider=StubProvider({"PETR4": build_quote("PETR4", "43.55")}),
        fundamentals=StubFundamentalsProvider(
            {"PETR4": FeatureUnavailableError("Pro tier required")}
        ),
    )

    assert report.summary[TickerOutcome.PARTIAL] == 1


def test_a_dead_fundamentals_key_still_aborts_the_run() -> None:
    with pytest.raises(AuthenticationError):
        run(
            stocks=InMemoryStockRepository(
                [build_stock("PETR4", fundamentals_provider=ProviderName.BOLSAI)]
            ),
            snapshots=InMemorySnapshotRepository(),
            provider=StubProvider({"PETR4": build_quote("PETR4", "43.55")}),
            fundamentals=StubFundamentalsProvider({"PETR4": AuthenticationError("bad api key")}),
        )


def test_an_unimplemented_provider_is_reported_not_raised() -> None:
    stock = build_stock("AAPL").model_copy(
        update={"quote_provider": ProviderName.ALPHA_VANTAGE, "market": Market.NASDAQ}
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
        quote_registry={
            ProviderName.BRAPI: StubProvider(
                {"PETR4": build_quote("PETR4", "38.5"), "VALE3": build_quote("VALE3", "60")}
            )
        },
        fundamentals_registry={},
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
        quote_registry={ProviderName.BRAPI: StubProvider({"VALE3": build_quote("VALE3", "60")})},
        fundamentals_registry={},
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


def test_the_trading_day_comes_from_the_market_timezone() -> None:
    """Lambda's clock is UTC; a 20:00 Sao Paulo run is 23:00 UTC the same day.

    Without this the snapshot would be stamped tomorrow, and that date is the
    sort key of the whole time series.
    """
    sao_paulo = market_today("America/Sao_Paulo")
    utc = market_today("UTC")

    assert sao_paulo <= utc
    assert (utc - sao_paulo).days <= 1


def test_an_unknown_timezone_fails_loudly() -> None:
    """Proves the IANA database is actually reachable, not silently absent."""
    with pytest.raises(ZoneInfoNotFoundError):
        market_today("Mars/Olympus_Mons")


# --- pacing ------------------------------------------------------------------


def test_both_calls_for_one_stock_are_paced() -> None:
    """Alpha Vantage serves the quote AND the fundamentals, and rejects anything
    faster than one request a second. Pacing per ticker left them back to back."""
    slept: list[float] = []

    collect_all(
        stocks=InMemoryStockRepository(
            [build_stock("MSFT", fundamentals_provider=ProviderName.BOLSAI)]
        ),
        snapshots=InMemorySnapshotRepository(),
        quote_registry={ProviderName.BRAPI: StubProvider({"MSFT": build_quote("MSFT", "513.53")})},
        fundamentals_registry={
            ProviderName.BOLSAI: StubFundamentalsProvider({"MSFT": build_fundamentals("MSFT")})
        },
        as_of=AS_OF,
        delay_seconds=1.5,
        sleep=slept.append,
    )

    # Two upstream calls, one gap between them.
    assert slept == [1.5]


def test_pacing_spans_tickers_as_well() -> None:
    slept: list[float] = []
    stocks = [
        build_stock("PETR4", fundamentals_provider=ProviderName.BOLSAI),
        build_stock("VALE3", fundamentals_provider=ProviderName.BOLSAI),
    ]

    collect_all(
        stocks=InMemoryStockRepository(stocks),
        snapshots=InMemorySnapshotRepository(),
        quote_registry={
            ProviderName.BRAPI: StubProvider(
                {"PETR4": build_quote("PETR4", "43.55"), "VALE3": build_quote("VALE3", "78.58")}
            )
        },
        fundamentals_registry={
            ProviderName.BOLSAI: StubFundamentalsProvider(
                {"PETR4": build_fundamentals("PETR4"), "VALE3": build_fundamentals("VALE3")}
            )
        },
        as_of=AS_OF,
        delay_seconds=1.5,
        sleep=slept.append,
    )

    # 2 stocks x 2 calls = 4 calls, so 3 gaps.
    assert slept == [1.5, 1.5, 1.5]


def test_a_stock_without_fundamentals_costs_one_call() -> None:
    slept: list[float] = []

    collect_all(
        stocks=InMemoryStockRepository([build_stock("USDBRL"), build_stock("PETR4")]),
        snapshots=InMemorySnapshotRepository(),
        quote_registry={
            ProviderName.BRAPI: StubProvider(
                {"USDBRL": build_quote("USDBRL", "5.42"), "PETR4": build_quote("PETR4", "43.55")}
            )
        },
        fundamentals_registry={},
        as_of=AS_OF,
        delay_seconds=1.5,
        sleep=slept.append,
    )

    assert slept == [1.5]


def test_an_existing_day_can_be_recollected_on_request() -> None:
    """`skipExisting: false` is the escape hatch for a row that exists and is
    wrong. Without it a bad row is permanent: the run reports SKIPPED, looks
    healthy, and changes nothing — which is how a price-only backfill row for
    today would have silently stripped the fundamentals off every B3 ticker."""
    snapshots = InMemorySnapshotRepository(
        [DailySnapshot(ticker="PETR4", date=AS_OF, price=Decimal("1.00"))]
    )
    provider = StubProvider({"PETR4": build_quote("PETR4", "42.00")})

    report = run(
        stocks=InMemoryStockRepository([build_stock("PETR4")]),
        snapshots=snapshots,
        provider=provider,
        skip_existing=False,
    )

    assert report.summary[TickerOutcome.SKIPPED] == 0
    refreshed = snapshots.get("PETR4", AS_OF)
    assert refreshed is not None
    assert refreshed.price == Decimal("42.00")


def test_by_default_an_existing_day_is_left_alone() -> None:
    """Re-running a collection must stay cheap: the providers are rate limited,
    and yesterday's answer for yesterday is still yesterday's answer."""
    snapshots = InMemorySnapshotRepository(
        [DailySnapshot(ticker="PETR4", date=AS_OF, price=Decimal("1.00"))]
    )
    provider = StubProvider({"PETR4": build_quote("PETR4", "42.00")})

    report = run(
        stocks=InMemoryStockRepository([build_stock("PETR4")]),
        snapshots=snapshots,
        provider=provider,
    )

    assert report.summary[TickerOutcome.SKIPPED] == 1
    kept = snapshots.get("PETR4", AS_OF)
    assert kept is not None
    assert kept.price == Decimal("1.00")
    assert provider.calls == []
