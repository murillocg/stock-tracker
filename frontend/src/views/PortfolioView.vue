<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  brl,
  bySignal,
  isNegative,
  num,
  listStocks,
  sumDecimals,
  windowState,
  type CollectionStatus,
  type PortfolioTotals,
  type StockView,
} from '@/api'
import CheckChips from '@/components/CheckChips.vue'
import CollectionLine from '@/components/CollectionLine.vue'
import HeadroomBar from '@/components/HeadroomBar.vue'
import HoldingFigures from '@/components/HoldingFigures.vue'
import PortfolioSummary from '@/components/PortfolioSummary.vue'
import CategoryLabel from '@/components/CategoryLabel.vue'
import SignalDot from '@/components/SignalDot.vue'

const stocks = ref<StockView[]>([])
const totals = ref<PortfolioTotals | null>(null)
const collection = ref<CollectionStatus | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)

// Fetched once. It used to be a watchEffect keyed on the list-type tab, which is
// what made switching to the watchlist blank this page while it refetched — the
// watchlist is its own route now, so there is nothing to react to.
onMounted(async () => {
  loading.value = true
  error.value = null
  try {
    const data = await listStocks('PORTFOLIO')
    stocks.value = data.stocks
    totals.value = data.totals
    collection.value = data.collection
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not reach the API.'
  } finally {
    loading.value = false
  }
})

type View = 'decide' | 'review'
type Order = 'weight' | 'signal' | 'headroom'

const VIEW_KEY = 'stock-tracker.view'

// localStorage can throw outright — a private window, a thumbnail capture, a
// browser set to block site data — so every read and write is guarded and the
// page renders correctly with nothing stored.
function storedView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === 'review' ? 'review' : 'decide'
  } catch {
    return 'decide'
  }
}

const view = ref<View>(storedView())
const order = ref<Order>(view.value === 'decide' ? 'headroom' : 'weight')

// The two views answer different questions, so each opens on the sort that
// serves its own: Decide leads with the most room against target, Review with
// the largest position. Switching resets the sort on purpose — carrying the
// other view's ordering across is what made the old single screen confusing.
watch(view, (next) => {
  order.value = next === 'decide' ? 'headroom' : 'weight'
  try {
    localStorage.setItem(VIEW_KEY, next)
  } catch {
    // A remembered tab is a convenience, not state worth failing over.
  }
})

// Two useful orderings, and neither is obviously right. By weight answers "where
// is my money", which is the question this app exists for; by signal answers
// "what needs attention". Sorting by weight puts the largest holdings first,
// where a bad signal matters most.
const descending = (get: (s: StockView) => string | null | undefined) => (a: StockView, b: StockView) =>
  Number(get(b) ?? -1) - Number(get(a) ?? -1) || a.ticker.localeCompare(b.ticker)

const sorted = computed(() => {
  const list = [...stocks.value]
  if (order.value === 'signal') return list.sort(bySignal)
  if (order.value === 'headroom') return list.sort(descending((s) => s.evaluation.headroom))
  return list.sort(descending((s) => s.valuation?.weight))
})

/** A change column reads as a value, or as how long until it can have one. */
const change = (stock: StockView, window: 'change1w' | 'change1m') =>
  windowState(stock.current?.[window] ?? null, window, collection.value?.historySince ?? null)

/**
 * Green up, red down — and neutral for exactly zero, which is neither. Judged
 * from the raw string rather than the rendered text, so it does not depend on
 * how the number happens to be formatted.
 */
function direction(stock: StockView, window: 'change1w' | 'change1m'): string {
  const raw = stock.current?.[window]
  if (raw === null || raw === undefined) return ''
  if (Number(raw) === 0) return 'flat'
  return isNegative(raw) ? 'down' : 'up'
}

function subtotal(group: StockView[]) {
  const pick = (get: (s: StockView) => string | null | undefined) =>
    group.map(get).filter((v): v is string => typeof v === 'string')
  return {
    value: sumDecimals(pick((s) => s.valuation?.baseMarketValue)),
    weight: sumDecimals(pick((s) => s.valuation?.weight)),
  }
}

