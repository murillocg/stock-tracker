"""The abstraction over upstream market-data APIs."""

from typing import Protocol, runtime_checkable

from shared.models import ProviderName
from shared.providers.fundamentals import ProviderFundamentals
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
            AuthenticationError: credentials rejected; abort the run.
            FeatureUnavailableError: our plan does not cover this; skip it.
            MalformedResponseError: 200 with a body we cannot map.
        """
        ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    """Structural contract for statement-derived indicators.

    A second, narrow Protocol rather than more methods on `QuoteProvider`. The
    two capabilities have different cadences and different providers serve them:
    brapi has prices and no fundamentals, bolsai has fundamentals and no daily
    price. One fat interface would leave every implementation raising
    `NotImplementedError` for half its methods — the interface-segregation
    argument, and the reason CLAUDE.md asks for composition over inheritance.

    A provider that happened to do both would satisfy both Protocols at once,
    with no changes to either — structural typing needs no `implements` list.
    """

    @property
    def name(self) -> ProviderName:
        """Which `ProviderName` this implementation serves."""
        ...

    def fetch_fundamentals(self, ticker: str) -> ProviderFundamentals:
        """Fetch the latest statement-derived indicators for one ticker.

        Raises the same errors as `QuoteProvider.fetch_quote`.
        """
        ...
