"""The `Stocks` table: the registry and current state of everything I follow."""

from pydantic import Field

from shared.models.alert_rule import AlertRule
from shared.models.base import CamelModel
from shared.models.enums import AlertType, Currency, ListType, LynchCategory, Market, ProviderName
from shared.models.snapshot import DailySnapshot
from shared.models.types import Ticker


class Stock(CamelModel):
    """One tracked stock. PK=`ticker`, GSI `listType` -> `ticker`."""

    ticker: Ticker
    name: str
    market: Market
    currency: Currency
    quote_provider: ProviderName
    """Which API supplies the daily price. B3 and US differ."""

    fundamentals_provider: ProviderName | None = None
    """Which API supplies the statement indicators, if any.

    Optional and separate from `quote_provider` because no single free source
    covers both: brapi has prices and no fundamentals, bolsai the reverse. `None`
    means price-only collection — correct for the `USDBRL` FX rate, and for US
    tickers until that provider exists.
    """

    sector: str | None = None
    category: LynchCategory | None = None
    """Set by hand. `None` means "not classified yet", so no ruleset applies."""

    list_type: ListType
    alert_rules: dict[AlertType, AlertRule] = Field(default_factory=dict)

    current: DailySnapshot | None = None
    """Latest snapshot, denormalised onto the registry item.

    Duplicated storage bought deliberately: rendering the whole portfolio becomes
    one GSI query instead of one query plus N reads against `DailySnapshots`.
    """
