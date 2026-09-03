"""The read API, driven through in-memory fakes. No AWS, no API Gateway."""

import datetime as dt
import json
from decimal import Decimal
from typing import Any

import pytest

from api.handler import MAX_HISTORY_DAYS, route
from shared.categories import Signal
from shared.models import (
    Currency,
    DailySnapshot,
    ListType,
    LynchCategory,
    Market,
    ProviderName,
    Stock,
    Transaction,
    TransactionType,
)
from shared.repository import (
    InMemorySnapshotRepository,
    InMemoryStockRepository,
    InMemoryTransactionRepository,
)

TODAY = dt.date.today()


def build_snapshot(ticker: str, day: dt.date, **values: object) -> DailySnapshot:
    return DailySnapshot.model_validate(
        {"ticker": ticker, "date": day, "price": Decimal("43.55"), **values}
    )


def build_stock(ticker: str, **values: object) -> Stock:
    return Stock.model_validate(
        {
            "ticker": ticker,
            "name": f"{ticker} SA",
            "market": Market.B3,
            "currency": Currency.BRL,
            "quote_provider": ProviderName.BRAPI,
            "list_type": ListType.PORTFOLIO,
            **values,
        }
    )


def call(
    route_key: str,
    *,
    stocks: list[Stock] | None = None,
    snapshots: list[DailySnapshot] | None = None,
    query: dict[str, str] | None = None,
    path: dict[str, str] | None = None,
    transactions: list[Transaction] | None = None,
) -> tuple[int, Any]:
    """Invoke the router the way API Gateway would, and parse the JSON back."""
    response = route(
        {"routeKey": route_key, "queryStringParameters": query, "pathParameters": path},
        InMemoryStockRepository(stocks or []),
        InMemorySnapshotRepository(snapshots or []),
        InMemoryTransactionRepository(transactions or []),
    )
    return response["statusCode"], json.loads(response["body"])


# --- GET /stocks -------------------------------------------------------------


def test_the_list_carries_the_verdict_with_each_stock() -> None:
    """Computed server-side so Vue never re-implements the rulesets."""
    stock = build_stock(
        "PRIO3",
        category=LynchCategory.FAST_GROWER,
        current=build_snapshot("PRIO3", TODAY, pe=Decimal("12"), earnings_cagr_5y=Decimal("30")),
    )

    status, body = call("GET /stocks", stocks=[stock])

    assert status == 200
    assert body["stocks"][0]["evaluation"]["signal"] == Signal.GREEN
    assert body["stocks"][0]["evaluation"]["checks"][0]["name"] == "PEG"


def test_decimals_are_serialised_as_strings_not_floats() -> None:
    """JavaScript numbers are float64; 4.2084 would not survive the round trip."""
    stock = build_stock("PETR4", current=build_snapshot("PETR4", TODAY, pe=Decimal("4.2084")))

    _, body = call("GET /stocks", stocks=[stock])

    assert body["stocks"][0]["current"]["pe"] == "4.2084"


def test_the_response_uses_camel_case() -> None:
    stock = build_stock("PETR4", current=build_snapshot("PETR4", TODAY))

    _, body = call("GET /stocks", stocks=[stock])

    assert "listType" in body["stocks"][0]
    assert "list_type" not in body["stocks"][0]


def test_the_list_can_be_filtered_by_type() -> None:
    stocks = [
        build_stock("PETR4"),
        build_stock("VALE3", list_type=ListType.WATCHLIST),
    ]

    _, body = call("GET /stocks", stocks=stocks, query={"listType": "WATCHLIST"})

    assert [s["ticker"] for s in body["stocks"]] == ["VALE3"]


def test_an_unfiltered_list_returns_both() -> None:
    stocks = [build_stock("PETR4"), build_stock("VALE3", list_type=ListType.WATCHLIST)]

    _, body = call("GET /stocks", stocks=stocks)

    assert len(body["stocks"]) == 2


def test_the_list_is_sorted_by_ticker() -> None:
    stocks = [build_stock("VALE3"), build_stock("BBAS3"), build_stock("PETR4")]

    _, body = call("GET /stocks", stocks=stocks)

    assert [s["ticker"] for s in body["stocks"]] == ["BBAS3", "PETR4", "VALE3"]


def test_an_unknown_list_type_is_a_400_naming_the_options() -> None:
    status, body = call("GET /stocks", query={"listType": "FAVOURITES"})

    assert status == 400
    assert "PORTFOLIO" in body["message"]


def test_an_empty_registry_is_an_empty_list_not_an_error() -> None:
    status, body = call("GET /stocks")

    assert status == 200
    assert body["stocks"] == []


