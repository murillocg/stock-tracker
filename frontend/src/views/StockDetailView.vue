<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { getStock, type BrokerLedger, type Snapshot, type StockView } from '@/api'
import CheckChips from '@/components/CheckChips.vue'
import HoldingFigures from '@/components/HoldingFigures.vue'
import CategoryLabel from '@/components/CategoryLabel.vue'
import SignalDot from '@/components/SignalDot.vue'

const props = defineProps<{ ticker: string }>()

const stock = ref<StockView | null>(null)
const history = ref<Snapshot[]>([])
const ledgers = ref<BrokerLedger[]>([])
const error = ref<string | null>(null)
const loading = ref(true)

watchEffect(async () => {
  loading.value = true
  error.value = null
  try {
    const data = await getStock(props.ticker)
    stock.value = data.stock
    history.value = [...data.history].reverse()
    ledgers.value = data.ledgers
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not reach the API.'
  } finally {
    loading.value = false
  }
})

type Panel = 'history' | 'transactions'

const panel = ref<Panel>('transactions')

const rowCount = computed(() =>
  ledgers.value.reduce((total, ledger) => total + ledger.entries.length, 0),
)

// Rows before the last flat point are shown but carry no running position: the
// holding went to zero there, so nothing earlier bears on today's average.
const preReset = (ledger: BrokerLedger) =>
  ledger.entries.filter((entry) => entry.position === null).length

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
          :priced="Boolean(stock.current)"
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
            Transactions ({{ rowCount }})
          </button>
          <button :aria-pressed="panel === 'history'" @click="panel = 'history'">
            Price history ({{ history.length }})
          </button>
        </nav>

        <template v-if="panel === 'transactions'">
          <!-- One block per custodian, because that is the unit the Brazilian
               tax return asks for: Bens e Direitos takes an entry per
               institution, each with its own quantity and average cost. The
               blended figure at the top of this page answers a different
               question — how much of the portfolio sits in this company. -->
          <section v-for="ledger in ledgers" :key="ledger.broker ?? 'none'" class="broker">
            <header class="group-head">
              <h2>{{ ledger.broker ?? 'no broker recorded' }}</h2>
              <span v-if="ledger.position" class="subtle">
                {{ ledger.position.quantity }} @ {{ ledger.position.averagePrice }}
                &middot; {{ ledger.position.invested }} invested
              </span>
              <span v-else class="subtle">closed &mdash; nothing held here now</span>
            </header>

            <table class="history ledger">
              <thead>
                <tr>
                  <th>date</th>
                  <th>type</th>
                  <th class="num">qty</th>
                  <th class="num">price</th>
                  <th class="num">holding</th>
                  <th class="num">average</th>
                  <th class="num">invested</th>
                </tr>
              </thead>
              <tbody>
                <!-- The fold made visible. The average is the one figure here
                     that cannot be checked by eye — it is the result of every
                     trade in order, and the only way to trust it is to watch it
                     move. -->
                <tr
                  v-for="entry in ledger.entries"
                  :key="entry.transaction.date + entry.transaction.type + entry.transaction.quantity"
                  :class="{ 'is-muted': entry.position === null }"
                  :title="entry.transaction.note ?? undefined"
                >
                  <td>{{ entry.transaction.date }}</td>
                  <td>{{ entry.transaction.type.toLowerCase().replace('_', ' ') }}</td>
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

            <p v-if="preReset(ledger)" class="subtle footnote">
              The first {{ preReset(ledger) }} row(s) are dimmed: the holding at this broker
              went to zero after them, so they are real trades but do not bear on the
              average above.
            </p>
            <p
              v-else-if="ledger.position && ledger.position.realisedGain !== '0.00'"
              class="subtle footnote"
            >
              Realised gain here: {{ ledger.position.realisedGain }} — booked on sales,
              and not part of the average.
            </p>
          </section>

          <p v-if="!ledgers.length" class="subtle">No transactions recorded for this stock.</p>
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
