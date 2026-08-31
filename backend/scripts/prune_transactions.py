"""Drop broker ledgers that cannot be reconciled.

    .venv/bin/python scripts/prune_transactions.py            # dry run
    .venv/bin/python scripts/prune_transactions.py --apply

An account qualifies only if it is closed AND it sold more than it ever
received — PRIO3 at Inter sells 200 having bought 100. Those are artefacts of
B3's Negociação export beginning in November 2019: the opening balance was
bought before the file starts, so the sale has nothing to sell. They cannot be
reconciled, cannot support a declaration, and are already excluded from every
fold.

A merely closed account is NOT pruned. Bought 500 and sold 500 is complete
history, and being old is not a reason to destroy it — `--all-closed` opts into
that, with a cutoff, for when you want it.

Deleting is irreversible — point-in-time recovery is off on this table — so the
rows are written to a JSON file before they go, and the script refuses to run if
removing them would move any current position by so much as a cent.
"""

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import boto3

from shared.models import ListType, Transaction, TransactionType
from shared.positions import combined_position, running_by_broker
from shared.repository import DynamoDbStockRepository, DynamoDbTransactionRepository

CUTOFF = dt.date(2026, 1, 1)

LEAVING = (TransactionType.SELL, TransactionType.TRANSFER_OUT)
"""The two ways shares leave an account. Everything else adds to it."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prune unreconcilable broker ledgers.")
    parser.add_argument("--apply", action="store_true", help="Delete. Without it, report only.")
    parser.add_argument(
        "--all-closed",
        action="store_true",
        help="Also prune closed accounts whose history IS complete, if older than --cutoff.",
    )
    parser.add_argument("--cutoff", default=CUTOFF.isoformat(), help="Only with --all-closed.")
    parser.add_argument("--backup", default="pruned-transactions.json")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    cutoff = dt.date.fromisoformat(args.cutoff)
    db = boto3.resource("dynamodb", region_name=args.region)
    table = db.Table("stock-tracker-Transactions")
    transactions = DynamoDbTransactionRepository(table)
    stocks = DynamoDbStockRepository(db.Table("stock-tracker-Stocks"))

    registered = [s.ticker for s in stocks.list_by_type(ListType.PORTFOLIO)]
    doomed: list[Transaction] = []

    if args.all_closed:
        print(f"Closed accounts, including complete ones, last traded before {cutoff}:\n")
    else:
        print("Closed accounts that sold more than they ever received:\n")
    print(f"{'ticker':<9}{'broker':<15}{'rows':>5}{'last trade':>13}{'in':>7}{'out':>7}")
    print("-" * 56)

    for ticker in sorted(registered):
        rows = transactions.for_ticker(ticker)
        if not rows:
            continue
        for ledger in running_by_broker(ticker, rows):
            if ledger.position is not None or not ledger.entries:
                continue  # still held here — never touched
            group = [entry.transaction for entry in ledger.entries]
            last = max(t.date for t in group)
            received = sum((t.quantity for t in group if t.type not in LEAVING), Decimal(0))
            left = sum((t.quantity for t in group if t.type in LEAVING), Decimal(0))

            # The ledger is impossible: more went out than ever came in, so the
            # opening balance predates the export and cannot be recovered.
            broken = left > received
            if not broken and not (args.all_closed and last < cutoff):
                continue

            doomed.extend(group)
            print(
                f"{ticker:<9}{(ledger.broker or '—'):<15}{len(group):>5}{last.isoformat():>13}"
                f"{received:>7}{left:>7}"
            )

    if not doomed:
        print("(none)")
        return 0

    # The safety property: these rows are already outside every fold, so removing
    # them must change nothing. Proving it beats asserting it.
    print(f"\n{len(doomed)} rows across {len({t.ticker for t in doomed})} tickers.\n")
    condemned = {(t.ticker, t.sort_key) for t in doomed}
    moved = []
    for ticker in sorted({t.ticker for t in doomed}):
        rows = transactions.for_ticker(ticker)
        kept = [t for t in rows if (t.ticker, t.sort_key) not in condemned]
        before, after = combined_position(ticker, rows), combined_position(ticker, kept)
        if (before is None) != (after is None) or (
            before is not None and after is not None and before != after
        ):
            moved.append(f"{ticker}: {before} -> {after}")

    if moved:
        print("Refusing to prune — these positions would change:")
        for line in moved:
            print(f"  {line}")
        return 1
    print("Verified: every current position is identical without these rows.")

    if not args.apply:
        print("\nDry run. Re-run with --apply to delete.")
        return 0

    backup = Path(args.backup)
    backup.write_text(
        json.dumps(
            [t.model_dump(by_alias=True, mode="json") for t in doomed],
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    print(f"\nWrote {len(doomed)} rows to {backup} before deleting.")

    # Straight to the table: the repository has no delete, and should not grow
    # one. Nothing in the collector or the API ever removes a transaction — an
    # append-only ledger is the point — so this stays where the exception is
    # visible, in a script you have to run on purpose.
    counts: dict[str, int] = defaultdict(int)
    with table.batch_writer() as batch:
        for t in doomed:
            batch.delete_item(Key={"ticker": t.ticker, "dateId": t.sort_key})
            counts[t.ticker] += 1

    for ticker, n in sorted(counts.items()):
        print(f"  {ticker}: deleted {n}")
    print(f"\nDeleted {len(doomed)} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
