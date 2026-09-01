"""Fill the price history that predates our own collection.

    .venv/bin/python scripts/backfill_prices.py --dry-run
    .venv/bin/python scripts/backfill_prices.py

Collection began on 2026-08-28, so every change window was empty and would have
stayed empty for a year. Yahoo's chart endpoint serves a year of daily closes for
B3 tickers with no credential, and — checked against every ticker we already
hold, on both collected days — it agrees with brapi to the cent. That agreement
is the whole basis for doing this: a backfill that disagreed with the present
would manufacture a jump exactly at the join, and the change windows measure
across the join.

A one-off, deliberately NOT a provider. The collector stays the source of truth
going forward; this only fills the hole behind it. Rows written here carry a
price and nothing else, because the chart endpoint serves nothing else — which
also makes them easy to tell apart from a collected row.

US tickers are excluded until we work out why Alpha Vantage disagrees with Yahoo
on them (BABA by 4.1%, matching no recent close). Splicing under a price we do
not trust would bake that difference into every US change window.
"""

import argparse
import datetime as dt
import sys
import time
from collections.abc import Iterator
from decimal import Decimal

import boto3
import httpx

from shared.indicators.changes import apply_changes, compute_changes
from shared.models import DailySnapshot, ListType, Market, Stock
from shared.repository import DynamoDbSnapshotRepository, DynamoDbStockRepository

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
TIMEOUT = httpx.Timeout(25.0, connect=10.0)
DELAY_SECONDS = 0.4
"""Yahoo has no published limit; this is politeness, and it is enough to avoid
the transient 400s a tight loop provokes."""

TOLERANCE = Decimal("0.01")
"""How far a backfilled price may sit from one we already collected, on a day we
hold both. A cent covers rounding. Anything wider means the two sources disagree
about the security, and the run stops rather than splice them together."""

HEADERS = {"User-Agent": "Mozilla/5.0 (stock-tracker; personal portfolio backfill)"}


def chart(client: httpx.Client, symbol: str, period: str) -> dict[dt.date, Decimal]:
    """Daily closes for `symbol`, keyed by trading day."""
    response = client.get(
        f"{CHART_URL}/{symbol}", params={"range": period, "interval": "1d"}, headers=HEADERS
    )
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]

    stamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    return {
        dt.date.fromtimestamp(stamp): Decimal(str(close)).quantize(Decimal("0.01"))
        # A null close is a halted or untraded day. Skipping beats inventing one.
        for stamp, close in zip(stamps, closes, strict=False)
        if close is not None
    }


def targets(stocks: DynamoDbStockRepository) -> Iterator[Stock]:
    """Brazilian holdings and watchlist entries, oldest ticker first."""
    both = [*stocks.list_by_type(ListType.PORTFOLIO), *stocks.list_by_type(ListType.WATCHLIST)]
    yield from sorted((s for s in both if s.market is Market.B3), key=lambda s: s.ticker)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill B3 price history from Yahoo.")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    parser.add_argument("--period", default="1y", help="Yahoo range: 1y, 2y, 5y, max.")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    db = boto3.resource("dynamodb", region_name=args.region)
    stocks = DynamoDbStockRepository(db.Table("stock-tracker-Stocks"))
    snapshots = DynamoDbSnapshotRepository(db.Table("stock-tracker-DailySnapshots"))

    pending: list[DailySnapshot] = []
    conflicts: list[str] = []

    print(f"{'ticker':<9}{'fetched':>9}{'have':>7}{'new':>7}{'oldest new':>13}  checked")
    print("-" * 62)

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for stock in targets(stocks):
            time.sleep(DELAY_SECONDS)
            try:
                closes = chart(client, f"{stock.ticker}.SA", args.period)
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                conflicts.append(f"{stock.ticker}: could not fetch ({type(exc).__name__})")
                continue

            held = {
                row.date: row.price
                for row in snapshots.history(stock.ticker, since=dt.date(2000, 1, 1))
            }

            # Every day we hold BOTH must agree, or the two sources are not
            # describing the same security and nothing here can be trusted.
            checked = 0
            for day, ours in held.items():
                theirs = closes.get(day)
                if theirs is None:
                    continue
                checked += 1
                if abs(ours - theirs) > TOLERANCE:
                    conflicts.append(f"{stock.ticker} on {day}: ours {ours}, Yahoo {theirs}")

            fresh = [
                DailySnapshot(ticker=stock.ticker, date=day, price=price)
                for day, price in sorted(closes.items())
                if day not in held
            ]
            pending.extend(fresh)
            oldest = fresh[0].date.isoformat() if fresh else "—"
            print(
                f"{stock.ticker:<9}{len(closes):>9}{len(held):>7}{len(fresh):>7}"
                f"{oldest:>13}  {checked} overlapping day(s) agree"
            )

    if conflicts:
        print("\nRefusing to backfill — the sources disagree:")
        for line in conflicts:
            print(f"  {line}")
        return 1

    print(f"\n{len(pending)} rows to add across {len({s.ticker for s in pending})} tickers.")
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    for snapshot in pending:
        snapshots.save(snapshot)
    print(f"Wrote {len(pending)} rows.")

    # The stored change windows were computed when there was no history behind
    # them, so they are all empty and nothing would recompute them until the next
    # collection. Redo them now, against the history that now exists.
    print("\nRecomputing change windows:")
    for stock in targets(stocks):
        history = snapshots.history(stock.ticker, since=dt.date(2000, 1, 1))
        if not history:
            continue
        latest = history[-1]
        changes = compute_changes(history[:-1], as_of=latest.date, current_price=latest.price)
        updated = apply_changes(latest, changes)
        snapshots.save(updated)
        # The list screen reads the denormalised copy, not the time series.
        stocks.save(stock.model_copy(update={"current": updated}))
        print(
            f"  {stock.ticker:<9}"
            + "  ".join(
                f"{window.field_name.replace('change_', '')} {value}%"
                for window, value in sorted(changes.items(), key=lambda kv: kv[0].delta)
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
