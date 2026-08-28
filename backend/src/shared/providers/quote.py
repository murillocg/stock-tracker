"""The value a provider returns: the outcome of the collector's FETCH step."""

from decimal import Decimal

from pydantic import Field

from shared.models import FetchedIndicators
from shared.models.types import Ticker


class ProviderQuote(FetchedIndicators):
    """A price plus whatever ready-made indicators the upstream API supplied.

    Deliberately *not* a `DailySnapshot`: it carries no computed fields and no
    date. The collector is what turns quotes into snapshots, once COMPUTE has run.
    """

    ticker: Ticker
    price: Decimal = Field(gt=0)
