"""Record a single trade in the ledger.

    .venv/bin/python scripts/add_transaction.py CPLE3 BUY 200 15,22 --broker "BTG PACTUAL"
    .venv/bin/python scripts/add_transaction.py VALE3 SELL 100 78.31 --broker NU --date 2026-08-29

The importers exist for a broker's whole export; this is for the one purchase you
just made. It prints the position before and after, so the average price is
something you agreed to rather than something you discovered later.

`--broker` is required and has no default. It is the unit Brazilian IRPF declares
by — the same security at two custodians is two entries in Bens e Direitos, each
with its own average cost — so a trade filed under the wrong one quietly corrupts
the figure the tax return needs.
"""

import argparse
import datetime as dt
import hashlib
import sys
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import boto3

from shared.models import Currency, ListType, Transaction, TransactionType
from shared.positions import running_by_broker
from shared.repository import DynamoDbStockRepository, DynamoDbTransactionRepository

BROKERS = ["BTG PACTUAL", "NU INVEST", "INTER", "RICO", "AVENUE"]
"""Known custodians. Matched on a prefix, so `--broker BTG` is enough."""

MARKET_TIMEZONE = "America/Sao_Paulo"


def money(raw: str) -> Decimal:
    """Accept `15,22` as readily as `15.22`.

    The screen shows Brazilian notation, so that is what gets typed back in;
    rejecting it would be the tool disagreeing with itself.
    """
    try:
        return Decimal(raw.strip().replace(".", "").replace(",", ".") if "," in raw else raw)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not a number: {raw}") from None


def resolve_broker(given: str) -> str:
    """Expand a prefix to a full custodian name, or fail loudly.

    Never invents one: a typo that silently created a sixth broker would split a
    position in two and the averages would both be wrong.
    """
    wanted = given.strip().upper()
    matches = [name for name in BROKERS if name.startswith(wanted)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"Unknown broker {given!r}. Known: {', '.join(BROKERS)}")
    raise SystemExit(f"{given!r} matches several: {', '.join(matches)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record one trade.")
    parser.add_argument("ticker")
    parser.add_argument("type", choices=[member.value for member in TransactionType])
    parser.add_argument("quantity", type=money)
    parser.add_argument("unit_price", type=money, help="0 for a BONUS or TRANSFER_OUT.")
    parser.add_argument("--broker", required=True, help="Full name or a unique prefix.")
    parser.add_argument("--date", help="ISO date. Defaults to today in São Paulo.")
    parser.add_argument("--note")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    db = boto3.resource("dynamodb", region_name=args.region)
    stocks = DynamoDbStockRepository(db.Table("stock-tracker-Stocks"))
    ledger = DynamoDbTransactionRepository(db.Table("stock-tracker-Transactions"))

    ticker = args.ticker.strip().upper()
    stock = stocks.get(ticker)
    if stock is None:
        print(f"{ticker} is not registered. Seed it first, or check the ticker.")
        return 1
    if stock.list_type is ListType.WATCHLIST:
        print(f"Note: {ticker} is on the watchlist. Recording a trade makes it a holding.")

    broker = resolve_broker(args.broker)
    # The market's own timezone, not the machine's: a purchase made late on a
    # Monday evening would otherwise be filed on Tuesday.
    date = (
        dt.date.fromisoformat(args.date)
        if args.date
        else dt.datetime.now(ZoneInfo(MARKET_TIMEZONE)).date()
    )

    existing = ledger.for_ticker(ticker)
    same_day = [t for t in existing if t.date == date and t.broker == broker]

    transaction = Transaction(
        ticker=ticker,
        date=date,
        type=TransactionType(args.type),
        quantity=args.quantity,
        unit_price=args.unit_price,
        currency=stock.currency,
        broker=broker,
        # Ordered after anything already recorded for this broker on this day, so
        # the fold is deterministic when several trades share a date.
        sequence=len(same_day),
        note=args.note,
        id=hashlib.sha1(
            f"{ticker}|{date}|{args.type}|{args.quantity}|{args.unit_price}"
            f"|{broker}|{len(same_day)}".encode()
        ).hexdigest()[:12],
    )

    def show(label: str, rows: list[Transaction]) -> None:
        print(f"\n{label}")
        for entry in running_by_broker(ticker, rows):
            position = entry.position
            held = (
                f"{position.quantity} @ {position.average_price}  (invested {position.invested})"
                if position
                else "closed"
            )
            print(f"  {(entry.broker or '—'):<14}{held}")

    symbol = "R$" if stock.currency is Currency.BRL else "$"
    print(
        f"{transaction.type.value} {transaction.quantity} {ticker} @ {symbol} "
        f"{transaction.unit_price} at {broker} on {date}"
    )
    show("before:", existing)
    show("after:", [*existing, transaction])

    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    ledger.save(transaction)
    print(f"\nRecorded. id {transaction.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
