# CLAUDE.md — Stock Tracker

Permanent project context for Claude Code. Read this before any task.

## What this is

A personal stock-monitoring app (Brazilian B3 + US markets) that supports
contribution decisions in a **Buy & Hold / value-investing** style. Not day
trading. The app's goal is to **free me from daily monitoring**: it collects data
once a day, evaluates it, and only notifies me when there's a real decision to
make. Personal use, a single user.

## Usage philosophy (organizes features by cadence)

- **Monthly** — contribution decision: "where do I put this month's money?"
- **Quarterly** — review: when earnings are released, I review every position.
- **Event-driven** — notifications: a meaningful price drop (protection) or a
  watchlist stock that hit its entry point (opportunity).
- **Daily** — this is a hobby and should be discouraged as the app matures.

## Stack (decided — do not reopen unless I ask)

- **Language:** Python (collector + API). Frontend in Angular (TypeScript).
- **Cloud:** all AWS, serverless, free tier, nothing running 24/7.
  - Collection: **Lambda** triggered by **EventBridge Scheduler** (1x/day, end of day).
  - Read API: **Lambda + API Gateway** (serves the Angular app).
  - Database: **DynamoDB** (always-free tier).
  - Frontend hosting: **S3 + CloudFront**.
  - Alert email: **SES**.
  - Permissions: native **IAM** between services.
