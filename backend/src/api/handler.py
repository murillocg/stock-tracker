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
from decimal import Decimal
from typing import Any

import boto3

from api.responses import (
    PortfolioTotals,
    StockDetailResponse,
    StockListResponse,
    StockView,
    error,
    json_response,
)
from shared.categories import evaluate
from shared.config import Config
from shared.models import Currency, ListType, Stock
from shared.positions import (
    ExchangeRates,
    Valuation,
    current_position,
    running_by_broker,
    value,
    with_weights,
)
from shared.repository import (
    DynamoDbSnapshotRepository,
    DynamoDbStockRepository,
    DynamoDbTransactionRepository,
    SnapshotRepository,
    StockRepository,
    TransactionRepository,
)

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_DAYS = 90
MAX_HISTORY_DAYS = 400
"""Caps the range query. 400 covers the widest change window with margin, and
stops a crafted `?days=99999` from scanning a ticker's entire history."""


BASE_CURRENCY = Currency.BRL
"""The currency the portfolio is totalled in.

Each row keeps its own currency — MSFT stays in dollars — and only the totals and
the weights are expressed here. Holdings whose currency has no collected rate are
still excluded and counted as `unpriced`.
"""

FX_TICKER = "USDBRL"
"""The USD/BRL rate, collected daily from the Banco Central and stored as an
ordinary REFERENCE row. It is a price like any other, so it needs no special
table, no special collector path, and it gets the same history for free."""


def exchange_rates(stocks: StockRepository) -> ExchangeRates:
    """Assemble today's rates from the REFERENCE rows.

    A missing or never-collected rate yields an empty table rather than an error:
    the Brazilian side of the portfolio is most of it and must still total up if
    the FX collection fails. The USD holdings degrade to `weight=None`, exactly
    as they did before any rate existed.
    """
    fx = stocks.get(FX_TICKER)
    if fx is None or fx.current is None:
        logger.warning("%s has no snapshot — USD holdings will not be weighted", FX_TICKER)
        return ExchangeRates(base=BASE_CURRENCY)
    return ExchangeRates(base=BASE_CURRENCY, rates={Currency.USD: fx.current.price})


def build_views(
    stocks: list[Stock],
    transactions: TransactionRepository,
    rates: ExchangeRates,
) -> tuple[list[StockView], PortfolioTotals | None]:
    """Attach a position, a valuation and a weight to each stock.

    All of it server-side, like the evaluations: the rulesets and the portfolio
    maths are tested Python, and duplicating either in TypeScript would mean two
    versions that drift.
    """
    ledger: dict[str, list[Any]] = {}
    for transaction in transactions.all():
        ledger.setdefault(transaction.ticker, []).append(transaction)

    positions = {}
    valuations: dict[str, Valuation] = {}
    unpriced = 0

    for stock in stocks:
        rows = ledger.get(stock.ticker)
        if not rows:
            continue
        position = current_position(stock.ticker, rows)
        if position is None or position.quantity == 0:
            continue
        positions[stock.ticker] = position

        # A position can only be priced if we have both a price and a way to
        # express it in the base currency.
        rate = rates.rate_for(stock.currency)
        if stock.current is None or rate is None:
            unpriced += 1
            continue
        valuations[stock.ticker] = value(position, stock.current.price, rate)

    valuations = with_weights(valuations)

    views = [
        StockView.of(
            stock,
            evaluate(stock),
            position=positions.get(stock.ticker),
            valuation=valuations.get(stock.ticker),
        )
        for stock in stocks
    ]

    if not valuations:
        return views, None

    # The base-currency figures, not the native ones: summing a dollar value into
    # a real total is the bug this whole conversion exists to prevent.
    invested = sum((v.base_invested or Decimal(0) for v in valuations.values()), Decimal(0))
    market = sum((v.base_market_value or Decimal(0) for v in valuations.values()), Decimal(0))
    gain = market - invested
    totals = PortfolioTotals(
        invested=invested,
        market_value=market,
        unrealised_gain=gain,
        unrealised_gain_percent=(
            Decimal(0) if invested == 0 else (gain / invested * 100).quantize(Decimal("0.01"))
        ),
        currency=BASE_CURRENCY,
        priced=len(valuations),
        unpriced=unpriced,
    )
    return views, totals


def list_stocks(
    stocks: StockRepository,
    transactions: TransactionRepository,
    raw_list_type: str | None,
) -> dict[str, Any]:
    """Portfolio or watchlist, each stock already evaluated."""
    if raw_list_type is None:
        # REFERENCE rows are deliberately absent: an exchange rate is not a
        # holding, and listing it would put it in the weights.
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

    views, totals = build_views(
        sorted(found, key=lambda s: s.ticker), transactions, exchange_rates(stocks)
    )
    return json_response(200, StockListResponse(stocks=views, totals=totals))


def get_stock(
    stocks: StockRepository,
    snapshots: SnapshotRepository,
    transactions: TransactionRepository,
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

    rows = transactions.for_ticker(stock.ticker)
    position = current_position(stock.ticker, rows) if rows else None
    # The rate matters even for a single stock: without it a USD holding's
    # base figures would come back as its dollar amounts wearing a BRL label.
    # `weight` stays None here — a share of one is not a share of a portfolio.
    valuation = (
        value(position, stock.current.price, exchange_rates(stocks).rate_for(stock.currency))
        if position and position.quantity > 0 and stock.current
        else None
    )

    return json_response(
        200,
        StockDetailResponse(
            stock=StockView.of(stock, evaluate(stock), position=position, valuation=valuation),
            history=history,
            ledgers=running_by_broker(stock.ticker, rows),
        ),
    )


def route(
    event: dict[str, Any],
    stocks: StockRepository,
    snapshots: SnapshotRepository,
    transactions: TransactionRepository,
) -> dict[str, Any]:
    """Dispatch on API Gateway's `routeKey`, e.g. `GET /stocks/{ticker}`.

    Taking the routeKey rather than parsing the raw path means the URL shape is
    declared once, in Terraform, and the handler cannot silently disagree with it.
    """
    route_key = event.get("routeKey", "")
    params: dict[str, str] = event.get("queryStringParameters") or {}
    path: dict[str, str] = event.get("pathParameters") or {}

    if route_key == "GET /stocks":
        return list_stocks(stocks, transactions, params.get("listType"))

    if route_key == "GET /stocks/{ticker}":
        ticker = path.get("ticker", "")
        if not ticker:
            return error(400, "Missing ticker in the path.")
        return get_stock(stocks, snapshots, transactions, ticker, params.get("days"))

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
            DynamoDbTransactionRepository(dynamodb.Table(config.transactions_table)),
        )
    except Exception:
        logger.exception("Unhandled error serving %s", event.get("routeKey"))
        return error(500, "Something went wrong. Check the logs.")
