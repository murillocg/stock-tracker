"""What the read API returns. Pydantic at the boundary, as everywhere else."""

from typing import Any

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
    current: DailySnapshot | None
    evaluation: Evaluation

    @classmethod
    def of(cls, stock: Stock, evaluation: Evaluation) -> "StockView":
        return cls(
            ticker=stock.ticker,
            name=stock.name,
            market=stock.market,
            currency=stock.currency,
            sector=stock.sector,
            category=stock.category,
            list_type=stock.list_type,
            current=stock.current,
            evaluation=evaluation,
        )


class StockListResponse(CamelModel):
    """GET /stocks — one list, already judged."""

    stocks: list[StockView]


class StockDetailResponse(CamelModel):
    """GET /stocks/{ticker} — the stock plus enough history to draw a line."""

    stock: StockView
    history: list[DailySnapshot]


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
