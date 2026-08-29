<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { bySignal, listStocks, type StockView } from '@/api'
import CheckChips from '@/components/CheckChips.vue'
import CategoryLabel from '@/components/CategoryLabel.vue'
import SignalDot from '@/components/SignalDot.vue'

type Tab = 'PORTFOLIO' | 'WATCHLIST'

const tab = ref<Tab>('PORTFOLIO')
const stocks = ref<StockView[]>([])
const error = ref<string | null>(null)
const loading = ref(true)

// watchEffect re-runs whenever a ref it read changes — so switching tabs refetches
// with no explicit subscription. Vue's reactivity tracks the dependency itself.
watchEffect(async () => {
  loading.value = true
  error.value = null
  try {
    stocks.value = (await listStocks(tab.value)).stocks
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not reach the API.'
  } finally {
    loading.value = false
  }
})

// Sorted so what needs attention is at the top. A portfolio view that leads with
// the healthy holdings buries the only rows worth acting on.
const sorted = computed(() => [...stocks.value].sort(bySignal))

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
    </nav>

    <p v-if="loading" class="state">Loading…</p>
    <p v-else-if="error" class="state error">{{ error }}</p>
    <p v-else-if="!sorted.length" class="state">Nothing here yet.</p>

    <RouterLink v-for="stock in sorted" :key="stock.ticker" :to="`/stocks/${stock.ticker}`">
      <article class="card">
        <div class="card-head">
          <SignalDot :signal="stock.evaluation.signal" />
          <span class="ticker">{{ stock.ticker }}</span>
          <span class="name">{{ stock.name }}</span>
          <span v-if="stock.sector" class="sector">{{ stock.sector }}</span>
          <span v-if="stock.current" class="price">
            {{ stock.currency === 'BRL' ? 'R$' : '$' }} {{ stock.current.price }}
          </span>
          <CategoryLabel :category="stock.category" />
        </div>
        <CheckChips :checks="stock.evaluation.checks" />
      </article>
    </RouterLink>
  </div>
</template>
