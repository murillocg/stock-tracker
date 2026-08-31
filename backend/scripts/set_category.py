"""Set a stock's Lynch category — the one field a human decides.

    .venv/bin/python scripts/set_category.py BNY STALWART
    .venv/bin/python scripts/set_category.py VOO --clear

CLAUDE.md is explicit that the app must never infer this tag, which is why
`seed_stocks.py` leaves it empty and why it gets its own command instead of a
flag on the seeder: registering a stock is mechanical, judging it is not.

Read-modify-write rather than a bare put. `save()` writes the whole item, so
constructing a fresh `Stock` here would silently erase the denormalised `current`
snapshot and the alert rules along with it.
"""

import argparse
import os
import sys

import boto3

from shared.models import LynchCategory
from shared.repository import DynamoDbStockRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set or clear a stock's Lynch category.")
    parser.add_argument("ticker")
    parser.add_argument(
        "category",
        nargs="?",
        choices=[member.value for member in LynchCategory],
        help="Omit with --clear.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Remove the tag. For a security the categories do not describe — an "
        "index fund is 500 companies, not one to classify.",
    )
    parser.add_argument("--table", default=os.environ.get("STOCKS_TABLE", "stock-tracker-Stocks"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = parser.parse_args(argv)

    if bool(args.category) == args.clear:
        print("Give exactly one of: a category, or --clear.")
        return 1

    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    repository = DynamoDbStockRepository(table)

    ticker = args.ticker.strip().upper()
    stock = repository.get(ticker)
    if stock is None:
        print(f"{ticker} is not registered.")
        return 1

    new = None if args.clear else LynchCategory(args.category)
    before = stock.category.value if stock.category else "—"
    if stock.category == new:
        print(f"{ticker} is already {before}. Nothing to do.")
        return 0

    repository.save(stock.model_copy(update={"category": new}))
    print(f"{ticker}: {before} -> {new.value if new else '—'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
