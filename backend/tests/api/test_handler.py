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
)
from shared.repository import InMemorySnapshotRepository, InMemoryStockRepository

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
) -> tuple[int, Any]:
    """Invoke the router the way API Gateway would, and parse the JSON back."""
    response = route(
        {"routeKey": route_key, "queryStringParameters": query, "pathParameters": path},
        InMemoryStockRepository(stocks or []),
        InMemorySnapshotRepository(snapshots or []),
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
