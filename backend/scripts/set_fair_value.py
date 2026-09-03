"""Record a fair value from outside this app.

    .venv/bin/python scripts/set_fair_value.py VIVA3 30,14 \
        --source "Analyst DCF, 10% real discount, 2.5% perpetuity"
    .venv/bin/python scripts/set_fair_value.py VIVA3 --clear

The rulesets derive a CEILING — the highest price at which a stock still passes
its own category. That is not a valuation, and for a fast grower it can sit far
above one: VIVA3's derived ceiling was R$ 83,19 against a published DCF of
R$ 30,14, because PEG projects trailing growth forward while a DCF decays it.

Recording the outside number does not override anything. It sits alongside, so
the disagreement is visible rather than averaged away.
"""

import argparse
import datetime as dt
import sys
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import boto3

from shared.repository import DynamoDbStockRepository

MARKET_TIMEZONE = "America/Sao_Paulo"


def money(raw: str) -> Decimal:
    """Accept `30,14` as readily as `30.14` — the screen shows the former."""
    try:
        return Decimal(raw.strip().replace(".", "").replace(",", ".") if "," in raw else raw)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not a number: {raw}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record an external fair value.")
    parser.add_argument("ticker")
    parser.add_argument("value", nargs="?", type=money, help="Omit with --clear.")
    parser.add_argument("--source", help="Who produced it, and on what assumptions.")
    parser.add_argument("--on", help="ISO date of the research. Defaults to today.")
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    if (args.value is None) == (not args.clear):
        print("Give exactly one of: a value, or --clear.")
        return 1

    repository = DynamoDbStockRepository(
        boto3.resource("dynamodb", region_name=args.region).Table("stock-tracker-Stocks")
    )
    ticker = args.ticker.strip().upper()
    stock = repository.get(ticker)
    if stock is None:
        print(f"{ticker} is not registered.")
        return 1

    if args.clear:
        repository.save(
            stock.model_copy(
                update={"fair_value": None, "fair_value_source": None, "fair_value_on": None}
            )
        )
        print(f"{ticker}: fair value cleared.")
        return 0

    # A target price with no date is a number with no shelf life.
    on = (
        dt.date.fromisoformat(args.on)
        if args.on
        else dt.datetime.now(ZoneInfo(MARKET_TIMEZONE)).date()
    )
    repository.save(
        stock.model_copy(
            update={
                "fair_value": args.value,
                "fair_value_source": args.source,
                "fair_value_on": on,
            }
        )
    )

    price = stock.current.price if stock.current else None
    gap = f"  ({(args.value / price - 1) * 100:+.1f}% vs today's {price})" if price else ""
    print(f"{ticker}: fair value {args.value} as of {on}{gap}")
    if args.source:
        print(f"  source: {args.source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
