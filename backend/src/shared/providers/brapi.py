"""brapi.dev — B3 quotes. The provider for the Phase 0 vertical slice."""

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from shared.models import ProviderName
from shared.providers.errors import (
    MalformedResponseError,
    ProviderUnavailableError,
    TickerNotFoundError,
)
from shared.providers.quote import ProviderQuote

DEFAULT_BASE_URL = "https://brapi.dev/api"


def _to_decimal(value: Any) -> Decimal | None:
    """Coerce one JSON number to `Decimal`, or `None` if it is unusable.

    JSON numbers arrive as `float`, which cannot represent 0.1 exactly. Going
    through `str` first is what stops 4.5 from becoming 4.4999999999999996 — the
    same reason you would never hold money in a Java `double`.

    A field we cannot parse becomes `None` rather than an exception: one bad
    indicator must not cost us the whole quote.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class BrapiProvider:
    """Fetches B3 quotes from brapi.dev.

    Conforms to `QuoteProvider` structurally — note there is no base class and no
    import of the Protocol.

    The free tier reliably returns the price and a small number of ratios. The
    fuller indicator set (EV/EBITDA, Net Debt/EBITDA) comes from bolsai; anything
    neither supplies is derived in the COMPUTE step.
    """

    def __init__(
        self,
        client: httpx.Client,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        """The http client is injected, never built here.

        That is what lets tests hand in a client backed by a mock transport, and
        what lets the Lambda reuse one connection pool across warm invocations.
        """
        self._client = client
        self._token = token
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> ProviderName:
        return ProviderName.BRAPI

    def fetch_quote(self, ticker: str) -> ProviderQuote:
        symbol = ticker.strip().upper()
        try:
            response = self._client.get(
                f"{self._base_url}/quote/{symbol}",
                params={"token": self._token},
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"brapi request failed for {symbol}: {exc}") from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise TickerNotFoundError(f"brapi does not know ticker {symbol}")
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise ProviderUnavailableError(f"brapi returned {response.status_code} for {symbol}")
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise ProviderUnavailableError(f"brapi rate limit hit for {symbol}")
        if response.status_code != httpx.codes.OK:
            raise MalformedResponseError(f"brapi returned {response.status_code} for {symbol}")

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise MalformedResponseError(f"brapi returned non-JSON for {symbol}") from exc

        return self._map(symbol, payload)

    def _map(self, symbol: str, payload: Any) -> ProviderQuote:
        """Translate brapi's wire format into our own. The only place that knows it."""
        if not isinstance(payload, dict):
            raise MalformedResponseError(f"brapi payload for {symbol} is not an object")

        results = payload.get("results")
        if not isinstance(results, list) or not results:
            raise TickerNotFoundError(f"brapi returned no results for {symbol}")

        result = results[0]
        if not isinstance(result, dict):
            raise MalformedResponseError(f"brapi result for {symbol} is not an object")

        price = _to_decimal(result.get("regularMarketPrice"))
        if price is None or price <= 0:
            raise MalformedResponseError(f"brapi returned no usable price for {symbol}")

        return ProviderQuote(
            ticker=result.get("symbol") or symbol,
            price=price,
            pe=_to_decimal(result.get("priceEarnings")),
            pb=_to_decimal(result.get("priceToBook")),
            ev_ebitda=_to_decimal(result.get("enterpriseValueToEbitda")),
            roe=_to_decimal(result.get("returnOnEquity")),
            net_debt_to_ebitda=_to_decimal(result.get("netDebtToEbitda")),
            dividend_yield=_to_decimal(result.get("dividendYield")),
        )
