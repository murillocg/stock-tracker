"""The abstraction over upstream market-data APIs."""

from typing import Protocol, runtime_checkable

from shared.models import ProviderName
from shared.providers.quote import ProviderQuote


@runtime_checkable
class QuoteProvider(Protocol):
    """Structural contract for the collector's FETCH step.

    A `Protocol`, not an ABC: implementations do **not** inherit from this and do
    not import it. `BrapiProvider` conforms simply by having a matching shape, so
    the concrete classes stay free of any coupling to the abstraction. mypy checks
    the conformance statically, at the point where a provider is passed to
    something expecting a `QuoteProvider`.
    """

    @property
    def name(self) -> ProviderName:
        """Which `ProviderName` this implementation serves.

        Declared as a read-only property so a plain instance attribute
        (`self.name = ...`) also satisfies it.
        """
        ...

    def fetch_quote(self, ticker: str) -> ProviderQuote:
        """Fetch the current price and ready-made indicators for one ticker.

        Raises:
            TickerNotFoundError: the ticker is unknown upstream; skip it.
            ProviderUnavailableError: transport failure, 5xx or rate limit.
            MalformedResponseError: 200 with a body we cannot map.
        """
        ...
