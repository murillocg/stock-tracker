"""The value a fundamentals provider returns: statement-derived indicators."""

import datetime as dt
from decimal import Decimal

from shared.models import FetchedIndicators
from shared.models.types import Ticker


class ProviderFundamentals(FetchedIndicators):
    """Indicators computed from the financial statements.

    Separate from `ProviderQuote` because the two move on different clocks: a
    price changes every day, these change only when earnings are released. Both
    build on `FetchedIndicators`, so the shared fields are declared once.

    `roic` and the two CAGRs sit here rather than in `FetchedIndicators` because
    our own COMPUTE step can also produce them — bolsai just happens to supply
    them ready-made, and `shared.indicators.roic()` reproduces their figure
    exactly from the same statements.
    """

    ticker: Ticker
    reference_date: dt.date
    """Required here, unlike on a snapshot: fundamentals without a statement date
    cannot be compared against the previous quarter, so they are not usable."""

    roic: Decimal | None = None
    revenue_cagr_5y: Decimal | None = None
    earnings_cagr_5y: Decimal | None = None
