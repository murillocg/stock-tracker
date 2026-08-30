"""Closed vocabularies used across the whole application. No magic strings."""

from enum import StrEnum


class Market(StrEnum):
    """Exchange the ticker trades on."""

    B3 = "B3"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"


class Currency(StrEnum):
    BRL = "BRL"
    USD = "USD"


class ProviderName(StrEnum):
    """Which upstream API supplies the FETCH step for a given ticker."""

    BRAPI = "BRAPI"
    BOLSAI = "BOLSAI"
    ALPHA_VANTAGE = "ALPHA_VANTAGE"

    BANCO_CENTRAL = "BANCO_CENTRAL"
    """Exchange rates. Free and official, where brapi gates them behind Pro."""


class ListType(StrEnum):
    """Partition of the registry. Also the GSI partition key on the Stocks table."""

    PORTFOLIO = "PORTFOLIO"
    WATCHLIST = "WATCHLIST"

    REFERENCE = "REFERENCE"
    """Collected but not owned — the USDBRL rate, for one.

    CLAUDE.md files FX as "a special ticker USDBRL", which means it needs a
    registry row to be collected. Without a third list type it would have to
    masquerade as a holding or a watchlist entry, and would then turn up in the
    portfolio weights as though it were a position.
    """


class LynchCategory(StrEnum):
    """Peter Lynch classification. Set manually — the app never infers it.

    Each category is judged with a different ruleset, so the category decides
    which indicators matter, never a global threshold.
    """

    FAST_GROWER = "FAST_GROWER"
    STALWART = "STALWART"
    SLOW_GROWER = "SLOW_GROWER"
    CYCLICAL = "CYCLICAL"
    TURNAROUND = "TURNAROUND"
    ASSET_PLAY = "ASSET_PLAY"


class AlertType(StrEnum):
    """Why we would email the user. Both are event-driven, never daily noise."""

    PRICE_DROP = "PRICE_DROP"
    """Protection: the price fell more than `threshold` percent over the window."""

    ENTRY_POINT = "ENTRY_POINT"
    """Opportunity: a watchlist price reached or crossed below `threshold`."""
