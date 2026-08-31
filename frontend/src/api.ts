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

export interface Position {
  ticker: string
  currency: string
  quantity: string
  averagePrice: string | null
  invested: string
  realisedGain: string
}

export interface Valuation {
  /** In the STOCK's own currency, so a US row matches what the broker shows. */
  marketValue: string
  unrealisedGain: string
  unrealisedGainPercent: string
  /** Share of the portfolio. Null when no exchange rate was collected for it. */
  weight: string | null
  /** `marketValue` in the portfolio's base currency, at today's rate. */
  baseMarketValue: string | null
  /**
   * `invested` at TODAY's rate — not the cost in reais, which would need the
   * rate on each purchase date. Do not label this a cost basis.
   */
  baseInvested: string | null
}

export interface PortfolioTotals {
  invested: string
  marketValue: string
  unrealisedGain: string
  unrealisedGainPercent: string
  currency: string
  priced: number
  unpriced: number
}

export interface CollectionStatus {
  /** When the collector last actually ran. Null for rows written before stamping. */
  lastRun: string | null
  /** Freshest trading day held. Differs from lastRun when a run collected nothing. */
  lastCollected: string | null
  /** Null when the schedule is one the API cannot read — silence beats a wrong time. */
  nextRun: string | null
  timezone: string
}

export interface StockView {
  ticker: string
  name: string
  market: string
  currency: string
  sector: string | null
  category: LynchCategory | null
  listType: 'PORTFOLIO' | 'WATCHLIST'
  /** Where the business is, not where the ticker trades — MSFT34 is foreign. */
  isForeign: boolean
  current: Snapshot | null
  evaluation: Evaluation
  position: Position | null
  valuation: Valuation | null
}

export interface Transaction {
  ticker: string
  date: string
  type: 'BUY' | 'SELL' | 'BONUS' | 'TRANSFER_IN' | 'TRANSFER_OUT'
  quantity: string
  unitPrice: string
  currency: string
  broker: string | null
  note: string | null
}

export interface LedgerEntry {
  transaction: Transaction
  /** The position after this trade. Null before the last flat point. */
  position: Position | null
}

export interface BrokerLedger {
  broker: string | null
  entries: LedgerEntry[]
  /** This custodian's holding today. Null once they hold none of it. */
  position: Position | null
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
  return get<{
    stocks: StockView[]
    totals: PortfolioTotals | null
    collection: CollectionStatus | null
  }>(`/stocks${query}`)
}

export function getStock(ticker: string, days = 90) {
  return get<{ stock: StockView; history: Snapshot[]; ledgers: BrokerLedger[] }>(
    `/stocks/${ticker}?days=${days}`,
  )
}

/** Format a Decimal-as-string for display, without ever parsing it to a float. */
export function brl(value: string): string {
  const [whole = '0', fraction = '00'] = value.split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return `${grouped},${fraction.slice(0, 2)}`
}

/**
 * Add Decimal strings exactly, via integer cents.
 *
 * The API sends Decimals as text precisely so they are never float64, and
 * `0.1 + 0.2 === 0.30000000000000004` is what would leak into a section
 * subtotal. Cents are integers, and a portfolio would need to pass R$90
 * trillion before it reached the limit of an exact integer in JavaScript.
 */
export function sumDecimals(values: string[]): string {
  const cents = values.reduce((total, value) => {
    const [whole = '0', fraction = ''] = value.split('.')
    const magnitude = Math.abs(Number(whole)) * 100 + Number((fraction + '00').slice(0, 2))
    return total + (whole.startsWith('-') ? -magnitude : magnitude)
  }, 0)
  const abs = Math.abs(cents)
  return `${cents < 0 ? '-' : ''}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, '0')}`
}

/**
 * "in 3h", "in 2 days", "4 hours ago" — a distance, not a timestamp.
 *
 * The question behind the next-run line is "is my data about to change?", and a
 * duration answers it without the reader doing date arithmetic in their head.
 */
export function relativeTime(iso: string): string {
  const target = new Date(iso).getTime()
  if (Number.isNaN(target)) return ''
  const minutes = Math.round((target - Date.now()) / 60000)
  const ahead = minutes >= 0
  const size = Math.abs(minutes)

  const [amount, unit] =
    size < 60
      ? [size, 'minute']
      : size < 60 * 24
        ? [Math.round(size / 60), 'hour']
        : [Math.round(size / (60 * 24)), 'day']

  const plural = `${amount} ${unit}${amount === 1 ? '' : 's'}`
  return ahead ? `in ${plural}` : `${plural} ago`
}

/** Sign of a Decimal string, judged textually — no float conversion involved. */
export function isNegative(value: string): boolean {
  return value.trimStart().startsWith('-')
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
