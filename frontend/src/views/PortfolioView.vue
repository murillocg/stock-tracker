<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { brl, bySignal, listStocks, sumDecimals, type PortfolioTotals, type StockView } from '@/api'
import CheckChips from '@/components/CheckChips.vue'
import HoldingFigures from '@/components/HoldingFigures.vue'
import PortfolioSummary from '@/components/PortfolioSummary.vue'
import CategoryLabel from '@/components/CategoryLabel.vue'
import SignalDot from '@/components/SignalDot.vue'

type Tab = 'PORTFOLIO' | 'WATCHLIST'

const tab = ref<Tab>('PORTFOLIO')
const stocks = ref<StockView[]>([])
const totals = ref<PortfolioTotals | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)

// watchEffect re-runs whenever a ref it read changes — so switching tabs refetches
// with no explicit subscription. Vue's reactivity tracks the dependency itself.
watchEffect(async () => {
  loading.value = true
  error.value = null
  try {
    const data = await listStocks(tab.value)
    stocks.value = data.stocks
    totals.value = data.totals
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not reach the API.'
  } finally {
    loading.value = false
  }
})

type Order = 'weight' | 'signal'

const order = ref<Order>('weight')

// Two useful orderings, and neither is obviously right. By weight answers "where
// is my money", which is the question this app exists for; by signal answers
// "what needs attention". Sorting by weight puts the largest holdings first,
// where a bad signal matters most.
const sorted = computed(() => {
  const list = [...stocks.value]
  if (order.value === 'signal') return list.sort(bySignal)
  return list.sort((a, b) => {
    const wa = Number(a.valuation?.weight ?? -1)
    const wb = Number(b.valuation?.weight ?? -1)
    return wb - wa || a.ticker.localeCompare(b.ticker)
  })
})

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

const collected = computed(() => sorted.value.find((s) => s.current)?.current?.date ?? null)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <h1>Stock Tracker</h1>
      <span v-if="collected" class="subtle">collected {{ collected }}</span>
    </header>

    <nav class="tabs">
      <button :aria-pressed="tab === 'PORTFOLIO'" @click="tab = 'PORTFOLIO'">Portfolio</button>
      <button :aria-pressed="tab === 'WATCHLIST'" @click="tab = 'WATCHLIST'">Watchlist</button>
      <span class="spacer" />
      <button :aria-pressed="order === 'weight'" @click="order = 'weight'">By weight</button>
      <button :aria-pressed="order === 'signal'" @click="order = 'signal'">By signal</button>
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

      <RouterLink
        v-for="stock in group.stocks"
        :key="stock.ticker"
        :to="`/stocks/${stock.ticker}`"
        class="row"
      >
        <SignalDot :signal="stock.evaluation.signal" />
        <span class="ticker">{{ stock.ticker }}</span>
        <CategoryLabel :category="stock.category" />

        <HoldingFigures
          :position="stock.position"
          :valuation="stock.valuation"
          :currency="stock.currency"
          compact
        />

        <!-- Chips only. The explanations live on the detail page, one click
             away: this screen is for comparing twenty holdings, not reading
             about one. -->
        <CheckChips :checks="stock.evaluation.checks" :with-reasons="false" />

        <span class="row-end">
          <span v-if="stock.current" class="price">
            <span class="currency">{{ stock.currency === 'BRL' ? 'R$' : '$' }}</span>
            {{ stock.current.price }}
          </span>
          <span v-else class="price is-empty">—</span>
          <span v-if="stock.valuation?.weight" class="weight">
            {{ stock.valuation.weight }}<small>%</small>
          </span>
          <span v-else class="weight is-empty">—</span>
        </span>
      </RouterLink>
    </section>
  </div>
</template>
