"""Manual smoke test against the REAL brapi API. Not part of the test suite.

Answers one question the unit tests cannot: does brapi's free tier actually
return the fields `BrapiProvider` maps? Every mapping in `QUOTE_FIELD_MAP` was
written against documentation, not against a live response.

    export BRAPI_TOKEN=...
    .venv/bin/python scripts/smoke_brapi.py PETR4

Hits the network and spends free-tier quota, so it lives in `scripts/` rather
than `tests/` and never runs under pytest.
"""

import argparse
import datetime as dt
import json
import os
import sys
from typing import Any

import httpx

from collector.handler import collect_one
from shared.models import Currency, ListType, Market, ProviderName, Stock
from shared.providers import BrapiProvider, ProviderError
from shared.providers.brapi import DEFAULT_BASE_URL, PRICE_KEY, QUOTE_FIELD_MAP
from shared.repository import InMemorySnapshotRepository

TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def report_raw_response(client: httpx.Client, token: str, ticker: str) -> dict[str, Any]:
    """Fetch once, unmapped, and show what brapi really sends back."""
    response = client.get(f"{DEFAULT_BASE_URL}/quote/{ticker}", params={"token": token})
    print(f"HTTP {response.status_code} {response.reason_phrase}")

    if response.status_code != httpx.codes.OK:
        print(f"  body: {response.text[:500]}")
        if response.status_code == httpx.codes.UNAUTHORIZED:
            print(
                "\n  brapi serves only PETR4, MGLU3, VALE3 and ITUB4 anonymously."
                "\n  Every other ticker needs BRAPI_TOKEN to be set."
            )
        return {}

    payload = response.json()
    results = payload.get("results") or []
    if not results:
        print(f"  no results in payload: {json.dumps(payload)[:500]}")
        return {}

    result: dict[str, Any] = results[0]
    print(f"\n{len(result)} keys in the response:")
    for key in sorted(result):
        value = result[key]
        rendered = json.dumps(value)
        if len(rendered) > 70:
            rendered = rendered[:67] + "..."
        print(f"  {key:<34} {rendered}")
    return result


def report_mapping(result: dict[str, Any]) -> list[str]:
    """Check every key `BrapiProvider` looks for. Returns the missing ones."""
    print("\nMapping check:")
    missing: list[str] = []

    for field, key in [("price", PRICE_KEY), *QUOTE_FIELD_MAP.items()]:
        if key in result and result[key] is not None:
            print(f"  FOUND    {field:<20} <- {key:<30} = {result[key]}")
        else:
            print(f"  MISSING  {field:<20} <- {key}")
            missing.append(field)

    return missing


def report_snapshot(provider: BrapiProvider, ticker: str) -> None:
    """Run the real pipeline: fetch -> compute -> the item we would store."""
    stock = Stock(
        ticker=ticker,
        name=ticker,
        market=Market.B3,
        currency=Currency.BRL,
        provider=ProviderName.BRAPI,
        list_type=ListType.PORTFOLIO,
    )
    # Empty history, so the change fields stay absent — there is nothing to
    # compare against on a first run. That is the correct behaviour, not a bug.
    snapshot = collect_one(
        stock,
        provider=provider,
        snapshots=InMemorySnapshotRepository(),
        as_of=dt.date.today(),
    )

    print("\nDynamoDB item we would write:")
    item = snapshot.model_dump(by_alias=True, exclude_none=True)
    for key, value in item.items():
        kind = type(value).__name__
        print(f"  {key:<24} {value!s:<24} ({kind})")

    non_decimal = [k for k, v in item.items() if isinstance(v, float)]
    if non_decimal:
        print(f"\n  WARNING: float values boto3 will reject: {non_decimal}")
    else:
        print("\n  All numbers are Decimal — boto3 will accept this item.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker", nargs="?", default="PETR4", help="B3 ticker (default: PETR4)")
    args = parser.parse_args(argv)

    ticker = args.ticker.strip().upper()
    token = os.environ.get("BRAPI_TOKEN", "")
    if not token:
        print("BRAPI_TOKEN is not set — trying anonymously, which brapi may reject.\n")

    print(f"=== brapi smoke test: {ticker} ===\n")

    with httpx.Client(timeout=TIMEOUT) as client:
        try:
            result = report_raw_response(client, token, ticker)
        except httpx.HTTPError as exc:
            print(f"Request failed: {exc}")
            return 1

        if not result:
            print("\nNo usable response. Check the token and the ticker.")
            return 1

        missing = report_mapping(result)

        provider = BrapiProvider(client, token=token)
        try:
            report_snapshot(provider, ticker)
        except ProviderError as exc:
            print(f"\nProvider error: {type(exc).__name__}: {exc}")
            return 1

    if missing:
        print(f"\n{len(missing)} field(s) not in this response: {', '.join(missing)}")
        print("Those must come from bolsai or be derived in the COMPUTE step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
