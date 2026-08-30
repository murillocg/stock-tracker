"""The Banco Central exchange-rate provider, over a mocked transport."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from shared.models import ProviderName
from shared.providers import (
    BancoCentralProvider,
    MalformedResponseError,
    ProviderUnavailableError,
    QuoteProvider,
    TickerNotFoundError,
)

# The whole of the SGS response format.
SERIES_PAYLOAD: list[dict[str, Any]] = [{"data": "28/08/2026", "valor": "5.2005"}]


def build_provider(handler: Callable[[httpx.Request], httpx.Response]) -> BancoCentralProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return BancoCentralProvider(client, base_url="https://bcb.test/dados/serie")


def ok(payload: Any) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(httpx.codes.OK, json=payload)


def test_it_satisfies_the_quote_provider_protocol() -> None:
    provider: QuoteProvider = build_provider(ok(SERIES_PAYLOAD))

    assert provider.name is ProviderName.BANCO_CENTRAL


def test_it_reads_the_dollar_rate() -> None:
    quote = build_provider(ok(SERIES_PAYLOAD)).fetch_quote("usdbrl")

    assert quote.ticker == "USDBRL"
    assert quote.price == Decimal("5.2005")


def test_it_asks_for_the_right_series() -> None:
    """Series 1 is the daily PTAX dollar selling rate."""
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(httpx.codes.OK, json=SERIES_PAYLOAD)

    build_provider(handler).fetch_quote("USDBRL")

    assert seen[0].path.endswith("/bcdata.sgs.1/dados/ultimos/1")
    assert seen[0].params["formato"] == "json"


def test_it_needs_no_credential() -> None:
    """The SGS series are open data — no key, no quota, nothing to rotate."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(httpx.codes.OK, json=SERIES_PAYLOAD)

    build_provider(handler).fetch_quote("USDBRL")

    assert "token" not in seen[0].url.params
    assert "apikey" not in seen[0].url.params
    assert "X-API-Key" not in seen[0].headers


def test_a_rate_carries_no_fundamentals() -> None:
    quote = build_provider(ok(SERIES_PAYLOAD)).fetch_quote("USDBRL")

    assert quote.pe is None
    assert quote.reference_date is None


def test_asking_for_an_equity_says_so_plainly() -> None:
    """This provider serves rates. A ticker is not a mistake to hide."""
    with pytest.raises(TickerNotFoundError, match="exchange rates"):
        build_provider(ok(SERIES_PAYLOAD)).fetch_quote("PETR4")


def test_an_empty_series_is_malformed() -> None:
    with pytest.raises(MalformedResponseError):
        build_provider(ok([])).fetch_quote("USDBRL")


def test_a_transport_failure_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom", request=request)

    with pytest.raises(ProviderUnavailableError):
        build_provider(handler).fetch_quote("USDBRL")
