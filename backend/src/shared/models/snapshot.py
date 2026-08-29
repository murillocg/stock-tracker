"""The `DailySnapshots` table: one immutable row per ticker per day."""

import datetime as dt
from decimal import Decimal

from pydantic import Field, field_serializer

from shared.models.base import CamelModel
from shared.models.types import Ticker


class FetchedIndicators(CamelModel):
    """Step 1 of the collector: indicators the provider hands us ready-made.

    Every field is optional on purpose. Free tiers are partial and inconsistent —
    a missing P/B must degrade one indicator, not fail the whole collection.

    `ProviderQuote` and `DailySnapshot` both build on this, which is how the
    FETCH/COMPUTE split stays visible in the type system.
    """

    pe: Decimal | None = None
    pb: Decimal | None = None
    ev_ebitda: Decimal | None = None
    roe: Decimal | None = None
    net_debt_to_ebitda: Decimal | None = None
    dividend_yield: Decimal | None = None
    gross_margin: Decimal | None = None
    ebitda_margin: Decimal | None = None

    reference_date: dt.date | None = None
    """Statement date the fundamentals describe, e.g. 2026-06-30.

    Stored as the date rather than a `2026Q2` label because the label is lossy
    and, for US tickers, wrong: Apple's fiscal Q2 ends in March and its fiscal
    year ends in September, so a calendar-quarter mapping would disagree with
    what the company itself reports. The date is the fact; any `Q2`-style label
    is presentation, derived where it is displayed.
    """

    @field_serializer("reference_date")
    def _serialise_reference_date(self, value: dt.date | None) -> str | None:
        return None if value is None else value.isoformat()


class DailySnapshot(FetchedIndicators):
    """One day of data for one ticker. PK=`ticker`, SK=`date`.

    The FX rate rides in this same table as the special ticker `USDBRL`, where
    only `price` is populated.
    """

    ticker: Ticker
    date: dt.date
    price: Decimal = Field(gt=0)

    # --- Step 2 of the collector: derived from the financial statements. ---
    roic: Decimal | None = None
    payout_ratio: Decimal | None = None
    """No free data source supplies dividends paid, so this stays empty for now."""

    peg: Decimal | None = None

    # Named for what they actually hold. bolsai supplies 5-year CAGR, not
    # year-over-year, and PEG means something different depending on which one
    # feeds it — so the field says which. `to_camel` would give `revenueCagr5Y`,
    # hence the explicit aliases.
    revenue_cagr_5y: Decimal | None = Field(default=None, alias="revenueCagr5y")
    earnings_cagr_5y: Decimal | None = Field(default=None, alias="earningsCagr5y")

    # --- Derived from our own history in DynamoDB, as a percentage. ---
    # `to_camel` would turn `change_1w` into `change1W`, so these four spell out
    # the alias explicitly. An explicit alias always wins over the generator.
    change_1w: Decimal | None = Field(default=None, alias="change1w")
    change_1m: Decimal | None = Field(default=None, alias="change1m")
    change_6m: Decimal | None = Field(default=None, alias="change6m")
    change_1y: Decimal | None = Field(default=None, alias="change1y")

    @field_serializer("date")
    def _serialise_date(self, value: dt.date) -> str:
        """DynamoDB has no date type; the sort key is an ISO 8601 string.

        ISO 8601 sorts lexicographically in the same order it sorts
        chronologically, which is what makes `between(since, until)` range
        queries work on a plain string sort key.
        """
        return value.isoformat()
