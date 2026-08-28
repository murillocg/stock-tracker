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
    """The provider rejected our credentials (401/403).

    Run-level, not ticker-level. Every other ticker will fail identically with
    the same token, so the collector aborts rather than spending twenty calls and
    twenty delays to learn the same thing twenty times.
    """


class MalformedResponseError(ProviderError):
    """The API answered 200 with a body we cannot map to a `ProviderQuote`."""
