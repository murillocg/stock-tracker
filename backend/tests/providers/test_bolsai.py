"""bolsai mapping and error translation, over a mocked transport (no network).

The payload below is a trimmed copy of a real free-plan response for PETR4, so
the field names here are verified rather than guessed.
"""

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from shared.models import ProviderName
from shared.providers import (
    AuthenticationError,
    BolsaiProvider,
    FeatureUnavailableError,
    FundamentalsProvider,
    MalformedResponseError,
    ProviderUnavailableError,
    TickerNotFoundError,
)
from shared.providers.bolsai import API_KEY_HEADER

FUNDAMENTALS_PAYLOAD: dict[str, Any] = {
    "ticker": "PETR4",
    "reference_date": "2026-06-30",
    "close_price": 42.7,
    "market_cap": 550348888894.7,
    "pl": 4.05,
    "pvp": 1.14,
    "ev_ebitda": 3.08,
    "roe": 28.26,
    "roic": 19.72,
    "gross_margin": 50.85,
    "ebitda_margin": 51.15,
    "net_debt_ebitda": 1.12,
    "cagr_revenue_5y": 12.83,
    "cagr_earnings_5y": 77.68,
    "ebit": 237156000.0,
    "equity": 480950000.0,
    "net_debt": 312769000.0,
}


def build_provider(handler: Callable[[httpx.Request], httpx.Response]) -> BolsaiProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return BolsaiProvider(client, api_key="test-key", base_url="https://bolsai.test/api/v1")


def ok(payload: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(httpx.codes.OK, json=payload)


def status(code: int) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(code, json={"error": "nope"})


def test_it_satisfies_the_fundamentals_provider_protocol() -> None:
    """Structural conformance against the *second* Protocol, with no inheritance."""
    provider: FundamentalsProvider = build_provider(ok(FUNDAMENTALS_PAYLOAD))

    assert isinstance(provider, FundamentalsProvider)
    assert provider.name is ProviderName.BOLSAI


def test_it_maps_the_verified_field_names() -> None:
    result = build_provider(ok(FUNDAMENTALS_PAYLOAD)).fetch_fundamentals("petr4")

    assert result.ticker == "PETR4"
    assert result.pe == Decimal("4.05")
    assert result.pb == Decimal("1.14")
    assert result.ev_ebitda == Decimal("3.08")
    assert result.net_debt_to_ebitda == Decimal("1.12")


def test_percentages_are_taken_as_given() -> None:
    """bolsai already emits 28.26 rather than 0.2826 — our own convention exactly.

    If this ever starts failing, a provider changed scale and every category
    ruleset silently became a coin flip.
    """
    result = build_provider(ok(FUNDAMENTALS_PAYLOAD)).fetch_fundamentals("PETR4")

    assert result.roe == Decimal("28.26")
    assert result.gross_margin == Decimal("50.85")
    assert result.ebitda_margin == Decimal("51.15")


def test_the_reference_date_is_parsed_as_a_date() -> None:
    result = build_provider(ok(FUNDAMENTALS_PAYLOAD)).fetch_fundamentals("PETR4")

    assert result.reference_date == dt.date(2026, 6, 30)


def test_a_timestamp_reference_date_is_accepted() -> None:
    payload = {**FUNDAMENTALS_PAYLOAD, "reference_date": "2026-06-30T00:00:00Z"}

    result = build_provider(ok(payload)).fetch_fundamentals("PETR4")

    assert result.reference_date == dt.date(2026, 6, 30)


def test_growth_is_mapped_as_cagr_not_year_over_year() -> None:
    """The names say which measure it is; PEG's meaning depends on the answer."""
    result = build_provider(ok(FUNDAMENTALS_PAYLOAD)).fetch_fundamentals("PETR4")

    assert result.revenue_cagr_5y == Decimal("12.83")
    assert result.earnings_cagr_5y == Decimal("77.68")


def test_roic_is_taken_ready_made() -> None:
    result = build_provider(ok(FUNDAMENTALS_PAYLOAD)).fetch_fundamentals("PETR4")

    assert result.roic == Decimal("19.72")


def test_dividend_yield_stays_empty() -> None:
    """Not in /fundamentals despite the docs, and /dividends is Pro-only."""
    result = build_provider(ok(FUNDAMENTALS_PAYLOAD)).fetch_fundamentals("PETR4")

    assert result.dividend_yield is None


def test_the_api_key_is_sent_as_a_header_not_a_query_parameter() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(httpx.codes.OK, json=FUNDAMENTALS_PAYLOAD)

    build_provider(handler).fetch_fundamentals("petr4")

    assert seen[0].headers[API_KEY_HEADER] == "test-key"
    assert seen[0].url.path == "/api/v1/fundamentals/PETR4"
    assert "token" not in seen[0].url.params


def test_a_401_aborts_the_run() -> None:
    with pytest.raises(AuthenticationError):
        build_provider(status(httpx.codes.UNAUTHORIZED)).fetch_fundamentals("PETR4")


def test_a_403_is_a_gated_feature_not_a_bad_key() -> None:
    """bolsai answers 403 'Pro tier required' while the key is perfectly valid."""
    with pytest.raises(FeatureUnavailableError) as caught:
        build_provider(status(httpx.codes.FORBIDDEN)).fetch_fundamentals("PETR4")

    assert not isinstance(caught.value, AuthenticationError)


def test_a_404_becomes_ticker_not_found() -> None:
    with pytest.raises(TickerNotFoundError):
        build_provider(status(httpx.codes.NOT_FOUND)).fetch_fundamentals("NOPE3")


def test_the_daily_quota_running_out_is_retryable() -> None:
    with pytest.raises(ProviderUnavailableError):
        build_provider(status(httpx.codes.TOO_MANY_REQUESTS)).fetch_fundamentals("PETR4")


def test_a_transport_failure_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom", request=request)

    with pytest.raises(ProviderUnavailableError):
        build_provider(handler).fetch_fundamentals("PETR4")


def test_a_missing_reference_date_is_malformed() -> None:
    """Without it we cannot tell whether these are new figures or last quarter's."""
    payload = {key: value for key, value in FUNDAMENTALS_PAYLOAD.items() if key != "reference_date"}

    with pytest.raises(MalformedResponseError):
        build_provider(ok(payload)).fetch_fundamentals("PETR4")


def test_missing_indicators_degrade_to_none() -> None:
    minimal = {"ticker": "AAAA3", "reference_date": "2026-06-30", "pl": 9.5}

    result = build_provider(ok(minimal)).fetch_fundamentals("AAAA3")

    assert result.pe == Decimal("9.5")
    assert result.roe is None
    assert result.roic is None


def test_the_remaining_quota_header_is_readable() -> None:
    response = httpx.Response(httpx.codes.OK, json={}, headers={"X-RateLimit-Remaining": "197"})

    assert BolsaiProvider.remaining_quota(response) == 197


def test_a_missing_quota_header_is_none() -> None:
    assert BolsaiProvider.remaining_quota(httpx.Response(httpx.codes.OK, json={})) is None
