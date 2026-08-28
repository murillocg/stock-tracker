"""Provider wiring."""

import httpx
import pytest

from shared.config import Config
from shared.models import ProviderName
from shared.providers import BrapiProvider, UnsupportedProviderError, build_registry, get_provider


def test_the_registry_serves_brapi(config: Config) -> None:
    with httpx.Client() as client:
        registry = build_registry(client, config)

    assert isinstance(get_provider(registry, ProviderName.BRAPI), BrapiProvider)


@pytest.mark.parametrize("name", [ProviderName.BOLSAI, ProviderName.ALPHA_VANTAGE])
def test_an_unimplemented_provider_fails_loudly(config: Config, name: ProviderName) -> None:
    """Phase 0 is a single slice through brapi; the rest must not fail silently."""
    with httpx.Client() as client:
        registry = build_registry(client, config)

    with pytest.raises(UnsupportedProviderError):
        get_provider(registry, name)
