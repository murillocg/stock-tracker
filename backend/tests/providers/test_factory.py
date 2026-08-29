"""Provider wiring."""

import httpx
import pytest

from shared.config import Config
from shared.models import ProviderName
from shared.providers import (
    BrapiProvider,
    UnsupportedProviderError,
    build_quote_registry,
    get_provider,
)


def test_the_registry_serves_brapi(config: Config) -> None:
    with httpx.Client() as client:
        registry = build_quote_registry(client, config)

    assert isinstance(get_provider(registry, ProviderName.BRAPI), BrapiProvider)


def test_a_provider_absent_from_a_registry_fails_loudly(config: Config) -> None:
    """bolsai serves fundamentals only — asking it for a quote must not be silent.

    Its `/fundamentals` does carry a close_price, but it is the quarter-end close,
    not today's, so it deliberately has no place in the quote registry.
    """
    name = ProviderName.BOLSAI
    with httpx.Client() as client:
        registry = build_quote_registry(client, config)

    with pytest.raises(UnsupportedProviderError):
        get_provider(registry, name)
