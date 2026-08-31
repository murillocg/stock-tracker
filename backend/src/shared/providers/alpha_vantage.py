"""Alpha Vantage — US quotes and fundamentals.

The first provider that serves BOTH capabilities: `GLOBAL_QUOTE` for the daily
price, `OVERVIEW` for the statement indicators. It therefore satisfies
`QuoteProvider` and `FundamentalsProvider` at once, with no change to either
Protocol — the case for keeping them separate rather than merging them.

Free plan is 25 requests/day, and we spend 2 per stock, so this caps US holdings
at roughly a dozen. That is the binding constraint, not rate per second.
"""

from decimal import Decimal
from typing import Any

import httpx

from shared.models import ProviderName
from shared.providers.errors import (
    AuthenticationError,
    MalformedResponseError,
    ProviderUnavailableError,
    TickerNotFoundError,
)
from shared.providers.fundamentals import ProviderFundamentals
from shared.providers.parsing import to_date, to_decimal, to_ratio
from shared.providers.quote import ProviderQuote

DEFAULT_BASE_URL = "https://www.alphavantage.co/query"

PRICE_KEY = "05. price"
QUOTE_ENVELOPE = "Global Quote"
"""GLOBAL_QUOTE nests everything under this key, with numbered sub-keys
("01. symbol", "05. price"). Ugly, but stable across years of the API."""

RATIO_FIELDS: dict[str, str] = {
    "pe": "PERatio",
    "pb": "PriceToBookRatio",
    "ev_ebitda": "EVToEBITDA",
}
"""Already plain ratios upstream — stored as-is."""

FRACTION_FIELDS: dict[str, str] = {
    "roe": "ReturnOnEquityTTM",
    "dividend_yield": "DividendYield",
    "payout_ratio": "PayoutRatio",
}
"""Returned as FRACTIONS and multiplied by 100 on the way in.

Alpha Vantage sends ROE as 0.35 and dividend yield as 0.0072, while our own
indicators and bolsai both speak percentages. Storing them unscaled would put two
different scales in one column and quietly break every category ruleset — a P/E
band would work and an ROE band would not, in a way nothing would flag.

No margins are mapped. `GrossProfitTTM` is an absolute dollar figure, not a
ratio, and `OperatingMarginTTM` is EBIT-based where our field is EBITDA-based —
they differ by depreciation. Same rule as the CAGRs: a field named for one
measure must not be fed another.
"""


def _percent(value: Decimal | None) -> Decimal | None:
    return None if value is None else to_ratio(value * 100)


def raise_for_body(symbol: str, payload: dict[str, Any]) -> None:
    """Translate Alpha Vantage's in-body errors into our vocabulary.

    Module-level rather than a private method on the provider because the seeding
    script needs exactly this too, and the version it grew on its own missed the
    rate-limit envelope — reporting an exhausted quota as "unknown ticker", which
    is the one conclusion that sends you off checking a symbol that was fine.
    """
    if "Error Message" in payload:
        raise TickerNotFoundError(f"Alpha Vantage rejected {symbol}: {payload['Error Message']}")

    # "Note" is the classic rate-limit envelope; "Information" is what the
    # newer free tier uses for both quota exhaustion and an invalid key.
    for key in ("Note", "Information"):
        message = payload.get(key)
        if not isinstance(message, str):
            continue
        lowered = message.lower()
        # Alpha Vantage writes it both ways depending on the endpoint.
        if ("apikey" in lowered or "api key" in lowered) and "invalid" in lowered:
            raise AuthenticationError(f"Alpha Vantage rejected our API key: {message}")
        raise ProviderUnavailableError(f"Alpha Vantage limit hit for {symbol}: {message}")


class AlphaVantageProvider:
    """US quotes and fundamentals. Satisfies both provider Protocols."""

    def __init__(
        self,
        client: httpx.Client,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url

    @property
    def name(self) -> ProviderName:
        return ProviderName.ALPHA_VANTAGE

    def fetch_quote(self, ticker: str) -> ProviderQuote:
        symbol = ticker.strip().upper()
        payload = self._call("GLOBAL_QUOTE", symbol)

        quote = payload.get(QUOTE_ENVELOPE)
        if not isinstance(quote, dict) or not quote:
            raise TickerNotFoundError(f"Alpha Vantage has no quote for {symbol}")

        price = to_decimal(quote.get(PRICE_KEY))
        if price is None or price <= 0:
            raise MalformedResponseError(f"Alpha Vantage returned no usable price for {symbol}")

        return ProviderQuote(ticker=symbol, price=price)

    def fetch_fundamentals(self, ticker: str) -> ProviderFundamentals:
        symbol = ticker.strip().upper()
        payload = self._call("OVERVIEW", symbol)

        # OVERVIEW answers an unknown symbol with an empty object rather than an
        # error, so emptiness is the "not found" signal.
        if not payload.get("Symbol"):
            raise TickerNotFoundError(f"Alpha Vantage has no fundamentals for {symbol}")

        reference_date = to_date(payload.get("LatestQuarter"))
        if reference_date is None:
            raise MalformedResponseError(f"Alpha Vantage gave no LatestQuarter for {symbol}")

        values: dict[str, Any] = {"ticker": symbol, "reference_date": reference_date}
        values.update({field: to_ratio(payload.get(key)) for field, key in RATIO_FIELDS.items()})
        values.update(
            {
                field: _percent(to_decimal(payload.get(key)))
                for field, key in FRACTION_FIELDS.items()
            }
        )
        # `roic`, `net_debt_to_ebitda` and the 5-year CAGRs have no OVERVIEW
        # equivalent. OVERVIEW does carry QuarterlyEarningsGrowthYOY, but writing a
        # quarterly year-over-year figure into a field named `earnings_cagr_5y`
        # would be a lie, and PEG's meaning depends on which measure feeds it.
        return ProviderFundamentals.model_validate(values)

    def _call(self, function: str, symbol: str) -> dict[str, Any]:
        """One request, with Alpha Vantage's unusual error conventions handled.

        The trap: rate limits and bad keys come back as **HTTP 200** with an
        explanatory string in the body. Checking `response.status_code` alone
        would treat "you have exceeded your quota" as a successful empty result,
        and the collector would record a puzzling MalformedResponseError instead
        of a retryable one.
        """
        try:
            response = self._client.get(
                self._base_url,
                params={"function": function, "symbol": symbol, "apikey": self._api_key},
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                f"Alpha Vantage request failed for {symbol}: {exc}"
            ) from exc

        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise ProviderUnavailableError(
                f"Alpha Vantage returned {response.status_code} for {symbol}"
            )
        if response.status_code != httpx.codes.OK:
            raise MalformedResponseError(
                f"Alpha Vantage returned {response.status_code} for {symbol}"
            )

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise MalformedResponseError(f"Alpha Vantage returned non-JSON for {symbol}") from exc

        if not isinstance(payload, dict):
            raise MalformedResponseError(f"Alpha Vantage payload for {symbol} is not an object")

        raise_for_body(symbol, payload)
        return payload
