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
  /** Room against this check's own target, as a multiple. 1.0 is at target. */
  headroom: string | null
}

export interface Evaluation {
  ticker: string
  category: LynchCategory | null
  signal: Signal
  checks: Check[]
  /**
   * Room against this category's targets, as one number. Not a score: it knows
   * the ruleset and nothing else — not your weights, not your cash.
   */
  headroom: string | null
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
  peg: string | null
  revenueCagr5y: string | null
  earningsCagr5y: string | null
  referenceDate: string | null
  change1w: string | null
  change1m: string | null
  change6m: string | null
  change1y: string | null
  /** When the collector run that wrote this row started, in UTC. */
  collectedAt: string | null
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

export interface EntryPrice {
  /** Where this stock's own rules would turn green. Null when nothing inverted. */
  price: string | null
  /** Signed % from today's price. Negative means a fall is needed. */
  discountNeeded: string | null
  /** Failing checks that price cannot repair — a low ROE stays low. */
  blockedBy: string[]
  /** Price-based checks too far past their limit to invert meaningfully. */
  unbounded: string[]
}

export interface PriceRange {
  low: string
  high: string
  /** 0 at the 52-week low, 100 at the high. */
  position: string
}

export interface WatchlistItem {
  ticker: string
  name: string
  market: string
  currency: string
  sector: string | null
  category: LynchCategory | null
  isForeign: boolean
  current: Snapshot | null
  evaluation: Evaluation
  entry: EntryPrice
  range52w: PriceRange | null
  /** A valuation from outside the app — shown beside the derived ceiling, never blended. */
  fairValue: string | null
  fairValueSource: string | null
  fairValueOn: string | null
}

export interface CollectionStatus {
  /** When the collector last actually ran. Null for rows written before stamping. */
  lastRun: string | null
  /** Freshest trading day held. Differs from lastRun when a run collected nothing. */
  lastCollected: string | null
  /** Oldest day we hold a price for — lets the UI say "not due yet" vs "missing". */
  historySince: string | null
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

export function listWatchlist() {
  return get<{ stocks: WatchlistItem[]; collection: CollectionStatus | null }>(
    '/stocks?listType=WATCHLIST',
  )
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
  const trimmed = value.trim()
  const negative = trimmed.startsWith('-')
  const [whole = '0', fraction = ''] = trimmed.replace(/^[-+]/, '').split('.')

  // Rounded to cents in integer arithmetic, never through a float — and always
  // padded to two places. The old version sliced the fraction, so a price of
  // "13.1" rendered as "13,1" and "8.0864" silently became "8,08": one looks
  // like a typo, the other is wrong by a rounding.
  const digits = (fraction + '000').slice(0, 3)
  let cents = Number(whole) * 100 + Number(digits.slice(0, 2))
  if (Number(digits[2]) >= 5) cents += 1

  const size = Math.abs(cents)
  const reais = String(Math.floor(size / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  const sign = negative && cents !== 0 ? '-' : ''
  return `${sign}${reais},${String(size % 100).padStart(2, '0')}`
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

/**
 * A ratio or percentage in Brazilian notation, at the precision the API sent.
 *
 * Separate from `brl` because the two have different jobs. `brl` is for money:
 * it rounds to cents, because a price is a price. This is for everything else —
 * P/E, ROE, margins, share counts — where rounding would be inventing a policy
 * the data does not carry. A P/E of 12.1414 is what the provider computed from a
 * quarter-end statement; it becomes 12,1414, not 12,14.
 *
 * Without this the same table spoke two conventions: 53,12 for the price and
 * 12.1414 in the column beside it.
 */
export function num(value: string): string {
  const trimmed = value.trim()
  const negative = trimmed.startsWith('-')
  const [whole = '0', fraction] = trimmed.replace(/^[-+]/, '').split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return `${negative ? '-' : ''}${grouped}${fraction ? `,${fraction}` : ''}`
}

/**
 * `2026-08-31` -> `31/08/2026`.
 *
 * ISO is right for storage — it sorts lexicographically in the same order it
 * sorts chronologically, which is what makes the DailySnapshots sort key work —
 * and wrong for a Brazilian reader. Split textually rather than through `Date`,
 * which would apply a timezone to a value that has none and can shift the day.
 */
export function day(iso: string): string {
  const [year, month, date] = iso.split('-')
  return year && month && date ? `${date}/${month}/${year}` : iso
}

/** Sign of a Decimal string, judged textually — no float conversion involved. */
export function isNegative(value: string): boolean {
  return value.trimStart().startsWith('-')
}

/** Days of price history needed before each change window can be computed. */
export const WINDOW_DAYS = { change1w: 7, change1m: 30, change6m: 182, change1y: 365 } as const

/**
 * How a change column should read: a value, or how long until it can exist.
 *
 * Three days after collection began a one-month change is not missing, it is not
 * due — and a bare dash cannot tell you which. `historySince` is the oldest day
 * we hold a price for.
 */
export function windowState(
  value: string | null,
  window: keyof typeof WINDOW_DAYS,
  historySince: string | null,
): { text: string; pending: boolean } {
  if (value !== null) return { text: `${value}%`, pending: false }
  if (!historySince) return { text: '—', pending: true }

  const days = Math.floor((Date.now() - new Date(`${historySince}T00:00:00`).getTime()) / 86400000)
  const remaining = WINDOW_DAYS[window] - days
  return remaining > 0
    ? { text: `in ${remaining}d`, pending: true }
    : { text: '—', pending: true }
}

/** Rank for sorting: the things needing attention first, the fine ones last. */
// Best first. This screen answers "where does this month's money go?", so the
// buy candidates belong at the top; hunting for them past twelve reds was the
// list working against the decision it exists for.
//
// The first four mirror `_SEVERITY` in shared/categories/signals.py exactly,
// which is what makes NEEDS_REVIEW rank better than RED — "go and look at this"
// is a milder verdict than a clear red flag.
//
// INSUFFICIENT_DATA and NOT_APPLICABLE are appended rather than ranked: neither
// is a degree of goodness, and a holding we cannot judge is not a candidate for
// this month's contribution. They sort last so they stay out of the way.
const SIGNAL_ORDER: Record<Signal, number> = {
  GREEN: 0,
  YELLOW: 1,
  NEEDS_REVIEW: 2,
  RED: 3,
  INSUFFICIENT_DATA: 4,
  NOT_APPLICABLE: 5,
}

export function bySignal(a: StockView, b: StockView): number {
  const diff = SIGNAL_ORDER[a.evaluation.signal] - SIGNAL_ORDER[b.evaluation.signal]
  return diff !== 0 ? diff : a.ticker.localeCompare(b.ticker)
}
