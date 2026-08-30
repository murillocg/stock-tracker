"""Banco Central do Brasil — the USD/BRL rate.

Free, official, no key, no quota. brapi serves rates too, but behind the same
Pro plan as its fundamentals, so this is the only source that actually works
here — and CLAUDE.md names it as the alternative for exactly that reason.
"""

from typing import Any

import httpx

from shared.models import ProviderName
from shared.providers.errors import (
    MalformedResponseError,
    ProviderUnavailableError,
    TickerNotFoundError,
)
from shared.providers.parsing import to_decimal
from shared.providers.quote import ProviderQuote

DEFAULT_BASE_URL = "https://api.bcb.gov.br/dados/serie"

SERIES = {"USDBRL": 1}
"""Ticker -> SGS series. Series 1 is the daily PTAX dollar selling rate.

Only the pair we need. Adding EURBRL would be one line (series 21), but an
unused mapping is a lookup that can only ever return nothing.
"""


class BancoCentralProvider:
    """Exchange rates from the Brazilian central bank. Conforms to `QuoteProvider`."""

    def __init__(self, client: httpx.Client, base_url: str = DEFAULT_BASE_URL) -> None:
        """No credential: the SGS series are open data."""
        self._client = client
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> ProviderName:
        return ProviderName.BANCO_CENTRAL

    def fetch_quote(self, ticker: str) -> ProviderQuote:
        symbol = ticker.strip().upper()
        series = SERIES.get(symbol)
        if series is None:
            raise TickerNotFoundError(
                f"Banco Central serves exchange rates, not {symbol}. "
                f"Known: {', '.join(sorted(SERIES))}."
            )

        try:
            response = self._client.get(
                f"{self._base_url}/bcdata.sgs.{series}/dados/ultimos/1",
                params={"formato": "json"},
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"BCB request failed for {symbol}: {exc}") from exc

        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise ProviderUnavailableError(f"BCB returned {response.status_code} for {symbol}")
        if response.status_code != httpx.codes.OK:
            raise MalformedResponseError(f"BCB returned {response.status_code} for {symbol}")

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise MalformedResponseError(f"BCB returned non-JSON for {symbol}") from exc

        return self._map(symbol, payload)

    def _map(self, symbol: str, payload: Any) -> ProviderQuote:
        """`[{"data": "28/08/2026", "valor": "5.2005"}]` — the whole format.

        The date is deliberately ignored: the series only moves on business days,
        so a Monday collection legitimately reads Friday's rate. Which trading day
        the snapshot belongs to is the collector's decision, not the source's.
        """
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            raise MalformedResponseError(f"BCB returned no series for {symbol}")

        rate = to_decimal(payload[0].get("valor"))
        if rate is None or rate <= 0:
            raise MalformedResponseError(f"BCB returned no usable rate for {symbol}")

        return ProviderQuote(ticker=symbol, price=rate)
