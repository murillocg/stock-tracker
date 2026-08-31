"""Register stocks in the Stocks table, with metadata fetched from the provider.

Writes through our own `Stock` model and `DynamoDbStockRepository`, so the item
shape, camelCase aliases and enum values are whatever the application expects
rather than hand-written JSON that drifts from it.

    export BRAPI_TOKEN=...
    .venv/bin/python scripts/seed_stocks.py PETR4 VALE3 BBAS3
    .venv/bin/python scripts/seed_stocks.py --list-type WATCHLIST TTEN3

    export ALPHA_VANTAGE_API_KEY=...
    .venv/bin/python scripts/seed_stocks.py --market NASDAQ BABA BNY

The market picks everything downstream — currency, both providers, and where the
metadata comes from. B3 names come from brapi, US names from Alpha Vantage.

Existing stocks are skipped, never overwritten: `save()` is a full put, and
rewriting one would erase the manually-set `category` and the denormalised
`current` snapshot. Use --force only if you mean that.

`category` is deliberately never set here. CLAUDE.md is explicit that the Lynch
tag is a human judgement and the app must not infer it.
"""

import argparse
import os
import sys
import time
from collections.abc import Callable
from typing import Any

import boto3
import httpx

from shared.models import Currency, ListType, Market, ProviderName, Stock
from shared.providers import Pacer
from shared.providers.alpha_vantage import DEFAULT_BASE_URL as ALPHA_VANTAGE_URL
from shared.providers.alpha_vantage import raise_for_body
from shared.providers.brapi import DEFAULT_BASE_URL
from shared.providers.errors import (
    AuthenticationError,
    ProviderUnavailableError,
    TickerNotFoundError,
)
from shared.repository import DynamoDbStockRepository

TIMEOUT = httpx.Timeout(15.0, connect=5.0)

DELAY_SECONDS = 1.5
"""Gap between upstream calls, matching the collector's.

Alpha Vantage rejects a second request inside the same second, and describing one
ETF takes two calls — OVERVIEW then GLOBAL_QUOTE. Firing them back-to-back is
what made VOO look like an unknown ticker.
"""

RETRY_PAUSE_SECONDS = 5.0
RETRIES = 2
"""One retry, which is what separates the two rate limits without reading their
prose: the per-second burst clears after a pause, the 25-a-day cap does not. If
the second attempt fails too, it is the daily cap and the run should stop."""

PROVIDERS: dict[Market, tuple[ProviderName, ProviderName]] = {
    Market.B3: (ProviderName.BRAPI, ProviderName.BOLSAI),
    Market.NYSE: (ProviderName.ALPHA_VANTAGE, ProviderName.ALPHA_VANTAGE),
    Market.NASDAQ: (ProviderName.ALPHA_VANTAGE, ProviderName.ALPHA_VANTAGE),
}
"""Quote provider, fundamentals provider. Two entries because no free source
covers both on B3: brapi serves the price, bolsai the fundamentals. Alpha Vantage
happens to do both for US listings, which is why those rows repeat themselves."""

CURRENCIES: dict[Market, Currency] = {
    Market.B3: Currency.BRL,
    Market.NYSE: Currency.USD,
    Market.NASDAQ: Currency.USD,
}

# summaryProfile is the one module brapi's free plan does serve, and it carries
# the sector. The fundamentals modules are Pro-only; we get those from bolsai.
PROFILE_MODULE = "summaryProfile"

SECTOR_EN: dict[str, str] = {
    "Serviços Financeiros": "Financial Services",
    "Energia": "Energy",
    "Materiais Básicos": "Basic Materials",
    "Consumo Cíclico": "Consumer Cyclical",
    "Consumo Não Cíclico": "Consumer Defensive",
    "Construção e Imobiliário": "Real Estate",
    "Emp. Adm. Part. - Energia Elétrica": "Utilities",
    "Saúde": "Healthcare",
    "Tecnologia": "Technology",
    "Bens Industriais": "Industrials",
    "Comunicações": "Communication Services",
    "Utilidade Pública": "Utilities",
}
"""brapi's Portuguese sector -> the English name we store.

CLAUDE.md: everything in English, including stored field values. brapi's taxonomy
is Yahoo-derived, so these are Yahoo's own English labels rather than a literal
translation — which keeps the vocabulary standard if a US provider is added later.

Anything unmapped is stored as-is: a wrong-but-real value is easier to notice and
fix than a silently dropped one.
"""


