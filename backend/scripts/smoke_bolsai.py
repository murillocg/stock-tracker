"""Manual smoke test against the REAL bolsai API. Not part of the test suite.

Answers what the docs leave ambiguous before we write a line of provider code:

  1. Does `/fundamentals` actually carry a dividend yield? (The docs say yes; the
     sample payload we have says no.)
  2. What shape does `/dividends` return, and does it give a TTM yield we can use
     for `dividend_yield` and `payout_ratio`?
  3. Are the statement figures really in thousands while `market_cap` is in units?
  4. Does bolsai's `roic` reproduce from our own `roic()` implementation?

    export BOLSAI_API_KEY=...
    .venv/bin/python scripts/smoke_bolsai.py PETR4

Spends 2 of the 200 free daily requests.
"""

import argparse
import json
import os
import sys
from decimal import Decimal
from typing import Any

import httpx

from shared.indicators import roic

BASE_URL = "https://api.usebolsai.com/api/v1"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)

BRAZILIAN_TAX_RATE = Decimal("0.34")
"""Statutory IRPJ + CSLL. The rate bolsai's own ROIC appears to assume."""

FETCHED_FIELD_MAP: dict[str, str] = {
    "pe": "pl",
    "pb": "pvp",
    "ev_ebitda": "ev_ebitda",
    "roe": "roe",
    "net_debt_to_ebitda": "net_debt_ebitda",
    "gross_margin": "gross_margin",
    "ebitda_margin": "ebitda_margin",
    "dividend_yield": "dividend_yield",
}
"""Our `FetchedIndicators` field -> bolsai key. `dividend_yield` is the unproven one."""

COMPUTED_FIELD_MAP: dict[str, str] = {
    "roic": "roic",
    "revenue_growth": "cagr_revenue_5y",
    "earnings_growth": "cagr_earnings_5y",
}
"""Fields we compute ourselves that bolsai also supplies. Note the growth figures
are 5-year CAGR, not the year-over-year our `year_over_year()` produces."""

STATEMENT_KEYS = (
    "ebit",
    "ebitda",
    "equity",
    "net_debt",
    "total_debt",
    "cash",
    "net_income",
    "net_revenue",
)


def get(client: httpx.Client, path: str, key: str, **params: str) -> dict[str, Any] | None:
    """One authenticated call, with the rate-limit budget reported."""
    response = client.get(
        f"{BASE_URL}{path}",
        headers={"X-API-Key": key},
        params=params,
    )
    remaining = response.headers.get("X-RateLimit-Remaining", "?")
    print(f"GET {path} -> HTTP {response.status_code} (quota left today: {remaining})")

    if response.status_code != httpx.codes.OK:
        print(f"  body: {response.text[:400]}\n")
        return None
    body: dict[str, Any] = response.json()
    return body


def report_fundamentals(payload: dict[str, Any]) -> None:
    print(f"\n{len(payload)} keys returned:")
    for key in sorted(payload):
        rendered = json.dumps(payload[key], ensure_ascii=False)
        print(f"  {key:<24} {rendered[:60]}")

    print("\nFETCH coverage:")
    for field, key in FETCHED_FIELD_MAP.items():
        value = payload.get(key)
        status = "FOUND   " if value is not None else "MISSING "
        print(f"  {status} {field:<20} <- {key:<20} = {value}")

    print("\nCOMPUTE fields bolsai also supplies:")
    for field, key in COMPUTED_FIELD_MAP.items():
        value = payload.get(key)
        status = "FOUND   " if value is not None else "MISSING "
        print(f"  {status} {field:<20} <- {key:<20} = {value}")


def report_scale(payload: dict[str, Any]) -> None:
    """Confirm the suspected mixed units: statements in thousands, cap in units."""
    price = payload.get("close_price")
    shares = payload.get("shares_outstanding")
    market_cap = payload.get("market_cap")
    if not (price and shares and market_cap):
        print("\nScale check: not enough fields to verify.")
        return

    implied = Decimal(str(price)) * Decimal(str(shares))
    ratio = implied / Decimal(str(market_cap))
    print(f"\nScale check:  close_price x shares = {implied:.0f}")
    print(f"              market_cap            = {Decimal(str(market_cap)):.0f}")
    print(f"              ratio                 = {ratio:.4f} (1.0 means same units)")

    net_income = payload.get("net_income")
    if net_income:
        as_units = Decimal(str(net_income))
        print(f"\n              net_income           = {as_units:.0f}")
        print(f"              x1000                = {as_units * 1000:.0f}")
        print("              If the second looks like the real figure, statements")
        print("              are in THOUSANDS while market_cap is in units.")


def report_roic_crosscheck(payload: dict[str, Any]) -> None:
    """Recompute bolsai's ROIC with our own pure function.

    Scale-invariant, so the thousands/units question does not matter here: EBIT,
    equity and net debt are all on the same scale.
    """
    missing = [key for key in ("ebit", "equity", "net_debt") if payload.get(key) is None]
    if missing:
        print(f"\nROIC cross-check: skipped, missing {missing}")
        return

    ours = roic(
        ebit=Decimal(str(payload["ebit"])),
        tax_rate=BRAZILIAN_TAX_RATE,
        equity=Decimal(str(payload["equity"])),
        net_debt=Decimal(str(payload["net_debt"])),
    )
    theirs = payload.get("roic")
    print(f"\nROIC cross-check (tax rate {BRAZILIAN_TAX_RATE}):")
    print(f"  shared.indicators.roic() = {ours}")
    print(f"  bolsai roic              = {theirs}")
    if ours is not None and theirs is not None:
        drift = abs(ours - Decimal(str(theirs)))
        verdict = "MATCH" if drift <= Decimal("0.05") else f"DIVERGES by {drift}"
        print(f"  {verdict}")


def report_dividends(payload: dict[str, Any]) -> None:
    print("\nTop-level keys:")
    for key in sorted(payload):
        value = payload[key]
        kind = type(value).__name__
        rendered = json.dumps(value, ensure_ascii=False)
        print(f"  {key:<24} ({kind:<5}) {rendered[:70]}")

    for key, value in payload.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            print(f"\nFirst entry of '{key}':")
            for inner in sorted(value[0]):
                print(f"  {inner:<24} {json.dumps(value[0][inner], ensure_ascii=False)[:60]}")
            break


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker", nargs="?", default="PETR4", help="B3 ticker (default: PETR4)")
    parser.add_argument("--years", default="3", help="Years of dividend history (default: 3)")
    args = parser.parse_args(argv)

    ticker = args.ticker.strip().upper()
    api_key = os.environ.get("BOLSAI_API_KEY", "")
    if not api_key:
        print("BOLSAI_API_KEY is not set. bolsai requires the X-API-Key header.")
        return 1

    print(f"=== bolsai smoke test: {ticker} ===\n")

    with httpx.Client(timeout=TIMEOUT) as client:
        try:
            fundamentals = get(client, f"/fundamentals/{ticker}", api_key)
            if fundamentals is None:
                return 1
            report_fundamentals(fundamentals)
            report_scale(fundamentals)
            report_roic_crosscheck(fundamentals)

            print("\n=== dividends ===\n")
            dividends = get(client, f"/dividends/{ticker}", api_key, years=args.years)
            if dividends is None:
                print("  No dividend data — dividend_yield and payout_ratio stay unavailable.")
                return 0
            report_dividends(dividends)
        except httpx.HTTPError as exc:
            print(f"Request failed: {exc}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