def test_a_stock_with_no_snapshot_still_appears() -> None:
    """A newly seeded stock must be visible before the collector has run."""
    status, body = call("GET /stocks", stocks=[build_stock("TTEN3")])

    assert status == 200
    assert body["stocks"][0]["current"] is None
    assert body["stocks"][0]["evaluation"]["signal"] == Signal.INSUFFICIENT_DATA


# --- GET /stocks/{ticker} ----------------------------------------------------


def test_the_detail_returns_history_for_the_chart() -> None:
    history = [build_snapshot("PETR4", TODAY - dt.timedelta(days=offset)) for offset in range(5)]

    status, body = call(
        "GET /stocks/{ticker}",
        stocks=[build_stock("PETR4")],
        snapshots=history,
        path={"ticker": "PETR4"},
    )

    assert status == 200
    assert body["stock"]["ticker"] == "PETR4"
    assert len(body["history"]) == 5


def test_history_is_oldest_first_so_a_chart_can_plot_it_directly() -> None:
    history = [build_snapshot("PETR4", TODAY - dt.timedelta(days=offset)) for offset in (3, 1, 2)]

    _, body = call(
        "GET /stocks/{ticker}",
        stocks=[build_stock("PETR4")],
        snapshots=history,
        path={"ticker": "PETR4"},
    )

    dates = [row["date"] for row in body["history"]]
    assert dates == sorted(dates)


def test_the_history_window_is_configurable() -> None:
    history = [build_snapshot("PETR4", TODAY - dt.timedelta(days=offset)) for offset in range(120)]

    _, body = call(
        "GET /stocks/{ticker}",
        stocks=[build_stock("PETR4")],
        snapshots=history,
        path={"ticker": "PETR4"},
        query={"days": "10"},
    )

    assert len(body["history"]) == 11  # inclusive of today


def test_an_absurd_window_is_clamped_not_honoured() -> None:
    """Stops `?days=99999` turning into a scan of the whole partition."""
    history = [build_snapshot("PETR4", TODAY - dt.timedelta(days=offset)) for offset in range(3)]

    status, body = call(
        "GET /stocks/{ticker}",
        stocks=[build_stock("PETR4")],
        snapshots=history,
        path={"ticker": "PETR4"},
        query={"days": str(MAX_HISTORY_DAYS * 100)},
    )

    assert status == 200
    assert len(body["history"]) == 3


def test_a_non_numeric_window_is_a_400() -> None:
    status, _ = call(
        "GET /stocks/{ticker}",
        stocks=[build_stock("PETR4")],
        path={"ticker": "PETR4"},
        query={"days": "lots"},
    )

    assert status == 400


def test_an_unregistered_ticker_is_a_404() -> None:
    status, body = call("GET /stocks/{ticker}", path={"ticker": "NOPE3"})

    assert status == 404
    assert "NOPE3" in body["message"]


def test_the_ticker_lookup_is_case_insensitive() -> None:
    status, _ = call(
        "GET /stocks/{ticker}", stocks=[build_stock("PETR4")], path={"ticker": "petr4"}
    )

    assert status == 200


@pytest.mark.parametrize(
    "route_key", ["POST /stocks", "GET /unknown", "DELETE /stocks/{ticker}", ""]
)
def test_unknown_routes_are_404(route_key: str) -> None:
    """Read-only by design: the collector owns every write."""
    status, _ = call(route_key)

    assert status == 404


# --- positions and weight ----------------------------------------------------


def buy(ticker: str, quantity: str, price: str, day: int = 1) -> Transaction:
    return Transaction(
        ticker=ticker,
        date=TODAY - dt.timedelta(days=day),
        type=TransactionType.BUY,
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        currency=Currency.BRL,
    )


def test_a_holding_carries_its_position_and_valuation() -> None:
    stock = build_stock("PETR4", current=build_snapshot("PETR4", TODAY))

    _, body = call("GET /stocks", stocks=[stock], transactions=[buy("PETR4", "100", "40.00")])
    holding = body["stocks"][0]

    assert holding["position"]["quantity"] == "100"
    assert holding["position"]["averagePrice"] == "40.00"
    assert holding["valuation"]["marketValue"] == "4355.00"  # 100 x 43.55
    assert holding["valuation"]["unrealisedGain"] == "355.00"


def test_weights_are_computed_across_the_portfolio() -> None:
    """The number Phase 3 exists for: a green light means little on a holding
    that is already a fifth of the portfolio."""
    a = build_stock("AAAA3", current=build_snapshot("AAAA3", TODAY))
    b = build_stock("BBBB3", current=build_snapshot("BBBB3", TODAY))

    _, body = call(
        "GET /stocks",
        stocks=[a, b],
        transactions=[buy("AAAA3", "300", "10"), buy("BBBB3", "100", "10")],
    )
    weights = {s["ticker"]: s["valuation"]["weight"] for s in body["stocks"]}

    assert weights == {"AAAA3": "75.00", "BBBB3": "25.00"}


