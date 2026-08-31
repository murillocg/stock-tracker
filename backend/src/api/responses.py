"""What the read API returns. Pydantic at the boundary, as everywhere else."""

from decimal import Decimal
from typing import Any

from pydantic import Field

from shared.categories import Evaluation
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
from shared.positions import LedgerEntry, Position, Valuation


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


class StockListResponse(CamelModel):
    """GET /stocks — one list, already judged and weighted."""

    stocks: list[StockView]
    totals: PortfolioTotals | None = None


class StockDetailResponse(CamelModel):
    """GET /stocks/{ticker} — the stock, its price history, and its ledger."""

    stock: StockView
    history: list[DailySnapshot]

    ledger: list[LedgerEntry] = Field(default_factory=list)
    """Every transaction with the position after it, oldest first.

    Sent whole rather than summarised because the average price is the one figure
    here that cannot be checked by eye — it is the output of a fold, and the only
    way to trust it is to watch it move trade by trade."""


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
