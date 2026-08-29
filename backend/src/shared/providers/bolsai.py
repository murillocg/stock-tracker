"""usebolsai.com — B3 fundamentals. The COMPUTE-side data source.

Every field name below was verified against a live free-plan response rather than
the documentation, which claims `/fundamentals` carries a dividend yield it does
not actually return.
"""

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
from shared.providers.fundamentals import ProviderFundamentals
from shared.providers.parsing import to_date, to_ratio

DEFAULT_BASE_URL = "https://api.usebolsai.com/api/v1"

API_KEY_HEADER = "X-API-Key"

RATE_LIMIT_HEADER = "X-RateLimit-Remaining"
"""bolsai reports the remaining daily budget on every response. The free plan
allows 200 requests/day, resetting at midnight UTC."""

REFERENCE_DATE_KEY = "reference_date"

FUNDAMENTALS_FIELD_MAP: dict[str, str] = {
    "pe": "pl",
    "pb": "pvp",
    "ev_ebitda": "ev_ebitda",
    "roe": "roe",
    "net_debt_to_ebitda": "net_debt_ebitda",
    "gross_margin": "gross_margin",
    "ebitda_margin": "ebitda_margin",
    "roic": "roic",
    "revenue_cagr_5y": "cagr_revenue_5y",
    "earnings_cagr_5y": "cagr_earnings_5y",
}
"""`ProviderFundamentals` field -> bolsai key.

bolsai already emits percentages (`roe: 28.26`, not `0.2826`), which is the same
convention `shared.indicators.arithmetic` uses — so nothing needs rescaling here.

`dividend_yield` is absent on purpose: it is not in `/fundamentals` despite the
docs, and `/dividends` answers 403 on the free plan. It stays `None`, which is
what leaves SLOW_GROWER unjudgeable for now.

Note also that bolsai's raw statement figures (`ebit`, `equity`, `net_income`)
are in THOUSANDS of BRL while `market_cap` and `close_price` are in units. We map
only their ready-made ratios, which are scale-invariant, so that trap does not
reach us — but anything derived from the raw figures later must account for it.
"""


class BolsaiProvider:
    """Fetches B3 fundamentals from usebolsai.com.

    Conforms to `FundamentalsProvider` structurally. No base class, no import of
    the Protocol.
    """

    def __init__(
        self,
        client: httpx.Client,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> ProviderName:
        return ProviderName.BOLSAI

    def fetch_fundamentals(self, ticker: str) -> ProviderFundamentals:
        symbol = ticker.strip().upper()
        try:
            response = self._client.get(
                f"{self._base_url}/fundamentals/{symbol}",
                headers={API_KEY_HEADER: self._api_key},
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"bolsai request failed for {symbol}: {exc}") from exc

        self._raise_for_status(symbol, response)

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise MalformedResponseError(f"bolsai returned non-JSON for {symbol}") from exc

        return self._map(symbol, payload)

    def _raise_for_status(self, symbol: str, response: httpx.Response) -> None:
        """Translate HTTP status into our own vocabulary.

        401 and 403 are deliberately different: a bad key means every remaining
        ticker will fail too, while 403 ("Pro tier required") means the key is
        fine and only this feature is gated.
        """
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise AuthenticationError(f"bolsai rejected our API key for {symbol}")
        if response.status_code == httpx.codes.FORBIDDEN:
            raise FeatureUnavailableError(f"bolsai plan does not cover this endpoint for {symbol}")
        if response.status_code == httpx.codes.NOT_FOUND:
            raise TickerNotFoundError(f"bolsai does not know ticker {symbol}")
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise ProviderUnavailableError(
                f"bolsai daily quota exhausted (200/day, resets midnight UTC) at {symbol}"
            )
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise ProviderUnavailableError(f"bolsai returned {response.status_code} for {symbol}")
        if response.status_code != httpx.codes.OK:
            raise MalformedResponseError(f"bolsai returned {response.status_code} for {symbol}")

    def _map(self, symbol: str, payload: Any) -> ProviderFundamentals:
        """Translate bolsai's wire format into our own. The only place that knows it."""
        if not isinstance(payload, dict):
            raise MalformedResponseError(f"bolsai payload for {symbol} is not an object")

        reference_date = to_date(payload.get(REFERENCE_DATE_KEY))
        if reference_date is None:
            raise MalformedResponseError(
                f"bolsai returned no usable {REFERENCE_DATE_KEY} for {symbol}"
            )

        indicators = {
            field: to_ratio(payload.get(key)) for field, key in FUNDAMENTALS_FIELD_MAP.items()
        }
        return ProviderFundamentals.model_validate(
            {
                "ticker": payload.get("ticker") or symbol,
                "reference_date": reference_date,
                **indicators,
            }
        )

    @staticmethod
    def remaining_quota(response: httpx.Response) -> int | None:
        """Requests left today, if bolsai reported it. `None` when absent."""
        raw = response.headers.get(RATE_LIMIT_HEADER)
        try:
            return None if raw is None else int(raw)
        except ValueError:
            return None
