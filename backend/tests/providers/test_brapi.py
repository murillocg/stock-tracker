"""brapi mapping and error translation, over a mocked transport (no network)."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from shared.models import ProviderName
from shared.providers import (
    AuthenticationError,
    BrapiProvider,
    FeatureUnavailableError,
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
            "earningsPerShare": 385.0,
            "marketCap": 578883123320,
        }
    ]
}
"""The shape of a real free-plan response: no fundamentals anywhere.

`priceEarnings` is 0.1 here purely to exercise float-to-Decimal precision below.
"""


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


def test_ratios_are_rounded_to_four_places() -> None:
    """brapi returned a P/E of 4.208420706782756 in production — sixteen digits,
    about four of them meaningful. Fetched ratios now match computed ones."""
    payload = {
        "results": [
            {"symbol": "PETR4", "regularMarketPrice": 43.55, "priceEarnings": 4.208420706782756}
        ]
    }

    quote = build_provider(ok(payload)).fetch_quote("PETR4")

    assert quote.pe == Decimal("4.2084")
    assert quote.price == Decimal("43.55")


def test_it_maps_the_payload_onto_a_quote() -> None:
    quote = build_provider(ok(QUOTE_PAYLOAD)).fetch_quote("petr4")

    assert quote.ticker == "PETR4"
    assert quote.price == Decimal("38.5")
    assert quote.pe == Decimal("0.1")


def test_json_floats_become_exact_decimals() -> None:
    """0.1 has no exact binary representation; going through str keeps it honest."""
    quote = build_provider(ok(QUOTE_PAYLOAD)).fetch_quote("PETR4")

    assert quote.pe == Decimal("0.1")
    # Decimal(0.1) is 0.1000000000000000055511151231257827... — the float we would
    # have stored had we skipped the str hop. ruff flags this pattern precisely
    # because it is almost always a bug; here it is the point being demonstrated.
    assert quote.pe != Decimal(0.1)  # noqa: RUF032


def test_the_free_plan_carries_no_fundamentals_at_all() -> None:
    """Verified against the live API: these live in Pro-only modules, not here.

    They come from `BolsaiProvider` instead, which is why `QUOTE_FIELD_MAP` no
    longer pretends to look for them.
    """
    quote = build_provider(ok(QUOTE_PAYLOAD)).fetch_quote("PETR4")

    assert quote.pb is None
    assert quote.ev_ebitda is None
    assert quote.roe is None
    assert quote.net_debt_to_ebitda is None
    assert quote.dividend_yield is None


def test_the_token_is_sent_as_a_query_parameter() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(httpx.codes.OK, json=QUOTE_PAYLOAD)

    build_provider(handler).fetch_quote("petr4")

    assert seen[0].params["token"] == "test-token"
    assert seen[0].path == "/api/quote/PETR4"


def test_rejected_credentials_are_their_own_error() -> None:
    """brapi answers 401 MISSING_TOKEN for every non-demo ticker without a token.

    It must not be reported as a malformed response: the fix is a new token, not
    a mapping bug, and the run should stop rather than retry 19 more times.
    """
    with pytest.raises(AuthenticationError):
        build_provider(status(httpx.codes.UNAUTHORIZED)).fetch_quote("WEGE3")


def test_a_gated_feature_is_not_a_credentials_problem() -> None:
    """brapi answers 403 MODULES_NOT_AVAILABLE while the token is valid."""
    with pytest.raises(FeatureUnavailableError):
        build_provider(status(httpx.codes.FORBIDDEN)).fetch_quote("WEGE3")


def test_a_401_is_not_treated_as_retryable() -> None:
    with pytest.raises(AuthenticationError) as caught:
        build_provider(status(httpx.codes.UNAUTHORIZED)).fetch_quote("WEGE3")

    assert not isinstance(caught.value, ProviderUnavailableError)


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
