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
    provider: ProviderName
    """Which API supplies this ticker's FETCH step — B3 and US differ."""

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
