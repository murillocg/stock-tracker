<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import { getStock, type Snapshot, type StockView } from '@/api'
import CheckChips from '@/components/CheckChips.vue'
import CategoryLabel from '@/components/CategoryLabel.vue'
import SignalDot from '@/components/SignalDot.vue'

const props = defineProps<{ ticker: string }>()

const stock = ref<StockView | null>(null)
const history = ref<Snapshot[]>([])
const error = ref<string | null>(null)
const loading = ref(true)

watchEffect(async () => {
  loading.value = true
  error.value = null
  try {
    const data = await getStock(props.ticker)
    stock.value = data.stock
    history.value = [...data.history].reverse()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not reach the API.'
  } finally {
    loading.value = false
  }
})

const CHANGES = [
  ['1w', 'change1w'],
  ['1m', 'change1m'],
  ['6m', 'change6m'],
  ['1y', 'change1y'],
] as const
</script>

<template>
  <div class="page">
    <header class="page-head">
      <RouterLink to="/" class="subtle">&larr; back</RouterLink>
      <h1>{{ ticker }}</h1>
    </header>

    <p v-if="loading" class="state">Loading…</p>
    <p v-else-if="error" class="state error">{{ error }}</p>

    <template v-else-if="stock">
      <article class="card">
        <div class="card-head">
          <SignalDot :signal="stock.evaluation.signal" with-label />
          <span class="name">{{ stock.name }}</span>
          <span class="labels">
            <span v-if="stock.sector" class="sector">{{ stock.sector }}</span>
            <CategoryLabel :category="stock.category" />
          </span>
          <span v-if="stock.current" class="price">
            <span class="currency">{{ stock.currency === 'BRL' ? 'R$' : '$' }}</span>
            {{ stock.current.price }}
          </span>
        </div>
        <CheckChips :checks="stock.evaluation.checks" />
        <p v-if="stock.current?.referenceDate" class="subtle" style="margin: .8rem 0 0">
          Fundamentals as of {{ stock.current.referenceDate }} — price-based ratios
          are quarter-end, not today.
        </p>
      </article>

      <article v-if="stock.current" class="card">
        <div class="checks">
          <span v-for="[label, key] in CHANGES" :key="key" class="chip">
            {{ label }}
            <strong>{{ stock.current[key] ?? '—' }}%</strong>
          </span>
        </div>
      </article>

      <article class="card">
        <p class="subtle" style="margin-top: 0">History &middot; {{ history.length }} day(s)</p>
        <table v-if="history.length" class="history">
          <thead>
            <tr><th>date</th><th>price</th><th>P/E</th><th>P/B</th><th>ROE</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in history" :key="row.date">
              <td>{{ row.date }}</td>
              <td>{{ row.price }}</td>
              <td>{{ row.pe ?? '—' }}</td>
              <td>{{ row.pb ?? '—' }}</td>
              <td>{{ row.roe ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="subtle">
          Nothing yet. The collector runs once each weekday evening.
        </p>
      </article>
    </template>
  </div>
</template>
