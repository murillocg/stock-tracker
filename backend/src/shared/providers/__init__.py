"""FETCH step: the abstraction over upstream market-data APIs, plus its wiring."""

from shared.providers.brapi import BrapiProvider
from shared.providers.errors import (
    MalformedResponseError,
    ProviderError,
    ProviderUnavailableError,
    TickerNotFoundError,
)
from shared.providers.factory import UnsupportedProviderError, build_registry, get_provider
from shared.providers.protocol import QuoteProvider
from shared.providers.quote import ProviderQuote

__all__ = [
    "BrapiProvider",
    "MalformedResponseError",
    "ProviderError",
    "ProviderQuote",
    "ProviderUnavailableError",
    "QuoteProvider",
    "TickerNotFoundError",
    "UnsupportedProviderError",
    "build_registry",
    "get_provider",
]
