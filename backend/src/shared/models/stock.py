"""The `Stocks` table: the registry and current state of everything I follow."""

import datetime as dt
from decimal import Decimal

from pydantic import Field, computed_field, field_serializer

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

    foreign_business: bool | None = None
    """Whether the COMPANY is outside Brazil — overriding what the listing implies.

    `None` means infer it from `market`, which is right for all but one case: a
    BDR is a Brazilian-listed receipt for a foreign company, so MSFT34 trades on
    the B3 while the business is Microsoft. Those need `True` explicitly.

    It cuts the other way too, which is why this is about the business and not
    the instrument. INBR32 is a BDR — same ticker shape, same B3 listing — but
    the company underneath is Banco Inter, a Brazilian bank that happens to hold
    its listing abroad. Treating "is a BDR" as "is foreign" would file it with
    Microsoft and TSMC, which is wrong about the only thing that matters here:
    where the earnings come from.
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

    fair_value: Decimal | None = None
    fair_value_source: str | None = None
    fair_value_on: dt.date | None = None
    """A valuation from outside this app — an analyst's DCF, or your own.

    Deliberately separate from the ceiling the rulesets derive, because the two
    answer different questions and can disagree by a lot. The derived ceiling is
    "the highest price at which my rules still say green"; a fair value is "what
    the business is worth". For VIVA3 in September 2026 those were R$ 83,19 and
    R$ 30,14 — a 2,8x gap, entirely explained by the growth assumption behind
    each: PEG projects the trailing 33% CAGR forward, while the DCF decays growth
    to 2,5% in perpetuity.

    Recording it does not override anything. It sits beside the derived figure so
    the disagreement is visible, which is the only honest way to show two numbers
    that were produced by incompatible methods.

    `fair_value_on` is not optional in spirit: a target price with no date is a
    number with no shelf life, and the screen shows the date so the staleness is
    yours to judge.
    """

    current: DailySnapshot | None = None
    """Latest snapshot, denormalised onto the registry item.

    Duplicated storage bought deliberately: rendering the whole portfolio becomes
    one GSI query instead of one query plus N reads against `DailySnapshots`.
    """

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_foreign(self) -> bool:
        """Where the business is, for grouping the portfolio.

        Computed rather than stored so the 20 ordinary holdings need no data at
        all — only the handful whose listing misrepresents them carry a value.
        """
        if self.foreign_business is not None:
            return self.foreign_business
        return self.market is not Market.B3

    @field_serializer("fair_value_on")
    def _serialise_fair_value_on(self, value: dt.date | None) -> str | None:
        return None if value is None else value.isoformat()

    @field_serializer("manual_updated_on")
    def _serialise_manual_updated_on(self, value: dt.date | None) -> str | None:
        return None if value is None else value.isoformat()
