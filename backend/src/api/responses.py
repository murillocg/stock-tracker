"""What the read API returns. Pydantic at the boundary, as everywhere else."""

import datetime as dt
from decimal import Decimal
from typing import Any

from pydantic import Field

from shared.categories import Evaluation
from shared.categories.entry import EntryPrice
from shared.models import (
    CamelModel,
    Currency,
    DailySnapshot,
    ListType,
    LynchCategory,
    Market,
    Stock,
)
from shared.models.types import Ticker
from shared.positions import BrokerLedger, Position, Valuation


class StockView(CamelModel):
    """One stock as the frontend sees it: registry, latest snapshot, verdict.

    The evaluation is computed here rather than in Vue. The rulesets are tested
    Python and the thresholds are an investment thesis — duplicating either in
    TypeScript would mean two versions that drift.
    """

    ticker: Ticker
    name: str
    market: Market
    currency: Currency
    sector: str | None
    category: LynchCategory | None
    list_type: ListType
    is_foreign: bool
    """Groups the list into Brazilian and international. Comes from the business,
    not the listing, so the BDRs sit with the companies they track."""

    current: DailySnapshot | None
    evaluation: Evaluation

    position: Position | None = None
    """What you hold, folded from the transaction ledger. `None` for a stock with
    no trades recorded — the five Avenue holdings, until that import exists."""

    valuation: Valuation | None = None
    """Today's worth and the portfolio weight. `None` without a position, since
    there is nothing to price."""

    @classmethod
    def of(
        cls,
        stock: Stock,
        evaluation: Evaluation,
        position: Position | None = None,
        valuation: Valuation | None = None,
    ) -> "StockView":
        return cls(
            ticker=stock.ticker,
            name=stock.name,
            market=stock.market,
            currency=stock.currency,
            sector=stock.sector,
            category=stock.category,
            list_type=stock.list_type,
            is_foreign=stock.is_foreign,
            current=stock.current,
            evaluation=evaluation,
            position=position,
            valuation=valuation,
        )


class PriceRange(CamelModel):
    """Where the price sits inside its own last year."""

    low: Decimal
    high: Decimal
    position: Decimal
    """0 at the 52-week low, 100 at the high. Context the raw price cannot give:
    R$ 17,72 means nothing until you know the year ran 16,61 to 27,13."""


class WatchlistItem(CamelModel):
    """One stock you do not own, described for the only question that matters.

    Deliberately not a `StockView`. That type carries position, valuation and
    weight — four fields that are structurally empty here, because you hold none
    of it. Reusing it would have meant a screen full of dashes and no room for
    the entry price.
    """

    ticker: Ticker
    name: str
    market: Market
    currency: Currency
    sector: str | None
    category: LynchCategory | None
    is_foreign: bool
    current: DailySnapshot | None
    evaluation: Evaluation

    entry: EntryPrice
    """Where this stock's own rules would turn green."""

    fair_value: Decimal | None = None
    fair_value_source: str | None = None
    fair_value_on: dt.date | None = None
    """A valuation from outside the app, shown beside the derived ceiling rather
    than blended with it. The two are produced by incompatible methods and their
    disagreement is the informative part."""

    range_52w: PriceRange | None = Field(default=None, alias="range52w")
    """`None` until there is a year of history behind it.

    The alias is explicit because `to_camel` renders this as `range52W` — it
    capitalises the segment after a digit. The same trap `change1w` hit."""


class PortfolioTotals(CamelModel):
    """The portfolio as a whole, so the frontend does not re-add the parts."""

    invested: Decimal
    market_value: Decimal
    unrealised_gain: Decimal
    unrealised_gain_percent: Decimal
    currency: Currency
    """Everything above is in this one currency. Holdings priced in another are
    excluded from the totals and carry no weight — see `Valuation.weight`."""

    priced: int
    unpriced: int
    """How many holdings are in, and how many were left out for want of a rate."""


class CollectionStatus(CamelModel):
    """When the data was last refreshed, and when it will be next.

    On the main screen because the single most useful thing to know before acting
    on any of these numbers is how old they are.
    """

    last_run: dt.datetime | None
    """When the collector last actually ran. `None` for data written before runs
    were stamped, in which case `lastCollected` is all there is."""

    last_collected: dt.date | None
    """The freshest trading day in the portfolio. Not the same as `lastRun`: a run
    that fails every ticker leaves this untouched, which is precisely the gap
    worth seeing."""

    history_since: dt.date | None = None
    """Oldest day we hold a price for. `None` before anything is collected.

    Lets the screen distinguish "not due yet" from "missing": three days after
    collection began, a one-month change is not a gap in the data, and a bare
    dash cannot say which it is.
    """

    next_run: dt.datetime | None
    """`None` when the schedule is not one this code can read — better silent
    than wrong, since the whole point is knowing if a refresh is imminent."""

    timezone: str


class WatchlistResponse(CamelModel):
    """GET /stocks?listType=WATCHLIST — no totals, because nothing is owned."""

    stocks: list[WatchlistItem]
    collection: CollectionStatus | None = None


class StockListResponse(CamelModel):
    """GET /stocks — one list, already judged and weighted."""

    stocks: list[StockView]
    totals: PortfolioTotals | None = None
    collection: CollectionStatus | None = None


class StockDetailResponse(CamelModel):
    """GET /stocks/{ticker} — the stock, its price history, and its ledger."""

    stock: StockView
    history: list[DailySnapshot]

    ledgers: list[BrokerLedger] = Field(default_factory=list)
    """Transactions grouped by custodian, each with its own running average.

    Grouped rather than flat because this is what the tax return asks for: Bens e
    Direitos takes one entry per institution, with that institution's own
    quantity and average cost. The blended figure at the top of the page is the
    portfolio answer; these are the fiscal one."""


class ErrorResponse(CamelModel):
    message: str


def json_response(status: int, body: CamelModel) -> dict[str, Any]:
    """Wrap a model in the shape API Gateway expects.

    `mode="json"` renders `Decimal` as a **string**, not a float, and that is
    deliberate: JavaScript numbers are float64, so parsing 4.2084 into one would
    reintroduce exactly the precision problem `Decimal` exists to avoid. The Vue
    app can display the string directly and parse only where it needs to compute.
    """
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": body.model_dump_json(by_alias=True, exclude_none=False),
    }


def error(status: int, message: str) -> dict[str, Any]:
    return json_response(status, ErrorResponse(message=message))
