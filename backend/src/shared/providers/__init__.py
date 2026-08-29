"""FETCH step: the abstractions over upstream market data, plus their wiring.

Two narrow capabilities, deliberately not merged into one interface:

- `QuoteProvider`        -> daily price (brapi)
- `FundamentalsProvider` -> statement indicators (bolsai)
"""

from shared.providers.alpha_vantage import AlphaVantageProvider
from shared.providers.bolsai import BolsaiProvider
from shared.providers.brapi import BrapiProvider
from shared.providers.errors import (
    AuthenticationError,
    FeatureUnavailableError,
    MalformedResponseError,
    ProviderError,
    ProviderUnavailableError,
    TickerNotFoundError,
)
from shared.providers.factory import (
    UnsupportedProviderError,
    build_fundamentals_registry,
    build_quote_registry,
    get_provider,
)
from shared.providers.fundamentals import ProviderFundamentals
from shared.providers.protocol import FundamentalsProvider, QuoteProvider
from shared.providers.quote import ProviderQuote

__all__ = [
    "AlphaVantageProvider",
    "AuthenticationError",
    "BolsaiProvider",
    "BrapiProvider",
    "FeatureUnavailableError",
    "FundamentalsProvider",
    "MalformedResponseError",
    "ProviderError",
    "ProviderFundamentals",
    "ProviderQuote",
    "ProviderUnavailableError",
    "QuoteProvider",
    "TickerNotFoundError",
    "UnsupportedProviderError",
    "build_fundamentals_registry",
    "build_quote_registry",
    "get_provider",
]