def fetch_us_metadata(
    client: httpx.Client, key: str, ticker: str, pace: Pacer
) -> dict[str, str] | None:
    """Company name and sector from Alpha Vantage's OVERVIEW.

    An ETF returns `{}` here rather than an error — OVERVIEW describes companies,
    and VOO is not one. That is not "unknown ticker", so the empty case falls
    through to GLOBAL_QUOTE to establish that the symbol trades at all, and the
    stock registers with no sector. Treating the empty body as a failure would
    make every ETF unregistrable.

    Both responses go through the provider's own `raise_for_body`, so an
    exhausted quota surfaces as a quota error instead of being mistaken for a
    symbol that does not exist.
    """
    pace.wait()
    overview = client.get(
        ALPHA_VANTAGE_URL, params={"function": "OVERVIEW", "symbol": ticker, "apikey": key}
    ).json()
    raise_for_body(ticker, overview)

    if overview.get("Name"):
        sector = str(overview.get("Sector") or "").title()
        return {"name": str(overview["Name"]), "sector": sector}

    pace.wait()
    quote = client.get(
        ALPHA_VANTAGE_URL, params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": key}
    ).json()
    raise_for_body(ticker, quote)

    # The key is "Global Quote" on the free tier and carries a suffix on some
    # premium plans, so match on the prefix rather than the exact string.
    body = next(
        (v for k, v in quote.items() if k.startswith("Global Quote") and isinstance(v, dict)),
        {},
    )
    if body.get("05. price"):
        print("  no company overview (an ETF, most likely) — registering without a sector")
        return {"name": ticker, "sector": ""}

    # Neither call identified it and neither raised. Show what came back: a
    # bare "check the ticker" here has already sent one person chasing a symbol
    # that was not the problem.
    print(f"  OVERVIEW said: {str(overview)[:200]}")
    print(f"  GLOBAL_QUOTE said: {str(quote)[:200]}")
    return None


def fetch_metadata(
    client: httpx.Client, token: str, ticker: str, pace: Pacer
) -> dict[str, str] | None:
    """Company name and sector from brapi, or `None` if the ticker is unknown.

    Tries with the profile module first, then falls back to a plain quote. The
    sector is a nice-to-have; the ticker existing is not. Losing the module must
    not be mistaken for the stock not existing.
    """
    for params in (
        {"token": token, "modules": PROFILE_MODULE},
        {"token": token},
    ):
        pace.wait()
        response = client.get(f"{DEFAULT_BASE_URL}/quote/{ticker}", params=params)

        if response.status_code == httpx.codes.OK:
            results = response.json().get("results") or []
            if not results:
                return None
            result: dict[str, Any] = results[0]
            profile = result.get(PROFILE_MODULE) or {}
            sector = profile.get("sector") or ""
            return {
                "name": result.get("longName") or result.get("shortName") or ticker,
                "sector": SECTOR_EN.get(sector, sector),
            }

        # 404 means the ticker genuinely does not exist — retrying without the
        # module would only waste a request and give the same answer.
        if response.status_code == httpx.codes.NOT_FOUND:
            return None

        print(f"  brapi says HTTP {response.status_code}: {response.text[:120]}")

    return None


