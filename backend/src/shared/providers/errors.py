"""Provider failures, normalised so callers never catch `httpx` exceptions."""


class ProviderError(RuntimeError):
    """Base for anything that went wrong talking to an upstream API."""


class TickerNotFoundError(ProviderError):
    """The upstream API answered, but does not know this ticker.

    Distinct from a transport failure: retrying will not help, and the collector
    should skip the ticker rather than abort the run.
    """


class ProviderUnavailableError(ProviderError):
    """Transport failure, 5xx, or a rate limit. Retrying later may succeed."""


class AuthenticationError(ProviderError):
    """The provider rejected our credentials (401).

    Run-level, not ticker-level. Every other ticker will fail identically with
    the same token, so the collector aborts rather than spending twenty calls and
    twenty delays to learn the same thing twenty times.
    """


class FeatureUnavailableError(ProviderError):
    """Our plan does not include what we asked for (403).

    Distinct from `AuthenticationError` on the evidence: both free tiers answer
    403 for paid features while the credentials are perfectly valid — brapi with
    `MODULES_NOT_AVAILABLE`, bolsai with `Pro tier required`. Aborting the run
    over one gated endpoint would be wrong, so this is recorded and skipped.
    """


class MalformedResponseError(ProviderError):
    """The API answered 200 with a body we cannot map to a `ProviderQuote`."""
