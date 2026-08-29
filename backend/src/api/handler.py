"""Lambda 2: read endpoints behind API Gateway, serving the Vue app.

Read-only by design. Nothing here writes: the collector owns every mutation, so
a bug in the API cannot corrupt the time series.

    GET /stocks?listType=PORTFOLIO   list + latest snapshot + verdict
    GET /stocks/{ticker}?days=90     one stock + history for the chart

Routing is a handful of `if` statements rather than a framework. Two routes do
not justify a dependency in the layer, and every import costs cold-start time on
a Lambda that is only awake while someone has the page open.
"""

import datetime as dt
import logging
from typing import Any

import boto3

from api.responses import (
    StockDetailResponse,
    StockListResponse,
    StockView,
    error,
    json_response,
)
from shared.categories import evaluate
from shared.config import Config
from shared.models import ListType
from shared.repository import (
    DynamoDbSnapshotRepository,
    DynamoDbStockRepository,
    SnapshotRepository,
    StockRepository,
)

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_DAYS = 90
MAX_HISTORY_DAYS = 400
"""Caps the range query. 400 covers the widest change window with margin, and
stops a crafted `?days=99999` from scanning a ticker's entire history."""


def list_stocks(stocks: StockRepository, raw_list_type: str | None) -> dict[str, Any]:
    """Portfolio or watchlist, each stock already evaluated."""
    if raw_list_type is None:
        found = [
            *stocks.list_by_type(ListType.PORTFOLIO),
            *stocks.list_by_type(ListType.WATCHLIST),
        ]
    else:
        try:
            list_type = ListType(raw_list_type.strip().upper())
        except ValueError:
            allowed = ", ".join(member.value for member in ListType)
            return error(400, f"Unknown listType '{raw_list_type}'. Expected one of: {allowed}.")
        found = stocks.list_by_type(list_type)

    views = [
        StockView.of(stock, evaluate(stock)) for stock in sorted(found, key=lambda s: s.ticker)
    ]
    return json_response(200, StockListResponse(stocks=views))


def get_stock(
    stocks: StockRepository,
    snapshots: SnapshotRepository,
    ticker: str,
    raw_days: str | None,
) -> dict[str, Any]:
    """One stock plus its recent history, for the change chart."""
    stock = stocks.get(ticker)
    if stock is None:
        return error(404, f"{ticker.strip().upper()} is not in the registry.")

    try:
        days = DEFAULT_HISTORY_DAYS if raw_days is None else int(raw_days)
    except ValueError:
        return error(400, f"days must be a whole number, got '{raw_days}'.")
    days = max(1, min(days, MAX_HISTORY_DAYS))

    today = dt.date.today()
    history = snapshots.history(stock.ticker, since=today - dt.timedelta(days=days), until=today)

    return json_response(
        200,
        StockDetailResponse(
            stock=StockView.of(stock, evaluate(stock)),
            history=history,
        ),
    )


def route(
    event: dict[str, Any],
    stocks: StockRepository,
    snapshots: SnapshotRepository,
) -> dict[str, Any]:
    """Dispatch on API Gateway's `routeKey`, e.g. `GET /stocks/{ticker}`.

    Taking the routeKey rather than parsing the raw path means the URL shape is
    declared once, in Terraform, and the handler cannot silently disagree with it.
    """
    route_key = event.get("routeKey", "")
    params: dict[str, str] = event.get("queryStringParameters") or {}
    path: dict[str, str] = event.get("pathParameters") or {}

    if route_key == "GET /stocks":
        return list_stocks(stocks, params.get("listType"))

    if route_key == "GET /stocks/{ticker}":
        ticker = path.get("ticker", "")
        if not ticker:
            return error(400, "Missing ticker in the path.")
        return get_stock(stocks, snapshots, ticker, params.get("days"))

    return error(404, f"No route for '{route_key}'.")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS entry point. Wiring and error containment only.

    Unlike the collector, this Lambda is user-facing: an unhandled exception
    would surface as an opaque API Gateway 502. Catching it here means the Vue
    app gets a JSON error it can render, and the stack trace lands in CloudWatch
    where it belongs rather than in front of a browser.
    """
    config = Config.from_env()
    dynamodb = boto3.resource("dynamodb", region_name=config.aws_region)

    try:
        return route(
            event,
            DynamoDbStockRepository(dynamodb.Table(config.stocks_table)),
            DynamoDbSnapshotRepository(dynamodb.Table(config.snapshots_table)),
        )
    except Exception:
        logger.exception("Unhandled error serving %s", event.get("routeKey"))
        return error(500, "Something went wrong. Check the logs.")