def describe(
    client: httpx.Client,
    market: Market,
    credential: str,
    ticker: str,
    pace: Pacer,
    sleep: Callable[[float], None],
) -> dict[str, str] | None:
    """Ask the right provider about `ticker`, riding out a transient rate limit.

    Retries exactly once. A burst limit clears after a pause and a daily cap does
    not, so the second failure is the informative one — and it propagates, which
    is what stops the run.
    """
    for attempt in range(1, RETRIES + 1):
        try:
            if market is Market.B3:
                return fetch_metadata(client, credential, ticker, pace)
            return fetch_us_metadata(client, credential, ticker, pace)
        except ProviderUnavailableError:
            if attempt == RETRIES:
                raise
            print(f"  rate limited — pausing {RETRY_PAUSE_SECONDS:.0f}s and trying once more")
            sleep(RETRY_PAUSE_SECONDS)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed stocks into the registry.")
    parser.add_argument("tickers", nargs="+", help="Tickers, e.g. PETR4 VALE3 or BABA BNY")
    parser.add_argument(
        "--market",
        default=Market.B3.value,
        choices=[member.value for member in Market],
        help="Decides currency, providers, and which API supplies the metadata.",
    )
    parser.add_argument(
        "--list-type",
        default=ListType.PORTFOLIO.value,
        choices=[member.value for member in ListType],
    )
    parser.add_argument("--table", default=os.environ.get("STOCKS_TABLE", "stock-tracker-Stocks"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--name",
        help="Register under this name instead of asking the provider. For a "
        "security the provider cannot describe — an ETF has no OVERVIEW. Takes "
        "one ticker at a time, since a name applies to exactly one.",
    )
    parser.add_argument("--sector", default="", help="Only meaningful with --name.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing entries, discarding their category and current snapshot.",
    )
    args = parser.parse_args(argv)

    market = Market(args.market)
    quote_provider, fundamentals_provider = PROVIDERS[market]

    if args.name and len(args.tickers) > 1:
        print("--name describes one security; pass one ticker.")
        return 1

    # --name makes no provider call, so it must not demand a credential it will
    # never use — that is the case where the provider has already refused to help.
    if market is Market.B3:
        credential = os.environ.get("BRAPI_TOKEN", "")
        if not credential and not args.name:
            print("BRAPI_TOKEN is not set. Only PETR4/MGLU3/VALE3/ITUB4 work without it.\n")
    else:
        credential = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        if not credential and not args.name:
            print("ALPHA_VANTAGE_API_KEY is not set.")
            return 1

    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    repository = DynamoDbStockRepository(table)
    list_type = ListType(args.list_type)

    seeded: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    print(
        f"=== seeding into {args.table} ({args.region}) as {market.value} / {list_type.value} ===\n"
    )

    pace = Pacer(DELAY_SECONDS, time.sleep)

    with httpx.Client(timeout=TIMEOUT) as client:
        for raw in args.tickers:
            ticker = raw.strip().upper()
            print(f"{ticker}:")

            if not args.force and repository.get(ticker) is not None:
                print("  already registered — leaving category and current untouched")
                skipped.append(ticker)
                continue

            metadata: dict[str, str] | None
            try:
                if args.name:
                    print("  name given on the command line — not asking the provider")
                    metadata = {"name": args.name, "sector": args.sector}
                else:
                    metadata = describe(client, market, credential, ticker, pace, time.sleep)
            except TickerNotFoundError as exc:
                print(f"  {exc}")
                failed.append(ticker)
                continue
            except (AuthenticationError, ProviderUnavailableError) as exc:
                # A bad key or an exhausted quota applies to every remaining
                # ticker, so stopping beats printing the same failure N times and
                # burning what is left of a 25-request daily allowance.
                print(f"  {exc}")
                print("\nStopping: this affects every remaining ticker.")
                failed.extend(args.tickers[args.tickers.index(raw) :])
                break
            except httpx.HTTPError as exc:
                print(f"  request failed: {exc}")
                failed.append(ticker)
                continue

            if metadata is None:
                print("  the provider does not know this ticker — check it")
                failed.append(ticker)
                continue

            stock = Stock(
                ticker=ticker,
                name=metadata["name"],
                market=market,
                currency=CURRENCIES[market],
                quote_provider=quote_provider,
                fundamentals_provider=fundamentals_provider,
                sector=metadata["sector"] or None,
                list_type=list_type,
            )
            repository.save(stock)
            print(f"  {stock.name} · {stock.sector or 'sector unknown'}")
            seeded.append(ticker)

    print(f"\nseeded {len(seeded)}, skipped {len(skipped)}, failed {len(failed)}")
    if skipped:
        print(f"  skipped (already present): {', '.join(skipped)}")
    if failed:
        print(f"  failed: {', '.join(failed)}")
    print("\nRemember: `category` is not set by this script — the Lynch tag is yours to make.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