// Split by where the BUSINESS is, not where the ticker trades. That is what puts
// MSFT34 beside MSFT instead of beside VALE3 — you hold Microsoft twice, and a
// split by listing would hide it across two sections. It also keeps INBR32 on the
// Brazilian side, where Banco Inter belongs, despite being a BDR like the others.
const groups = computed(() =>
  [
    { key: 'BR', title: 'Brazilian', stocks: sorted.value.filter((s) => !s.isForeign) },
    { key: 'INTL', title: 'International', stocks: sorted.value.filter((s) => s.isForeign) },
  ]
    .filter((group) => group.stocks.length > 0)
    .map((group) => ({ ...group, ...subtotal(group.stocks) })),
)

</script>

<template>
  <div class="page">
    <header class="page-head">
      <h1>Portfolio</h1>
      <RouterLink to="/watchlist" class="subtle">watchlist &rarr;</RouterLink>
    </header>

    <CollectionLine v-if="collection" :collection="collection" />

    <nav class="tabs">
      <span class="spacer" />
      <!-- Two questions, two views. Decide is "where does this month's money
           go?"; Review is "how is everything holding up?". The old single screen
           was answering both at once, which is why nothing on it could be
           compared. -->
      <button :aria-pressed="view === 'decide'" @click="view = 'decide'">Decide</button>
      <button :aria-pressed="view === 'review'" @click="view = 'review'">Review</button>
    </nav>

    <PortfolioSummary v-if="totals" :totals="totals" />

    <p v-if="loading" class="state">Loading…</p>
    <p v-else-if="error" class="state error">{{ error }}</p>
    <p v-else-if="!sorted.length" class="state">Nothing here yet.</p>

    <section v-for="group in groups" :key="group.key" class="group">
      <header class="group-head">
        <h2>{{ group.title }}</h2>
        <span class="subtle">
          {{ group.stocks.length }} &middot; R$ {{ brl(group.value) }} &middot;
          {{ group.weight }}% of the portfolio
        </span>
      </header>

      <div v-if="view === 'decide'" class="row head-row">
        <span></span>
        <span></span>
        <span></span>
        <button class="sortable" :aria-pressed="order === 'headroom'" @click="order = 'headroom'">
          headroom
        </button>
        <span class="col-head">1w</span>
        <span class="col-head">1m</span>
        <span class="col-head">price</span>
        <button class="sortable" :aria-pressed="order === 'weight'" @click="order = 'weight'">
          weight
        </button>
      </div>

      <RouterLink
        v-for="stock in group.stocks"
        :key="stock.ticker"
        :to="`/stocks/${stock.ticker}`"
        class="row"
        :class="view"
      >
        <SignalDot :signal="stock.evaluation.signal" />
        <span class="ticker">{{ stock.ticker }}</span>
        <CategoryLabel :category="stock.category" />

        <template v-if="view === 'decide'">
          <HeadroomBar :headroom="stock.evaluation.headroom" />
          <span
            v-for="w in (['change1w', 'change1m'] as const)"
            :key="w"
            class="cell"
            :class="[direction(stock, w), { pending: change(stock, w).pending }]"
            :title="change(stock, w).pending ? 'Not enough price history yet.' : ''"
          >
            {{ change(stock, w).text }}
          </span>
          <span v-if="stock.current" class="cell price">
            <span class="currency">{{ stock.currency === 'BRL' ? 'R$' : '$' }}</span>
            {{ brl(stock.current.price) }}
          </span>
          <span v-else class="cell price is-empty">—</span>
          <span v-if="stock.valuation?.weight" class="cell weight">
            {{ num(stock.valuation.weight) }}<small>%</small>
          </span>
          <span v-else class="cell weight is-empty">—</span>
        </template>

        <template v-else>
          <HoldingFigures
            :position="stock.position"
            :valuation="stock.valuation"
            :currency="stock.currency"
            :priced="Boolean(stock.current)"
            compact
          />
          <CheckChips :checks="stock.evaluation.checks" :with-reasons="false" />
          <span class="row-end">
            <span v-if="stock.current" class="price">
              <span class="currency">{{ stock.currency === 'BRL' ? 'R$' : '$' }}</span>
              {{ brl(stock.current.price) }}
            </span>
            <span v-else class="price is-empty">—</span>
            <span v-if="stock.valuation?.weight" class="weight">
              {{ num(stock.valuation.weight) }}<small>%</small>
            </span>
            <span v-else class="weight is-empty">—</span>
          </span>
        </template>
      </RouterLink>
    </section>
  </div>
</template>
