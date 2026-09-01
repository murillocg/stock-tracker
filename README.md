# stock-tracker

Personal stock monitoring for the Brazilian (B3) and US markets, built around
Peter Lynch's investment categories.

It exists to make a monthly decision — *where does this month's contribution
go?* — without turning into a daily habit. It collects one snapshot per weekday
evening, evaluates every holding against rules specific to its category, and
shows the result. Nothing streams, nothing refreshes while you watch it.

Not a trading tool. Not financial advice. One user, one portfolio.

## What it does

**Judges each stock by its own category.** A P/E limit that suits a stalwart is
meaningless for a fast grower, and Lynch's six categories each turn on different
numbers — PEG for a fast grower, dividend yield and payout sustainability for a
slow grower, price-to-book for a cyclical. The category is set by hand: the app
flags, it does not decide.

**Measures headroom against those limits.** Every check is normalised to
"multiples of room" against its own target, so a P/E and an ROE become
comparable, then combined as a geometric mean and shrunk by how many checks
actually fired. A stock judged on one lenient number should not outrank one
judged on three.

**Folds a transaction ledger into positions.** Weighted average cost, the
Brazilian convention: a buy moves the average, a sale leaves it untouched and
books a realised gain, a bonus issue lowers it without costing anything.
Positions are computed **per custodian**, because that is the unit the Brazilian
tax return asks for — the same security at two brokers is two declarations.

**Spans two currencies.** USD holdings are converted at the USD/BRL rate
collected daily from the Banco Central, so a US position and a Brazilian one can
be weighed against each other in one portfolio.

## Architecture

```
collector Lambda  --(weekday 20:00 BRT)-->  DynamoDB  <--  read API Lambda  <--  Vue app
   brapi / bolsai / Alpha Vantage / BCB                          API Gateway      S3 + CloudFront
```

Everything is AWS serverless and sized to the free tier: nothing runs
continuously, and both Lambdas are awake only while doing something.

```
backend/src/shared/       code shared by both Lambdas, deployed as a layer
            models/       Pydantic at the boundaries, camelCase <-> snake_case
            providers/    FETCH: one Protocol per capability, one module per API
            indicators/   COMPUTE: pure functions — data in, data out
            categories/   Lynch rulesets, signals, and the headroom measure
            positions/    ledger -> position -> valuation -> weight
            repository/   Protocol + DynamoDB implementation + in-memory fake
     collector/           fetch -> compute -> store -> alert
           api/           read endpoints for the frontend
frontend/                 Vue 3, <script setup>, Vite, no state library
infra/                    Terraform: every resource, no console clicking
```

Some conventions the code holds to throughout: `typing.Protocol` rather than
ABCs, composition over inheritance, dependencies injected via constructor, pure
functions wherever the work is a calculation, and `Decimal` for every monetary
value — boto3 rejects `float` outright, and JavaScript's float64 is exactly why
the API serialises decimals as strings.

## Data sources

Verified against the live APIs rather than their documentation, which differed:

| Source | Provides | Limit |
|---|---|---|
| [brapi](https://brapi.dev) | B3 prices | free with a token |
| [bolsai](https://bolsai.com.br) | B3 fundamentals | 200 requests/day |
| [Alpha Vantage](https://www.alphavantage.co) | US prices and fundamentals | 25 requests/day |
| [Banco Central do Brasil](https://dadosabertos.bcb.gov.br) | USD/BRL | no credential |

No free source covers both price and fundamentals for a Brazilian ticker, which
is why a stock names its quote provider and its fundamentals provider
separately. Dividend data for B3 is behind a paid plan on both providers, so
those fields are entered by hand where they matter.

Collection is sequential with a pause before every upstream call. Free-tier rate
limits are the binding constraint, not wall-clock time — Alpha Vantage rejects a
second request inside the same second, whatever is making it.

## Running it

```bash
# Backend: lint, type-check, test
cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]"
make check

# Frontend
cd frontend && npm ci && npm run dev

# Deploy — build is a prerequisite of plan and deploy on purpose, because
# Terraform hashes whatever is sitting in backend/build/
make deploy
```

Terraform needs `infra/terraform.tfvars` (provider tokens, alert addresses) and
`infra/backend.hcl` (the state bucket). Both are gitignored; see
[`infra/README.md`](infra/README.md).

## Status

Phases 0–3 are done: collection, evaluation, the read API, the frontend, and the
transaction ledger with per-broker positions and portfolio weights. Income-tax
support and the watchlist copilot come next.

Known gaps, all deliberate: BDRs have no fundamentals from any free source, so
they carry a category but no verdict; realised gains from fully closed broker
accounts are not recoverable without a full-history fold; the price series began
in August 2026, so the 6-month and 1-year change windows are still filling.

## Licence

[MIT](LICENSE).

Market data from brapi, bolsai, Alpha Vantage and the Banco Central do Brasil.
This project would not have a US side without Alpha Vantage's free tier.
