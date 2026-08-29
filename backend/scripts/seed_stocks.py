"""Register stocks in the Stocks table, with metadata fetched from brapi.

Writes through our own `Stock` model and `DynamoDbStockRepository`, so the item
shape, camelCase aliases and enum values are whatever the application expects
rather than hand-written JSON that drifts from it.

    export BRAPI_TOKEN=...
    .venv/bin/python scripts/seed_stocks.py PETR4 VALE3 BBAS3
    .venv/bin/python scripts/seed_stocks.py --list-type WATCHLIST TTEN3

Existing stocks are skipped, never overwritten: `save()` is a full put, and
rewriting one would erase the manually-set `category` and the denormalised
`current` snapshot. Use --force only if you mean that.

`category` is deliberately never set here. CLAUDE.md is explicit that the Lynch
tag is a human judgement and the app must not infer it.
"""

import argparse
import os
import sys
from typing import Any

import boto3
import httpx

from shared.models import Currency, ListType, Market, ProviderName, Stock
from shared.providers.brapi import DEFAULT_BASE_URL
from shared.repository import DynamoDbStockRepository

TIMEOUT = httpx.Timeout(15.0, connect=5.0)

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


def fetch_metadata(client: httpx.Client, token: str, ticker: str) -> dict[str, str] | None:
    """Company name and sector from brapi, or `None` if the ticker is unknown.

    Tries with the profile module first, then falls back to a plain quote. The
    sector is a nice-to-have; the ticker existing is not. Losing the module must
    not be mistaken for the stock not existing.
    """
    for params in (
        {"token": token, "modules": PROFILE_MODULE},
        {"token": token},
    ):
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed stocks into the registry.")
    parser.add_argument("tickers", nargs="+", help="B3 tickers, e.g. PETR4 VALE3")
    parser.add_argument(
        "--list-type",
        default=ListType.PORTFOLIO.value,
        choices=[member.value for member in ListType],
    )
    parser.add_argument("--table", default=os.environ.get("STOCKS_TABLE", "stock-tracker-Stocks"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing entries, discarding their category and current snapshot.",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("BRAPI_TOKEN", "")
    if not token:
        print("BRAPI_TOKEN is not set. Only PETR4/MGLU3/VALE3/ITUB4 work without it.\n")

    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    repository = DynamoDbStockRepository(table)
    list_type = ListType(args.list_type)

    seeded: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    print(f"=== seeding into {args.table} ({args.region}) as {list_type.value} ===\n")

    with httpx.Client(timeout=TIMEOUT) as client:
        for raw in args.tickers:
            ticker = raw.strip().upper()
            print(f"{ticker}:")

            if not args.force and repository.get(ticker) is not None:
                print("  already registered — leaving category and current untouched")
                skipped.append(ticker)
                continue

            try:
                metadata = fetch_metadata(client, token, ticker)
            except httpx.HTTPError as exc:
                print(f"  request failed: {exc}")
                failed.append(ticker)
                continue

            if metadata is None:
                print("  unknown to brapi — check the ticker")
                failed.append(ticker)
                continue

            stock = Stock(
                ticker=ticker,
                name=metadata["name"],
                market=Market.B3,
                currency=Currency.BRL,
                quote_provider=ProviderName.BRAPI,
                fundamentals_provider=ProviderName.BOLSAI,
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
