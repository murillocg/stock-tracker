"""brapi.dev — B3 quotes. The provider for the Phase 0 vertical slice."""

from typing import Any

import httpx

from shared.models import ProviderName
from shared.providers.errors import (
    AuthenticationError,
    FeatureUnavailableError,
    MalformedResponseError,
    ProviderUnavailableError,
    TickerNotFoundError,
)
from shared.providers.parsing import to_decimal
from shared.providers.quote import ProviderQuote

DEFAULT_BASE_URL = "https://brapi.dev/api"

PRICE_KEY = "regularMarketPrice"

QUOTE_FIELD_MAP: dict[str, str] = {
    "pe": "priceEarnings",
}
"""`ProviderQuote` field -> brapi response key.

Deliberately short. Verified against the live API: brapi's free plan returns the
price, `priceEarnings`, `earningsPerShare` and `marketCap`, and nothing else we
model. P/B, EV/EBITDA, ROE, Net Debt/EBITDA and dividend yield are not top-level
keys on *any* plan — they live inside the `defaultKeyStatistics` and
`financialData` modules, which cost R$139,99/mo. Mapping them here would be five
lookups that can only ever return `None`.

Everything fundamental comes from bolsai instead; see `bolsai.py`.
"""


class BrapiProvider:
    """Fetches B3 quotes from brapi.dev.

    Conforms to `QuoteProvider` structurally — note there is no base class and no
    import of the Protocol.

    Price and P/E only: that is the whole of brapi's free plan for our purposes.
    It is the *daily* half of collection. The fundamentals, which move only when
    earnings are released, come from `BolsaiProvider`.
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

        # Checked before the generic fallback below: brapi answers 401
        # `MISSING_TOKEN` for every non-demo ticker when the token is absent or
        # revoked, and calling that "malformed" would send us hunting the wrong bug.
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise AuthenticationError(f"brapi rejected our credentials for {symbol}")
        if response.status_code == httpx.codes.FORBIDDEN:
            raise FeatureUnavailableError(f"brapi plan does not cover this request for {symbol}")
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

        price = to_decimal(result.get(PRICE_KEY))
        if price is None or price <= 0:
            raise MalformedResponseError(f"brapi returned no usable price for {symbol}")

        indicators = {field: to_decimal(result.get(key)) for field, key in QUOTE_FIELD_MAP.items()}
        # `model_validate` rather than the constructor: we are parsing a dict built
        # from a mapping table, and mypy cannot prove a `dict[str, Decimal | None]`
        # fits every keyword argument (`reference_date` is a date). Validation runs.
        return ProviderQuote.model_validate(
            {"ticker": result.get("symbol") or symbol, "price": price, **indicators}
        )
