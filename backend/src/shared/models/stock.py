"""The `Stocks` table: the registry and current state of everything I follow."""

import datetime as dt
from decimal import Decimal

from pydantic import Field, field_serializer

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

    uses_operating_leverage: bool = True
    """Whether net debt / EBITDA means anything for this company.

    False for banks, insurers and holding companies: their deposits and float are
    raw material, not leverage, so the ratio is arithmetic noise. BPAC11 collected
    at -6 and BBAS3 at 12.73; judging either on that number is worse than not
    judging it at all.

    Set by hand, like `category`, and for the same reason — the app must not infer
    it from a free-text sector string it does not control.
    """

    list_type: ListType
    alert_rules: dict[AlertType, AlertRule] = Field(default_factory=dict)

    manual_dividend_yield: Decimal | None = None
    manual_payout_ratio: Decimal | None = None
    manual_updated_on: dt.date | None = None
    """Figures you maintain by hand, because no free API supplies them.

    Dividend yield and payout ratio are gated behind paid plans at both brapi and
    bolsai, and scraping Status Invest is off the table. They move once a quarter
    at most, so entering them by hand is tractable — and without them SLOW_GROWER
    is a category that can never return an answer.

    `manual_updated_on` exists because hand-maintained numbers go stale silently.
    Nothing will warn you; the UI showing the date is the warning.

    A provider value always wins over these — see `slow_grower`.
    """

    current: DailySnapshot | None = None
    """Latest snapshot, denormalised onto the registry item.

    Duplicated storage bought deliberately: rendering the whole portfolio becomes
    one GSI query instead of one query plus N reads against `DailySnapshots`.
    """

    @field_serializer("manual_updated_on")
    def _serialise_manual_updated_on(self, value: dt.date | None) -> str | None:
        return None if value is None else value.isoformat()