def test_the_totals_are_computed_server_side() -> None:
    """So the frontend never re-adds the parts and disagrees with itself."""
    stock = build_stock("PETR4", current=build_snapshot("PETR4", TODAY))

    _, body = call("GET /stocks", stocks=[stock], transactions=[buy("PETR4", "100", "40.00")])

    assert body["totals"]["invested"] == "4000.00"
    assert body["totals"]["marketValue"] == "4355.00"
    assert body["totals"]["currency"] == "BRL"
    assert body["totals"]["priced"] == 1


def test_a_stock_with_no_trades_has_no_position() -> None:
    """The five Avenue holdings, until that import exists."""
    _, body = call("GET /stocks", stocks=[build_stock("MSFT")])

    assert body["stocks"][0]["position"] is None
    assert body["stocks"][0]["valuation"] is None


def test_a_foreign_currency_holding_is_left_out_of_the_weights() -> None:
    """Adding USD into a BRL total without a rate is not an approximation, it is
    an addition of unlike things."""
    brl = build_stock("PETR4", current=build_snapshot("PETR4", TODAY))
    usd = build_stock("MSFT", currency=Currency.USD, current=build_snapshot("MSFT", TODAY))

    _, body = call(
        "GET /stocks",
        stocks=[brl, usd],
        transactions=[buy("PETR4", "100", "40.00"), buy("MSFT", "10", "500")],
    )
    by_ticker = {s["ticker"]: s for s in body["stocks"]}

    assert by_ticker["MSFT"]["position"] is not None  # it is still held
    assert by_ticker["MSFT"]["valuation"] is None  # but not priced
    assert by_ticker["PETR4"]["valuation"]["weight"] == "100.00"
    assert body["totals"]["unpriced"] == 1


def test_a_closed_position_reports_nothing() -> None:
    sell = Transaction(
        ticker="PETR4",
        date=TODAY,
        type=TransactionType.SELL,
        quantity=Decimal("100"),
        unit_price=Decimal("50"),
        currency=Currency.BRL,
    )
    stock = build_stock("PETR4", current=build_snapshot("PETR4", TODAY))

    _, body = call("GET /stocks", stocks=[stock], transactions=[buy("PETR4", "100", "40"), sell])

    assert body["stocks"][0]["position"] is None


def test_the_detail_view_carries_the_position_too() -> None:
    status, body = call(
        "GET /stocks/{ticker}",
        stocks=[build_stock("PETR4", current=build_snapshot("PETR4", TODAY))],
        transactions=[buy("PETR4", "100", "40.00")],
        path={"ticker": "PETR4"},
    )

    assert status == 200
    assert body["stock"]["position"]["invested"] == "4000.00"


# --- cross-currency totals ---------------------------------------------------


def usd_book() -> tuple[list[Stock], list[Transaction]]:
    """One BRL holding, one USD holding, and the rate that joins them."""
    stocks = [
        build_stock("VALE3", current=build_snapshot("VALE3", TODAY, price=Decimal("50.00"))),
        build_stock(
            "MSFT",
            market=Market.NASDAQ,
            currency=Currency.USD,
            quote_provider=ProviderName.ALPHA_VANTAGE,
            current=build_snapshot("MSFT", TODAY, price=Decimal("450.00")),
        ),
        # The rate travels as an ordinary REFERENCE row, not a special case.
        build_stock(
            "USDBRL",
            list_type=ListType.REFERENCE,
            current=build_snapshot("USDBRL", TODAY, price=Decimal("5.2005")),
        ),
    ]
    transactions = [
        Transaction(
            ticker="VALE3",
            date=TODAY,
            type=TransactionType.BUY,
            quantity=Decimal("100"),
            unit_price=Decimal("50.00"),
            currency=Currency.BRL,
            id="v1",
        ),
        Transaction(
            ticker="MSFT",
            date=TODAY,
            type=TransactionType.BUY,
            quantity=Decimal("4"),
            unit_price=Decimal("443.02"),
            currency=Currency.USD,
            id="m1",
        ),
    ]
    return stocks, transactions


def test_a_usd_holding_is_weighed_against_the_brazilian_book() -> None:
    stocks, transactions = usd_book()

    _, body = call("GET /stocks", stocks=stocks, transactions=transactions)
    by_ticker = {s["ticker"]: s for s in body["stocks"]}

    # The row itself stays in dollars — it has to match what Avenue reports.
    assert by_ticker["MSFT"]["valuation"]["marketValue"] == "1800.00"
    # The weight does not: R$9,360.90 against a R$14,360.90 book.
    assert by_ticker["MSFT"]["valuation"]["weight"] == "65.18"
    assert by_ticker["VALE3"]["valuation"]["weight"] == "34.82"

    assert body["totals"]["marketValue"] == "14360.90"
    assert body["totals"]["currency"] == Currency.BRL
    assert body["totals"]["priced"] == 2
    assert body["totals"]["unpriced"] == 0


