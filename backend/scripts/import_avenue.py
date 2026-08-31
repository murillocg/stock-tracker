"""Import Avenue statements into the transaction ledger.

    .venv/bin/python scripts/import_avenue.py ~/Downloads --dry-run
    .venv/bin/python scripts/import_avenue.py ~/Downloads

Avenue exports a cash-account statement rather than a trade report, so trades are
parsed out of the Portuguese description. Two things about that are easy to get
wrong, and both are handled below: the amount separator is a non-breaking space,
and the quantity in the description is ROUNDED for display.
"""

import argparse
import csv
import datetime as dt
import glob
import hashlib
import re
import sys
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import boto3

from shared.models import Currency, Transaction, TransactionType
from shared.positions import LedgerError, current_position
from shared.repository import DynamoDbTransactionRepository

BROKER = "AVENUE"

TRADE = re.compile(r"^(Compra|Venda)\s+de\s+([\d.,]+)\s+([A-Z.]+)\s+a\s+\$\s*([\d.,]+)\s+cada$")
"""`Compra de 3,2 BNY a $ 157,97 cada`.

`\\s` rather than a literal space: Avenue separates the dollar sign from the
amount with a non-breaking space, and a plain " " silently matches nothing.
"""

RENAMES = {
    "FB": "META",
    "BK": "BNY",
}
"""Ticker changes, both confirmed against the Avenue holdings screen, which shows
a single line for each. Facebook became Meta in 2022; Bank of New York Mellon now
trades as BNY. Folding them separately would give two half positions."""

DUST = Decimal("0.001")
"""Below this, a leftover quantity is rounding residue, not a holding.

Quantities are derived by division (see `quantity_of`), so a bought-and-sold
position lands near zero rather than on it — MCHI ends at 0.00001 shares.
"""

EXPECTED: dict[str, str] = {
    "MU": "2",
    "META": "3.24061",
    "BNY": "9.33672",
    "MSFT": "4.06301",
    "BABA": "4.20042",
    "VOO": "3.22282",
}
"""What the Avenue app reports. Checked to DUST rather than exactly: the true
fractional quantity is recorded nowhere in the statement, so a derived figure
cannot match to the last digit. The residual is about a tenth of a dollar across
ten thousand."""

CLOSED = {
    "IAU": "Sold in full. The closing sale appears in none of the twelve statements, "
    "so the fold still shows 4.5 shares. The trades import exactly as exported rather "
    "than being balanced by an invented sale at an invented price — IAU is simply not "
    "registered as a holding, so nothing reads the residue. If the missing sale turns "
    "up, adding it here is the whole fix.",
}
"""Positions that are gone but that the statements cannot close by themselves."""


def brazilian(number: str) -> Decimal:
    """`1.234,56` -> `1234.56`."""
    return Decimal(number.replace(".", "").replace(",", "."))


def quantity_of(amount: Decimal, price: Decimal) -> Decimal:
    """Shares actually traded, derived from the money rather than the description.

    Avenue rounds the displayed quantity: a $500.00 purchase of VOO at $709.89 is
    written `0,7` but is really 0.704334 shares. Taking the description at face
    value put VOO at 3.23 against the app's 3.22282, and the average a cent out.
    """
    return (abs(amount) / price).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def read_statements(directory: str) -> list[Transaction]:
    """Parse every statement in `directory`, de-duplicating the overlap.

    The exports are per period and overlap, so the same trade appears in several
    files. A row is identified by date, description and amount.
    """
    paths = sorted(glob.glob(str(Path(directory).expanduser() / "avenue-report-statement*.csv")))
    if not paths:
        raise SystemExit(f"No avenue-report-statement*.csv found in {directory}")

    seen: set[tuple[str, str, str]] = set()
    trades: list[Transaction] = []

    for path in paths:
        with open(path, encoding="utf-8-sig") as handle:
            for index, row in enumerate(csv.DictReader(handle)):
                description = " ".join(row["Descrição"].split())
                key = (row["Data transação"], description, row["Valor"])
                if key in seen:
                    continue
                seen.add(key)

                match = TRADE.match(description)
                if match is None:
                    continue

                price = brazilian(match.group(4))
                date = dt.datetime.strptime(row["Data transação"], "%d/%m/%Y").date()
                ticker = RENAMES.get(match.group(3), match.group(3))
                trades.append(
                    Transaction(
                        ticker=ticker,
                        date=date,
                        type=(
                            TransactionType.BUY
                            if match.group(1) == "Compra"
                            else TransactionType.SELL
                        ),
                        quantity=quantity_of(Decimal(row["Valor"]), price),
                        unit_price=price,
                        currency=Currency.USD,
                        broker=BROKER,
                        sequence=index,
                        id=hashlib.sha1("|".join(key).encode()).hexdigest()[:12],
                    )
                )

    print(f"{len(paths)} statements, {len(seen)} unique rows, {len(trades)} trades")
    return trades


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Avenue statements.")
    parser.add_argument("directory", help="Folder holding avenue-report-statement*.csv")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--table", default="stock-tracker-Transactions")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    trades = read_statements(args.directory)

    by_ticker: dict[str, list[Transaction]] = defaultdict(list)
    for trade in trades:
        by_ticker[trade.ticker].append(trade)

    keys: dict[tuple[str, str], int] = defaultdict(int)
    for trade in trades:
        keys[(trade.ticker, trade.sort_key)] += 1
    if any(n > 1 for n in keys.values()):
        print("Refusing to import — rows would overwrite each other:")
        for (ticker, key), n in sorted(keys.items()):
            if n > 1:
                print(f"  {ticker} {key} x{n}")
        return 1

    print(f"\n{'ticker':<7}{'qty':>12}{'expected':>12}{'drift':>11}{'avg':>9}{'invested':>11}")
    print("-" * 62)
    problems: list[str] = []
    for ticker in sorted(by_ticker):
        try:
            position = current_position(ticker, by_ticker[ticker])
        except LedgerError as exc:
            problems.append(f"{ticker}: {exc}")
            print(f"{ticker:<7}  LEDGER ERROR")
            continue
        if position is None or position.quantity <= DUST:
            print(f"{ticker:<7}{'closed':>12}")
            continue

        if ticker in CLOSED:
            print(f"{ticker:<7}{position.quantity:>12}{'closed':>12}   (residue, see CLOSED)")
            continue

        expected = EXPECTED.get(ticker)
        if expected is None:
            print(f"{ticker:<7}{position.quantity:>12}{'not listed':>12}")
            problems.append(f"{ticker}: {position.quantity} held, but Avenue does not list it")
            continue

        drift = position.quantity - Decimal(expected)
        if abs(drift) > DUST:
            problems.append(f"{ticker}: {position.quantity} vs {expected} — drift {drift}")
        print(
            f"{ticker:<7}{position.quantity:>12}{expected:>12}{drift:>11}"
            f"{position.average_price:>9}{position.invested:>11}"
        )

    if problems:
        print("\nRefusing to import:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print(f"\nEvery holding matches Avenue to within {DUST} shares.")
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    repository = DynamoDbTransactionRepository(
        boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    )
    for trade in trades:
        repository.save(trade)
    print(f"Wrote {len(trades)} rows to {args.table}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
