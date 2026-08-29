"""Manual smoke test against the REAL Alpha Vantage API. Not part of the suite.

Runs the same `AlphaVantageProvider` the Lambda runs, with the same httpx client
and User-Agent — so if this works here and fails in Lambda, the source IP is the
only remaining difference.

    export ALPHA_VANTAGE_API_KEY=...
    .venv/bin/python scripts/smoke_alpha_vantage.py MSFT SPCX

Spends 2 of the 25 free daily requests per ticker.
"""

import argparse
import hashlib
import os
import sys

import httpx

from shared.providers import AlphaVantageProvider, ProviderError

TIMEOUT = httpx.Timeout(20.0, connect=5.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", default=["MSFT"], help="US tickers")
    args = parser.parse_args(argv)

    key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not key:
        print("ALPHA_VANTAGE_API_KEY is not set.")
        return 1

    # Fingerprint only — enough to compare against the deployed Lambda's key
    # without either copy ever being printed.
    print(f"key fingerprint: {hashlib.sha1(key.encode()).hexdigest()[:10]}\n")

    failures = 0
    with httpx.Client(timeout=TIMEOUT) as client:
        provider = AlphaVantageProvider(client, api_key=key)

        for ticker in args.tickers:
            symbol = ticker.strip().upper()

            try:
                quote = provider.fetch_quote(symbol)
                print(f"{symbol:<6} quote     OK    price={quote.price}")
            except ProviderError as exc:
                print(f"{symbol:<6} quote     {type(exc).__name__}: {str(exc)[:120]}")
                failures += 1

            try:
                f = provider.fetch_fundamentals(symbol)
                print(
                    f"{symbol:<6} overview  OK    pe={f.pe} pb={f.pb} roe={f.roe} "
                    f"dy={f.dividend_yield} payout={f.payout_ratio} ref={f.reference_date}"
                )
            except ProviderError as exc:
                print(f"{symbol:<6} overview  {type(exc).__name__}: {str(exc)[:120]}")
                failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