- **IaC:** **Terraform** (not OpenTofu, though they're compatible).
- **Code versioned on GitHub.**
- **No GraalVM, no Java** — both were evaluated and rejected; Python fits the
  serverless model and the data/scraping tasks better.

## Code conventions (important — I'm a staff engineer in Java, learning Python)

- **Everything in English:** field names, variables, enums, code comments, file
  names. (Conversation with me can be in Portuguese.)
- **Type hints everywhere.** `mypy` must pass clean.
- **Protocol, NOT ABC.** I favor **composition over inheritance**. Abstractions
  (providers, repositories) are `typing.Protocol` — structural conformance, no
  inheritance, no coupling.
- **Dependency injection:** resources (http client, boto3 table, token) are passed
  in via constructor/parameter, never created inside the class. Keeps things testable.
- **Pure functions** where possible (e.g. indicator computation): take data, return
  data, no side effects.
- **Pydantic at the boundaries:** validates what comes in (API) and goes out
  (database/HTTP). Uses `alias` for the **snake_case (Python) <-> camelCase
  (DynamoDB/JSON)** bridge.
- **Repository pattern:** the rest of the code never talks to boto3 directly; it
  talks to a repository. Only the concrete implementation knows the DynamoDB item
  shape.
- **Enums, not magic strings.**
- **Tooling from day one:** `ruff` (lint), `mypy` (types), `pytest` (tests).

## How to work with me (I'm LEARNING Python)

- **Manual mode** (I approve each change). Do not build the whole app at once.
- Go **module by module**, writing AND explaining the reasoning behind each decision.
- Run `pytest` and `mypy` at each step and show me the result.
- I prefer understanding over copying. If I ask "why like this?", explain in depth.
- **Teach as you go.** When a Python concept comes up that differs from what a Java
  developer would expect, call it out and explain it — and **compare it with Java**,
  which is the language I know. Examples worth flagging: `Protocol` vs Java
  interfaces, `str`/`int`/`dict` naming, duck typing, list/dict comprehensions,
  decorators, context managers, `None` vs `null`, dataclasses/Pydantic vs POJOs,
  the GIL, `async`/`await`, virtual envs vs the JVM classpath. Keep these
  explanations short and practical, tied to the code we're writing.

## Code architecture (monorepo)

```
stock-tracker/
├─ infra/            # Terraform (dynamodb, lambda, eventbridge, api_gateway, ses, s3_cloudfront, iam)
├─ backend/
│  ├─ pyproject.toml
│  ├─ src/
│  │  ├─ shared/     # Lambda Layer — code shared by both Lambdas
│  │  │  ├─ models/       # Pydantic: Stock, DailySnapshot, AlertRule + enums
│  │  │  ├─ providers/    # FETCH: Provider Protocol + brapi/bolsai/alpha_vantage + factory
│  │  │  ├─ indicators/   # COMPUTE: roic, payout, peg, growth (pure) + changes (from history)
│  │  │  ├─ categories/   # Lynch rulesets + evaluate()
│  │  │  ├─ repository/   # Protocol + DynamoDB impl (boto3) + in-memory fake for tests
│  │  │  └─ config.py
│  │  ├─ collector/  # LAMBDA 1: handler.py — fetch -> compute -> store -> alert
│  │  └─ api/        # LAMBDA 2: handler.py — read endpoints for Angular
│  └─ tests/
├─ frontend/         # Angular
└─ .github/workflows/
```

## Data model (DynamoDB — 2 tables)

**Table `Stocks`** (registry/state): PK=`ticker`, GSI `listType`->`ticker`.
Fields: name, market (B3/NYSE/NASDAQ), currency (BRL/USD), provider
(BRAPI/BOLSAI/ALPHA_VANTAGE), sector, category (Lynch enum), listType
(PORTFOLIO/WATCHLIST), alertRules (map), current (map — latest denormalized snapshot
so the portfolio lists in a single query).

**Table `DailySnapshots`** (time series): PK=`ticker`, SK=`date` (ISO 8601).
Indicators: price, pe, pb, evEbitda, roe, netDebtToEbitda, dividendYield (these come
from the API — FETCH); roic, payoutRatio, peg, revenueGrowth, earningsGrowth
(computed — COMPUTE); grossMargin, ebitdaMargin; quarter (e.g. "2026Q2");
change1w/1m/6m/1y (computed from our own history). FX enters as a special ticker
`USDBRL`.

Billing: `PAY_PER_REQUEST` (on-demand, no fixed cost).

## Peter Lynch categories (the tag is MANUAL; each uses different indicators)

FAST_GROWER (PEG<1), STALWART (P/E, ROE, debt), SLOW_GROWER (DY + sustainable
payout), CYCLICAL (P/B vs historical band — P/E misleads), TURNAROUND (debt down,
margin inflecting — qualitative), ASSET_PLAY (P/B<1 with real assets). Limits are
PER category, never global. Cyclical and Turnaround require human judgment — the app
flags, it does not decide.

## Collector: TWO steps (not one)

1. **FETCH** — pull ready-made indicators from the API (provider per market).
2. **COMPUTE** — calculate the derived ones (roic, payout, peg, YoY growth) from the
   financial statements, and the changes from the history in DynamoDB.
Collection is **sequential** with a small delay between calls — respects the free-tier
rate limits of the APIs. No parallelism.

## Data sources

- B3: brapi.dev (price + basics, free tier) + bolsai (27 indicators incl. EV/EBITDA
  and Net Debt/EBITDA). Confirm what's in the free tier; whatever isn't, compute from
  the statements.
- US: Alpha Vantage / Finnhub / yfinance (restricted free tiers).
- FX USD/BRL: brapi or the Brazilian Central Bank.
- **Do not scrape oceans14/statusinvest** (they block it and it violates ToS). Use APIs.

## Roadmap (build in this order)

- **Phase 0 — Foundation:** collector + DynamoDB + providers. Thin vertical slice
  first: 1 stock, brapi -> compute -> store. Validates the stack end to end.
- **Phase 1 — MVP:** list portfolio + watchlist with indicators + category tag +
  per-category traffic-light.
- **Phase 2 — Watch:** changes 1w/1m/6m/1y + drop alert >20% (SES).
- **Phase 3 — Transactional:** positions/quantity -> average price -> portfolio weight
  (3rd table). Weight depends on this.
- **Phase 4 — Tax:** income-tax support (evaluate integrating an existing tool vs
  building).
- **Phase 5 — Copilot:** watchlist entry triggers + B3 screener (low frequency to fit
  the free tier) + earnings calendar.

## Dependencies (pyproject)

pydantic, httpx, boto3, ruff, mypy, pytest. No heavy web framework; if the api/ needs
a router, `aws-lambda-powertools`.
