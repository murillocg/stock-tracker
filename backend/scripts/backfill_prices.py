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

Covers both markets. B3 tickers carry a `.SA` suffix on Yahoo; US ones are
themselves.

A note on the one disagreement this turned up. Prices written by the SCHEDULED
run — 19:00 New York, hours after the close — match Yahoo to the cent. Three rows
written by ad-hoc invocations minutes after the bell did not, because Alpha
Vantage's GLOBAL_QUOTE was still serving an intraday quote and we stored it as a
close. That is an argument for collecting on the schedule, not against either
source.
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
    """Daily closes for `symbol`, keyed by trading day, up to YESTERDAY.

    Today is excluded on purpose. The collector owns today, and it skips any
    ticker that already has a row for the date it is collecting — so a price-only
    row written here for today does not merely sit there, it makes the evening
    run report SKIPPED and the real snapshot never arrives. That is a silent
    failure: the run looks healthy and the fundamentals quietly vanish.
    """
    response = client.get(
        f"{CHART_URL}/{symbol}", params={"range": period, "interval": "1d"}, headers=HEADERS
    )
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]

    stamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    today = dt.date.today()
    return {
        day: Decimal(str(close)).quantize(Decimal("0.01"))
        # A null close is a halted or untraded day. Skipping beats inventing one.
        for day, close in (
            (dt.date.fromtimestamp(stamp), close)
            for stamp, close in zip(stamps, closes, strict=False)
        )
        if close is not None and day < today
    }


def symbol_for(stock: Stock) -> str:
    """Yahoo's name for this security. B3 listings take a `.SA` suffix."""
    return f"{stock.ticker}.SA" if stock.market is Market.B3 else stock.ticker


def targets(stocks: DynamoDbStockRepository, market: str | None = None) -> Iterator[Stock]:
    """Holdings and watchlist entries, oldest ticker first."""
    both = [*stocks.list_by_type(ListType.PORTFOLIO), *stocks.list_by_type(ListType.WATCHLIST)]
    chosen = (
        both if market is None else [s for s in both if (s.market is Market.B3) == (market == "B3")]
    )
    yield from sorted(chosen, key=lambda s: s.ticker)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill B3 price history from Yahoo.")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    parser.add_argument("--period", default="1y", help="Yahoo range: 1y, 2y, 5y, max.")
    parser.add_argument(
        "--market",
        choices=["B3", "US"],
        help="Restrict to one side of the book. Both by default.",
    )
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
        for stock in targets(stocks, args.market):
            time.sleep(DELAY_SECONDS)
            try:
                closes = chart(client, symbol_for(stock), args.period)
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
    recompute(stocks, snapshots, args.market)
    return 0


def carries_fundamentals(snapshot: DailySnapshot) -> bool:
    """Whether this row came from a collection rather than a price backfill."""
    return any(
        getattr(snapshot, field) is not None
        for field in ("pe", "pb", "roe", "ev_ebitda", "dividend_yield", "peg")
    )


def recompute(
    stocks: DynamoDbStockRepository,
    snapshots: DynamoDbSnapshotRepository,
    market: str | None = None,
) -> None:
    """Redo the change windows now that there is history behind them.

    The stored windows were computed when nothing preceded them, so they are all
    empty and nothing would recompute them until the next collection.

    `current` is taken from the newest row that CARRIES FUNDAMENTALS, not simply
    the newest row. A backfilled row has a price and nothing else, and promoting
    one to `current` strips the P/E and ROE the whole evaluation reads — which
    turns every verdict grey and every headroom into a dash. It did exactly that
    once; hence this function rather than `history[-1]`.
    """
    print("\nRecomputing change windows:")
    for stock in targets(stocks, market):
        history = snapshots.history(stock.ticker, since=dt.date(2000, 1, 1))
        if not history:
            continue
        collected = [row for row in history if carries_fundamentals(row)]
        latest = collected[-1] if collected else history[-1]
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


if __name__ == "__main__":
    sys.exit(main())