def test_without_the_rate_the_usd_holding_drops_out_but_the_book_still_totals() -> None:
    """The Brazilian side is most of the portfolio and must survive a failed FX
    collection — degraded, and visibly so, rather than absent or wrong."""
    stocks, transactions = usd_book()
    stocks = [s for s in stocks if s.ticker != "USDBRL"]

    _, body = call("GET /stocks", stocks=stocks, transactions=transactions)
    by_ticker = {s["ticker"]: s for s in body["stocks"]}

    assert by_ticker["MSFT"]["valuation"] is None
    assert by_ticker["VALE3"]["valuation"]["weight"] == "100.00"
    assert body["totals"]["marketValue"] == "5000.00"
    assert body["totals"]["priced"] == 1
    assert body["totals"]["unpriced"] == 1


def test_the_rate_itself_is_never_listed_as_a_holding() -> None:
    stocks, transactions = usd_book()

    _, body = call("GET /stocks", stocks=stocks, transactions=transactions)

    assert "USDBRL" not in {s["ticker"] for s in body["stocks"]}


# --- the watchlist -----------------------------------------------------------


def test_the_watchlist_has_no_totals_because_nothing_is_owned() -> None:
    stock = build_stock(
        "TOTS3",
        list_type=ListType.WATCHLIST,
        category=LynchCategory.STALWART,
        current=build_snapshot("TOTS3", TODAY, price=Decimal("34.74"), pe=Decimal("14.49")),
    )

    status, body = call("GET /stocks", stocks=[stock], query={"listType": "WATCHLIST"})

    assert status == 200
    assert "totals" not in body
    assert body["stocks"][0]["ticker"] == "TOTS3"


def test_it_carries_an_entry_price_derived_from_the_category() -> None:
    """A P/E of 10 against a Brazilian limit of 15 means the price could rise by
    half and still be green — so the entry sits above today's."""
    stock = build_stock(
        "TOTS3",
        list_type=ListType.WATCHLIST,
        category=LynchCategory.STALWART,
        current=build_snapshot(
            "TOTS3", TODAY, price=Decimal("100"), pe=Decimal("10"), roe=Decimal("20")
        ),
    )

    _, body = call("GET /stocks", stocks=[stock], query={"listType": "WATCHLIST"})

    assert body["stocks"][0]["entry"]["price"] == "150.00"
    assert body["stocks"][0]["entry"]["discountNeeded"] == "50.00"


def test_an_untagged_stock_gets_no_entry_price() -> None:
    """The category is the input: a stalwart is judged on P/E, a fast grower on
    PEG. Without one there is no threshold to invert."""
    stock = build_stock(
        "TOTS3",
        list_type=ListType.WATCHLIST,
        current=build_snapshot("TOTS3", TODAY, price=Decimal("100"), pe=Decimal("10")),
    )

    _, body = call("GET /stocks", stocks=[stock], query={"listType": "WATCHLIST"})

    assert body["stocks"][0]["entry"]["price"] is None


def test_the_52_week_range_uses_the_alias_the_frontend_expects() -> None:
    """`to_camel` renders `range_52w` as `range52W`, which the frontend does not
    read. The explicit alias is load-bearing."""
    stock = build_stock(
        "TOTS3",
        list_type=ListType.WATCHLIST,
        current=build_snapshot("TOTS3", TODAY, price=Decimal("30")),
    )
    history = [
        build_snapshot("TOTS3", TODAY - dt.timedelta(days=n), price=Decimal(20 + n))
        for n in range(1, 30)
    ]

    _, body = call(
        "GET /stocks", stocks=[stock], snapshots=history, query={"listType": "WATCHLIST"}
    )

    assert "range52w" in body["stocks"][0]
    assert body["stocks"][0]["range52w"]["low"] == "21"


def test_a_recorded_fair_value_reaches_the_watchlist() -> None:
    """Regression: the field existed on the response model but nothing assigned
    it, so it serialised as null and read as "no research recorded" while the
    value sat in DynamoDB. A model field with no assignment fails silently."""
    stock = build_stock(
        "VIVA3",
        list_type=ListType.WATCHLIST,
        category=LynchCategory.STALWART,
        current=build_snapshot("VIVA3", TODAY, price=Decimal("23.76"), pe=Decimal("9.53")),
        fair_value=Decimal("30.14"),
        fair_value_source="Analyst DCF",
        fair_value_on=dt.date(2026, 9, 3),
    )

    _, body = call("GET /stocks", stocks=[stock], query={"listType": "WATCHLIST"})
    item = body["stocks"][0]

    assert item["fairValue"] == "30.14"
    assert item["fairValueSource"] == "Analyst DCF"
    assert item["fairValueOn"] == "2026-09-03"
