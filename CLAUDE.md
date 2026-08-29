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

- **Language:** Python (collector + API). Frontend in **Vue 3 (TypeScript)**.
  - Angular was the original choice and was reconsidered on 2026-08-29. The app is
    four read-only screens for one user; Angular's ceremony is not repaid at that
    size, and learning it alongside Python and serverless is a third curve at once.
    Vue ships fastest with official router/store and a gentle learning curve.
    Use `<script setup>` + Composition API, Vite, Pinia only if state demands it.
- **Cloud:** all AWS, serverless, free tier, nothing running 24/7.
  - Collection: **Lambda** triggered by **EventBridge Scheduler** (1x/day, end of day).
  - Read API: **Lambda + API Gateway** (serves the Vue app).
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
│  │  └─ api/        # LAMBDA 2: handler.py — read endpoints for the Vue app
│  └─ tests/
├─ frontend/         # Vue 3 + Vite (TypeScript)
└─ .github/workflows/
```

## Data model (DynamoDB — 2 tables)

**Table `Stocks`** (registry/state): PK=`ticker`, GSI `listType`->`ticker`.
Fields: name, market (B3/NYSE/NASDAQ), currency (BRL/USD), **quoteProvider**
(daily price) and **fundamentalsProvider** (optional, statement indicators) — two
fields because no free source covers both, sector, category (Lynch enum), listType
(PORTFOLIO/WATCHLIST), alertRules (map), current (map — latest denormalized snapshot
so the portfolio lists in a single query).

**Table `DailySnapshots`** (time series): PK=`ticker`, SK=`date` (ISO 8601).
Indicators: price, pe, pb, evEbitda, roe, netDebtToEbitda, dividendYield (these come
from the API — FETCH); roic, payoutRatio, peg, revenueCagr5y, earningsCagr5y
(computed — COMPUTE); grossMargin, ebitdaMargin; referenceDate (statement date,
e.g. "2026-06-30"); change1w/1m/6m/1y (computed from our own history). FX enters as
a special ticker `USDBRL`.

Two naming decisions, both settled against live API data:
- **`referenceDate`, not `quarter`** — a `2026Q2` label is lossy and wrong for US
  tickers whose fiscal year is not the calendar year (Apple's fiscal Q2 ends in
  March). The date is the fact; the label is presentation, derived at render time.
- **`revenueCagr5y` / `earningsCagr5y`, not `revenueGrowth` / `earningsGrowth`** —
  bolsai supplies 5-year CAGR, not year-over-year, and PEG means different things
  depending on which one feeds it. The field name says which.

`dividendYield` and `payoutRatio` have **no free data source** (brapi gates them
behind Pro at R$139,99/mo; bolsai's `/dividends` endpoint is Pro-only). They stay
empty, which makes SLOW_GROWER the one category we cannot fully judge yet.

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

- B3 — **verified against the live APIs, 2026-08-28:**
  - **brapi.dev = price only.** Free plan returns `regularMarketPrice`,
    `priceEarnings`, `earningsPerShare`, `marketCap`. All fundamentals live in the
    `defaultKeyStatistics` / `financialData` modules, which are **Pro at
    R$139,99/mo**. PETR4, MGLU3, VALE3 and ITUB4 answer anonymously with all
    resources — do not draw conclusions from those four; every other ticker 401s
    without a token.
  - **bolsai = fundamentals.** `GET /fundamentals/{ticker}` with an `X-API-Key`
    header, 200 req/day free. Supplies P/L, P/VP, EV/EBITDA, ROE, ROIC, Net
    Debt/EBITDA and margins, **already as percentages** (28.26, not 0.2826) —
    matching our own convention. Its ROIC reproduces exactly from
    `shared.indicators.roic()` with a 34% tax rate.
    Two traps: raw statement figures are in **thousands** of BRL while
    `market_cap`/`close_price` are in units; and its price-based ratios are as of
    `reference_date` (quarter end), not today.
  - **No free source for dividends.** brapi gates them behind Pro; bolsai's
    `/dividends` answers 403 on the free plan. `dividendYield` and `payoutRatio`
    stay empty.
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
