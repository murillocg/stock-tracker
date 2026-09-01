<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import {
  brl,
  day,
  getStock,
  num,
  type BrokerLedger,
  type Snapshot,
  type StockView,
} from '@/api'
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

const panel = ref<Panel>('history')

const rowCount = computed(() =>
  ledgers.value.reduce((total, ledger) => total + ledger.entries.length, 0),
)

// Rows before the last flat point are shown but carry no running position: the
// holding went to zero there, so nothing earlier bears on today's average.
const preReset = (ledger: BrokerLedger) =>
  ledger.entries.filter((entry) => entry.position === null).length

// Every indicator the snapshot can carry, in the order they belong on screen:
// valuation, then returns, then leverage, then margins, then growth. The table
// showed three of these and hid the other eight for no reason.
const INDICATORS = [
  ['price', 'price'],
  ['pe', 'P/E'],
  ['pb', 'P/B'],
  ['evEbitda', 'EV/EBITDA'],
  ['roe', 'ROE'],
  ['roic', 'ROIC'],
  ['netDebtToEbitda', 'Net debt/EBITDA'],
  ['grossMargin', 'Gross margin'],
  ['ebitdaMargin', 'EBITDA margin'],
  ['dividendYield', 'Div. yield'],
  ['payoutRatio', 'Payout'],
  ['peg', 'PEG'],
  ['revenueCagr5y', 'Rev. CAGR 5y'],
  ['earningsCagr5y', 'Earn. CAGR 5y'],
] as const satisfies readonly (readonly [keyof Snapshot, string])[]

// Only the columns this stock actually has. A B3 stock carries eleven of these
// and a US one carries five; a fixed table would give every US stock six columns
// of dashes, which reads as broken data rather than a different provider.
const columns = computed(() =>
  INDICATORS.filter(([key]) => history.value.some((row) => row[key] !== null)),
)

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
            {{ brl(stock.current.price) }}
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
            <strong>{{ stock.current[key] === null ? '—' : num(stock.current[key]!) }}%</strong>
          </span>
        </div>
      </article>

      <article class="card">
        <nav class="tabs inline">
          <button :aria-pressed="panel === 'history'" @click="panel = 'history'">
            Price history ({{ history.length }})
          </button>
          <button :aria-pressed="panel === 'transactions'" @click="panel = 'transactions'">
            Transactions ({{ rowCount }})
          </button>
        </nav>

        <template v-if="panel === 'history'">
          <div v-if="history.length" class="scroller">
            <table class="history">
              <thead>
                <tr>
                  <th>date</th>
                  <th v-for="[key, label] in columns" :key="key" class="num">{{ label }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in history" :key="row.date">
                  <td>{{ day(row.date) }}</td>
                  <td v-for="[key] in columns" :key="key" class="num">
                    {{ key === 'price' ? brl(row.price) : row[key] === null ? '—' : num(row[key]!) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="subtle">
            Nothing yet. The collector runs once each weekday evening.
          </p>
        </template>
        <template v-else>
          <!-- One block per custodian, because that is the unit the Brazilian
               tax return asks for: Bens e Direitos takes an entry per
               institution, each with its own quantity and average cost. The
               blended figure at the top of this page answers a different
               question — how much of the portfolio sits in this company. -->
          <section v-for="ledger in ledgers" :key="ledger.broker ?? 'none'" class="broker">
            <header class="group-head">
              <h2>{{ ledger.broker ?? 'no broker recorded' }}</h2>
              <span v-if="ledger.position" class="subtle">
                {{ num(ledger.position.quantity) }} @ {{ brl(ledger.position.averagePrice ?? '0') }}
                &middot; {{ brl(ledger.position.invested) }} invested
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
                  <td>{{ day(entry.transaction.date) }}</td>
                  <td>{{ entry.transaction.type.toLowerCase().replace('_', ' ') }}</td>
                  <td class="num">{{ num(entry.transaction.quantity) }}</td>
                  <td class="num">
                    {{ entry.transaction.unitPrice === '0' ? '—' : brl(entry.transaction.unitPrice) }}
                  </td>
                  <td class="num">{{ entry.position ? num(entry.position.quantity) : '—' }}</td>
                  <td class="num">
                    <b>{{ entry.position ? brl(entry.position.averagePrice ?? '0') : '—' }}</b>
                  </td>
                  <td class="num">
                    {{ entry.position ? brl(entry.position.invested) : '—' }}
                  </td>
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
              Realised gain here: {{ brl(ledger.position.realisedGain) }} — booked on sales,
              and not part of the average.
            </p>
          </section>

          <p v-if="!ledgers.length" class="subtle">No transactions recorded for this stock.</p>
        </template>

      </article>

    </template>
  </div>
</template>
