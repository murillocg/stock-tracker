"""Alpha Vantage mapping, unit scaling, and its unusual error conventions."""

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from shared.models import ProviderName
from shared.providers import (
    AlphaVantageProvider,
    AuthenticationError,
    FundamentalsProvider,
    MalformedResponseError,
    ProviderUnavailableError,
    QuoteProvider,
    TickerNotFoundError,
)

QUOTE_PAYLOAD: dict[str, Any] = {"Global Quote": {"01. symbol": "MSFT", "05. price": "430.5000"}}

OVERVIEW_PAYLOAD: dict[str, Any] = {
    "Symbol": "MSFT",
    "LatestQuarter": "2026-06-30",
    "PERatio": "35.2",
    "PriceToBookRatio": "12.41",
    "EVToEBITDA": "24.5",
    "ReturnOnEquityTTM": "0.3512",
    "DividendYield": "0.0072",
    "PayoutRatio": "0.2534",
    "OperatingMarginTTM": "0.4471",
}


def build_provider(handler: Callable[[httpx.Request], httpx.Response]) -> AlphaVantageProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AlphaVantageProvider(client, api_key="test-key", base_url="https://av.test/query")


def ok(payload: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(httpx.codes.OK, json=payload)


def test_one_class_satisfies_both_protocols() -> None:
    """The reason the two Protocols were kept separate rather than merged.

    No `implements` list anywhere — the same object simply has both shapes.
    """
    provider = build_provider(ok(QUOTE_PAYLOAD))
    as_quotes: QuoteProvider = provider
    as_fundamentals: FundamentalsProvider = provider

    assert as_quotes.name is ProviderName.ALPHA_VANTAGE
    assert as_fundamentals.name is ProviderName.ALPHA_VANTAGE


def test_it_reads_the_price_from_the_numbered_key() -> None:
    quote = build_provider(ok(QUOTE_PAYLOAD)).fetch_quote("msft")

    assert quote.ticker == "MSFT"
    assert quote.price == Decimal("430.5000")


def test_fractions_are_scaled_to_percentages() -> None:
    """ROE arrives as 0.3512 while bolsai and our own indicators speak percent.

    Storing both scales in one column would break every category ruleset in a way
    nothing would flag: the P/E band would work and the ROE band would not.
    """
    result = build_provider(ok(OVERVIEW_PAYLOAD)).fetch_fundamentals("MSFT")

    assert result.roe == Decimal("35.12")
    assert result.dividend_yield == Decimal("0.72")
    assert result.payout_ratio == Decimal("25.34")


def test_plain_ratios_are_left_alone() -> None:
    result = build_provider(ok(OVERVIEW_PAYLOAD)).fetch_fundamentals("MSFT")

    assert result.pe == Decimal("35.2")
    assert result.pb == Decimal("12.41")
    assert result.ev_ebitda == Decimal("24.5")


def test_us_stocks_carry_the_dividend_figures_b3_cannot() -> None:
    """The gap that forced hand-maintained fields for BBSE3 and CPLE3."""
    result = build_provider(ok(OVERVIEW_PAYLOAD)).fetch_fundamentals("MSFT")

    assert result.dividend_yield is not None
    assert result.payout_ratio is not None


def test_the_five_year_cagrs_stay_empty() -> None:
    """OVERVIEW has a quarterly YoY figure, which is not a 5-year CAGR.

    Writing it into `earnings_cagr_5y` would be a lie, and PEG's meaning depends
    on which growth measure feeds it.
    """
    result = build_provider(ok(OVERVIEW_PAYLOAD)).fetch_fundamentals("MSFT")

    assert result.earnings_cagr_5y is None
    assert result.revenue_cagr_5y is None


def test_the_latest_quarter_becomes_the_reference_date() -> None:
    result = build_provider(ok(OVERVIEW_PAYLOAD)).fetch_fundamentals("MSFT")

    assert result.reference_date == dt.date(2026, 6, 30)


def test_the_api_key_is_sent() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(httpx.codes.OK, json=QUOTE_PAYLOAD)

    build_provider(handler).fetch_quote("MSFT")

    assert seen[0].params["apikey"] == "test-key"
    assert seen[0].params["function"] == "GLOBAL_QUOTE"


# --- Alpha Vantage's in-body errors, all served with HTTP 200 ----------------


def test_a_rate_limit_arrives_as_http_200_and_is_still_retryable() -> None:
    """The trap: checking status_code alone would read this as an empty success."""
    payload = {"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 25/day."}

    with pytest.raises(ProviderUnavailableError):
        build_provider(ok(payload)).fetch_quote("MSFT")


def test_the_newer_information_envelope_is_also_a_limit() -> None:
    payload = {"Information": "Our standard API rate limit was reached."}

    with pytest.raises(ProviderUnavailableError):
        build_provider(ok(payload)).fetch_fundamentals("MSFT")


def test_an_invalid_key_aborts_the_run() -> None:
    payload = {"Information": "the parameter apikey is invalid or missing."}

    with pytest.raises(AuthenticationError):
        build_provider(ok(payload)).fetch_quote("MSFT")


def test_an_unknown_symbol_is_reported_as_not_found() -> None:
    payload = {"Error Message": "Invalid API call. Please retry."}

    with pytest.raises(TickerNotFoundError):
        build_provider(ok(payload)).fetch_quote("NOPE")


def test_an_empty_overview_means_the_symbol_is_unknown() -> None:
    """OVERVIEW answers an unknown ticker with {} rather than an error."""
    with pytest.raises(TickerNotFoundError):
        build_provider(ok({})).fetch_fundamentals("NOPE")


def test_an_empty_quote_envelope_means_unknown() -> None:
    with pytest.raises(TickerNotFoundError):
        build_provider(ok({"Global Quote": {}})).fetch_quote("NOPE")


def test_a_missing_price_is_malformed() -> None:
    with pytest.raises(MalformedResponseError):
        build_provider(ok({"Global Quote": {"01. symbol": "MSFT"}})).fetch_quote("MSFT")


def test_a_transport_failure_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom", request=request)

    with pytest.raises(ProviderUnavailableError):
        build_provider(handler).fetch_quote("MSFT")
