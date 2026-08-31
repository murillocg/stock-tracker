<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { getStock, type LedgerEntry, type Snapshot, type StockView } from '@/api'
import CheckChips from '@/components/CheckChips.vue'
import HoldingFigures from '@/components/HoldingFigures.vue'
import CategoryLabel from '@/components/CategoryLabel.vue'
import SignalDot from '@/components/SignalDot.vue'

const props = defineProps<{ ticker: string }>()

const stock = ref<StockView | null>(null)
const history = ref<Snapshot[]>([])
const ledger = ref<LedgerEntry[]>([])
const error = ref<string | null>(null)
const loading = ref(true)

watchEffect(async () => {
  loading.value = true
  error.value = null
  try {
    const data = await getStock(props.ticker)
    stock.value = data.stock
    history.value = [...data.history].reverse()
    ledger.value = data.ledger
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not reach the API.'
  } finally {
    loading.value = false
  }
})

type Panel = 'history' | 'transactions'

const panel = ref<Panel>('transactions')

// Rows before the last flat point are shown but carry no running position: the
// holding went to zero there, so nothing earlier bears on today's average.
const preReset = computed(() => ledger.value.filter((entry) => entry.position === null).length)

/** The position after the final trade — the same figure shown at the top. */
const settled = computed(() => ledger.value[ledger.value.length - 1]?.position ?? null)

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
        <HoldingFigures
          :position="stock.position"
          :valuation="stock.valuation"
          :currency="stock.currency"
        />
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
        <nav class="tabs inline">
          <button
            :aria-pressed="panel === 'transactions'"
            @click="panel = 'transactions'"
          >
            Transactions ({{ ledger.length }})
          </button>
          <button :aria-pressed="panel === 'history'" @click="panel = 'history'">
            Price history ({{ history.length }})
          </button>
        </nav>

        <template v-if="panel === 'transactions'">
          <table v-if="ledger.length" class="history ledger">
            <thead>
              <tr>
                <th>date</th>
                <th>type</th>
                <th>broker</th>
                <th class="num">qty</th>
                <th class="num">price</th>
                <th class="num">holding</th>
                <th class="num">average</th>
                <th class="num">invested</th>
              </tr>
            </thead>
            <tbody>
              <!-- The fold made visible. The average is the one figure on this
                   page that cannot be checked by eye — it is the result of every
                   trade in order, and the only way to trust it is to watch it
                   move. The last row is the number shown at the top. -->
              <tr
                v-for="entry in ledger"
                :key="entry.transaction.date + entry.transaction.type + entry.transaction.quantity"
                :class="{ 'is-muted': entry.position === null }"
                :title="entry.transaction.note ?? undefined"
              >
                <td>{{ entry.transaction.date }}</td>
                <td>{{ entry.transaction.type.toLowerCase().replace('_', ' ') }}</td>
                <td>{{ entry.transaction.broker ?? '—' }}</td>
                <td class="num">{{ entry.transaction.quantity }}</td>
                <td class="num">
                  {{ entry.transaction.unitPrice === '0' ? '—' : entry.transaction.unitPrice }}
                </td>
                <td class="num">{{ entry.position?.quantity ?? '—' }}</td>
                <td class="num"><b>{{ entry.position?.averagePrice ?? '—' }}</b></td>
                <td class="num">{{ entry.position?.invested ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="subtle">No transactions recorded for this stock.</p>

          <p v-if="preReset" class="subtle" style="margin-bottom: 0">
            The first {{ preReset }} row(s) are dimmed: the holding went to zero after them,
            so they are real trades but do not bear on today's average.
          </p>
          <p
            v-else-if="settled && settled.realisedGain !== '0.00'"
            class="subtle"
            style="margin-bottom: 0"
          >
            Realised gain to date: {{ settled.realisedGain }} — booked on sales,
            and not part of the average above.
          </p>
        </template>

        <template v-else>
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
        </template>
      </article>

    </template>
  </div>
</template>
