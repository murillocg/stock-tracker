"""Wiring: `ProviderName` -> a concrete `QuoteProvider`."""

import httpx

from shared.config import Config
from shared.models import ProviderName
from shared.providers.brapi import BrapiProvider
from shared.providers.errors import ProviderError
from shared.providers.protocol import QuoteProvider


class UnsupportedProviderError(ProviderError):
    """A stock is registered against a provider we have not implemented yet."""


def build_registry(client: httpx.Client, config: Config) -> dict[ProviderName, QuoteProvider]:
    """Build every provider we can serve, sharing one http client between them.

    The annotated return type is where the Protocol earns its keep: mypy checks
    here that `BrapiProvider` structurally matches `QuoteProvider`. Get the
    signature wrong and this line fails to type-check — even though the two
    classes have no inheritance relationship at all.

    BOLSAI and ALPHA_VANTAGE are intentionally absent: Phase 0 is a single
    vertical slice through brapi. Registering a stock against them raises a clear
    error rather than silently returning nothing.
    """
    return {
        ProviderName.BRAPI: BrapiProvider(client, config.brapi_token),
    }


def get_provider(
    registry: dict[ProviderName, QuoteProvider],
    name: ProviderName,
) -> QuoteProvider:
    """Look one up, failing loudly instead of returning `None`."""
    provider = registry.get(name)
    if provider is None:
        raise UnsupportedProviderError(f"No provider implemented for {name}")
    return provider
