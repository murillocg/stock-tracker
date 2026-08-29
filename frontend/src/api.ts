/**
 * Client for the read API, plus the types it returns.
 *
 * Numbers arrive as STRINGS, not numbers. That is deliberate on the server side:
 * JavaScript numbers are float64, so parsing "4.2084" into one would reintroduce
 * exactly the precision problem Decimal exists to prevent. Render the string as
 * it is; only parse where you genuinely need to compute (charts, sorting).
 */

export type Signal =
  | 'GREEN'
  | 'YELLOW'
  | 'RED'
  | 'NEEDS_REVIEW'
  | 'INSUFFICIENT_DATA'
  | 'NOT_APPLICABLE'

export type LynchCategory =
  | 'FAST_GROWER'
  | 'STALWART'
  | 'SLOW_GROWER'
  | 'CYCLICAL'
  | 'TURNAROUND'
  | 'ASSET_PLAY'

export interface Check {
  name: string
  value: string | null
  signal: Signal
  explanation: string
}

export interface Evaluation {
  ticker: string
  category: LynchCategory | null
  signal: Signal
  checks: Check[]
}

export interface Snapshot {
  ticker: string
  date: string
  price: string
  pe: string | null
  pb: string | null
  evEbitda: string | null
  roe: string | null
  roic: string | null
  netDebtToEbitda: string | null
  dividendYield: string | null
  payoutRatio: string | null
  grossMargin: string | null
  ebitdaMargin: string | null
  revenueCagr5y: string | null
  earningsCagr5y: string | null
  referenceDate: string | null
  change1w: string | null
  change1m: string | null
  change6m: string | null
  change1y: string | null
}

export interface StockView {
  ticker: string
  name: string
  market: string
  currency: string
  sector: string | null
  category: LynchCategory | null
  listType: 'PORTFOLIO' | 'WATCHLIST'
  current: Snapshot | null
  evaluation: Evaluation
}

const BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`)
  if (!response.ok) {
    // The API always returns {"message": "..."} on error, so surface that rather
    // than a bare status code the user cannot act on.
    const body = (await response.json().catch(() => null)) as { message?: string } | null
    throw new Error(body?.message ?? `Request failed (${response.status})`)
  }
  return (await response.json()) as T
}

export function listStocks(listType?: 'PORTFOLIO' | 'WATCHLIST') {
  const query = listType ? `?listType=${listType}` : ''
  return get<{ stocks: StockView[] }>(`/stocks${query}`)
}

export function getStock(ticker: string, days = 90) {
  return get<{ stock: StockView; history: Snapshot[] }>(`/stocks/${ticker}?days=${days}`)
}

/** Rank for sorting: the things needing attention first, the fine ones last. */
const SIGNAL_ORDER: Record<Signal, number> = {
  RED: 0,
  YELLOW: 1,
  NEEDS_REVIEW: 2,
  INSUFFICIENT_DATA: 3,
  GREEN: 4,
  NOT_APPLICABLE: 5,
}

export function bySignal(a: StockView, b: StockView): number {
  const diff = SIGNAL_ORDER[a.evaluation.signal] - SIGNAL_ORDER[b.evaluation.signal]
  return diff !== 0 ? diff : a.ticker.localeCompare(b.ticker)
}
