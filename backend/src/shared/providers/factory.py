"""Wiring: `ProviderName` -> a concrete provider, for each capability."""

from collections.abc import Mapping

import httpx

from shared.config import Config
from shared.models import ProviderName
from shared.providers.alpha_vantage import AlphaVantageProvider
from shared.providers.banco_central import BancoCentralProvider
from shared.providers.bolsai import BolsaiProvider
from shared.providers.brapi import BrapiProvider
from shared.providers.errors import ProviderError
from shared.providers.protocol import FundamentalsProvider, QuoteProvider


class UnsupportedProviderError(ProviderError):
    """A stock is registered against a provider we have not implemented yet."""


def build_quote_registry(client: httpx.Client, config: Config) -> dict[ProviderName, QuoteProvider]:
    """Providers that can supply a daily price, sharing one http client.

    The annotated return type is where the Protocol earns its keep: mypy checks
    here that `BrapiProvider` structurally matches `QuoteProvider`. Get the
    signature wrong and this line fails to type-check — even though the two
    classes have no inheritance relationship at all.

    bolsai is absent by design: `/fundamentals` carries a `close_price`, but it
    is the quarter-end close, not today's. Prices come from brapi.
    """
    return {
        ProviderName.BRAPI: BrapiProvider(client, config.brapi_token),
        ProviderName.ALPHA_VANTAGE: AlphaVantageProvider(client, config.alpha_vantage_api_key),
        ProviderName.BANCO_CENTRAL: BancoCentralProvider(client),
    }


def build_fundamentals_registry(
    client: httpx.Client, config: Config
) -> dict[ProviderName, FundamentalsProvider]:
    """Providers that can supply statement-derived indicators.

    brapi is absent: its fundamentals live behind the R$139,99/mo Pro plan.

    Note AlphaVantageProvider appears in BOTH registries — the same instance
    satisfies `QuoteProvider` and `FundamentalsProvider`. Structural typing needs
    no `implements` list, so one class covering two capabilities costs nothing.
    """
    return {
        ProviderName.BOLSAI: BolsaiProvider(client, config.bolsai_api_key),
        ProviderName.ALPHA_VANTAGE: AlphaVantageProvider(client, config.alpha_vantage_api_key),
    }


def get_provider[P](registry: Mapping[ProviderName, P], name: ProviderName) -> P:
    """Look one up, failing loudly instead of returning `None`.

    Generic in the provider type, so the same function serves both registries and
    the caller gets back a `QuoteProvider` or a `FundamentalsProvider` rather
    than a common supertype it would have to cast. `[P]` is Python 3.12+ syntax
    for what Java writes as `<P> P getProvider(Map<ProviderName, P>, ...)`.

    Takes a `Mapping` rather than a `dict` because it only ever reads. `Mapping`
    is the read-only supertype — roughly Guava's `ImmutableMap` as a *type* — so
    any dict-like caller fits, and the signature promises we will not mutate it.
    """
    provider = registry.get(name)
    if provider is None:
        raise UnsupportedProviderError(f"No provider implemented for {name}")
    return provider
