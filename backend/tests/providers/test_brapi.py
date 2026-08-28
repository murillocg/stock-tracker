"""brapi mapping and error translation, over a mocked transport (no network)."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from shared.models import ProviderName
from shared.providers import (
    BrapiProvider,
    MalformedResponseError,
    ProviderUnavailableError,
    QuoteProvider,
    TickerNotFoundError,
)

QUOTE_PAYLOAD: dict[str, Any] = {
    "results": [
        {
            "symbol": "PETR4",
            "regularMarketPrice": 38.5,
            "priceEarnings": 0.1,
            "priceToBook": 1.25,
        }
    ]
}


def build_provider(handler: Callable[[httpx.Request], httpx.Response]) -> BrapiProvider:
    """Wire a provider onto a fake transport.

    `httpx.MockTransport` intercepts at the transport layer, so the provider makes
    a completely ordinary `client.get(...)` call and no socket is ever opened.
    """
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return BrapiProvider(client, token="test-token", base_url="https://brapi.test/api")


def ok(payload: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(httpx.codes.OK, json=payload)


def status(code: int) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(code, json={"error": True})


def test_it_satisfies_the_quote_provider_protocol() -> None:
    """Structural conformance, with no inheritance anywhere in sight.

    The annotation is the real assertion — mypy verifies it statically. The
    runtime check below only confirms the members exist.
    """
    provider: QuoteProvider = build_provider(ok(QUOTE_PAYLOAD))

    assert isinstance(provider, QuoteProvider)
    assert provider.name is ProviderName.BRAPI


def test_it_maps_the_payload_onto_a_quote() -> None:
    quote = build_provider(ok(QUOTE_PAYLOAD)).fetch_quote("petr4")

    assert quote.ticker == "PETR4"
    assert quote.price == Decimal("38.5")
    assert quote.pb == Decimal("1.25")


def test_json_floats_become_exact_decimals() -> None:
    """0.1 has no exact binary representation; going through str keeps it honest."""
    quote = build_provider(ok(QUOTE_PAYLOAD)).fetch_quote("PETR4")

    assert quote.pe == Decimal("0.1")
    # Decimal(0.1) is 0.1000000000000000055511151231257827... — the float we would
    # have stored had we skipped the str hop. ruff flags this pattern precisely
    # because it is almost always a bug; here it is the point being demonstrated.
    assert quote.pe != Decimal(0.1)  # noqa: RUF032


def test_indicators_the_free_tier_omits_are_none() -> None:
    quote = build_provider(ok(QUOTE_PAYLOAD)).fetch_quote("PETR4")

    assert quote.ev_ebitda is None
    assert quote.roe is None


def test_the_token_is_sent_as_a_query_parameter() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(httpx.codes.OK, json=QUOTE_PAYLOAD)

    build_provider(handler).fetch_quote("petr4")

    assert seen[0].params["token"] == "test-token"
    assert seen[0].path == "/api/quote/PETR4"


def test_a_404_becomes_ticker_not_found() -> None:
    with pytest.raises(TickerNotFoundError):
        build_provider(status(httpx.codes.NOT_FOUND)).fetch_quote("NOPE3")


def test_an_empty_result_list_becomes_ticker_not_found() -> None:
    with pytest.raises(TickerNotFoundError):
        build_provider(ok({"results": []})).fetch_quote("NOPE3")


@pytest.mark.parametrize(
    "code",
    [
        httpx.codes.INTERNAL_SERVER_ERROR,
        httpx.codes.BAD_GATEWAY,
        httpx.codes.TOO_MANY_REQUESTS,
    ],
)
def test_server_errors_and_rate_limits_are_retryable(code: int) -> None:
    with pytest.raises(ProviderUnavailableError):
        build_provider(status(code)).fetch_quote("PETR4")


def test_a_transport_failure_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom", request=request)

    with pytest.raises(ProviderUnavailableError):
        build_provider(handler).fetch_quote("PETR4")


def test_a_missing_price_is_malformed() -> None:
    with pytest.raises(MalformedResponseError):
        build_provider(ok({"results": [{"symbol": "PETR4"}]})).fetch_quote("PETR4")


def test_a_zero_price_is_malformed() -> None:
    with pytest.raises(MalformedResponseError):
        build_provider(ok({"results": [{"symbol": "PETR4", "regularMarketPrice": 0}]})).fetch_quote(
            "PETR4"
        )
