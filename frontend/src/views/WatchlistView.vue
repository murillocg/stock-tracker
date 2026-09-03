<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import {
  brl,
  isNegative,
  listWatchlist,
  num,
  type CollectionStatus,
  type WatchlistItem,
} from '@/api'
import CategoryLabel from '@/components/CategoryLabel.vue'
import CollectionLine from '@/components/CollectionLine.vue'
import RangeGauge from '@/components/RangeGauge.vue'
import SignalDot from '@/components/SignalDot.vue'

const stocks = ref<WatchlistItem[]>([])
const collection = ref<CollectionStatus | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)

watchEffect(async () => {
  loading.value = true
  error.value = null
  try {
    const data = await listWatchlist()
    stocks.value = data.stocks
    collection.value = data.collection
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not reach the API.'
  } finally {
    loading.value = false
  }
})

type Bucket = 'waiting' | 'at-entry' | 'no-entry'

/**
 * Which of the three outcomes a row falls into.
 *
 * The distinction the whole screen exists for: a stock above the price your
 * rules accept is something to wait for; one already below it is something to
 * read the fundamentals on; and one whose failing check is not a price at all is
 * neither — a low return on equity does not go on sale.
 */
function bucket(item: WatchlistItem): Bucket {
  if (item.entry.discountNeeded === null) return 'no-entry'
  return isNegative(item.entry.discountNeeded) ? 'waiting' : 'at-entry'
}

const filter = ref<Bucket | 'all'>('all')

const ordered = computed(() => {
  const rank: Record<Bucket, number> = { waiting: 0, 'at-entry': 1, 'no-entry': 2 }
  return [...stocks.value].sort((a, b) => {
    const byBucket = rank[bucket(a)] - rank[bucket(b)]
    if (byBucket !== 0) return byBucket
    // Within "waiting", the smallest fall first — those are nearest a decision.
    const da = Number(a.entry.discountNeeded ?? 0)
    const db = Number(b.entry.discountNeeded ?? 0)
    return db - da || a.ticker.localeCompare(b.ticker)
  })
})

const shown = computed(() =>
  filter.value === 'all' ? ordered.value : ordered.value.filter((s) => bucket(s) === filter.value),
)

const counts = computed(() => ({
  waiting: stocks.value.filter((s) => bucket(s) === 'waiting').length,
  'at-entry': stocks.value.filter((s) => bucket(s) === 'at-entry').length,
  'no-entry': stocks.value.filter((s) => bucket(s) === 'no-entry').length,
}))

const symbol = (currency: string) => (currency === 'BRL' ? 'R$' : '$')

/**
 * How far the price sits from the limit, as one signed number.
 *
 * The limit is a CEILING, not a target: below it your rules are green, above it
 * they are not. An earlier version headed this column "entry" and showed "at
 * entry" for everything underneath, which read as "you have not got there yet"
 * when it meant the opposite — PLPL3 at R$ 7,61 against a limit of R$ 39,41 is
 * not 80% short of interesting, it is 80% past it.
 *
 * One measure in both directions fixes that. Negative is under the limit and
 * good; positive is over it and is the gap you are waiting on.
 */
function versusLimit(item: WatchlistItem): string {
  const price = item.current?.price
  const limit = item.entry.price
  if (!price || !limit) return '—'
  const gap = (Number(price) / Number(limit) - 1) * 100
  return `${gap >= 0 ? '+' : ''}${gap.toFixed(1).replace('.', ',')}%`
}

/**
 * What still has to happen, for a stock priced above its limit.
 *
 * `discountNeeded` already carries it, and it is the more actionable half of
 * the same fact: "needs a 20,8% fall" beats "26,2% over the limit" when the
 * question is what you are waiting for.
 */
function stillNeeds(item: WatchlistItem): string {
  const move = item.entry.discountNeeded
  return move !== null && isNegative(move) ? `needs ${num(move)}%` : ''
}

function why(item: WatchlistItem): string {
  const { blockedBy, unbounded, price } = item.entry
  if (blockedBy.length) return `${blockedBy.join(', ')} — price cannot fix this`
  if (price === null && unbounded.length) return `${unbounded.join(', ')} too far out to invert`
  if (price === null) return 'not enough data to set a limit'

  // A price far under the limit is not automatically a bargain. PLPL3 sits 81%
  // below its own, on a PEG built from 26% earnings growth — while the market
  // has marked it down 48% in a year. When those two disagree this strongly,
  // one of them is wrong, and the screen should not pretend otherwise.
  const move = item.entry.discountNeeded
  if (move !== null && !isNegative(move) && Number(move) > 200) {
    return 'far under its limit — worth asking why the market disagrees'
  }
  return ''
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <h1>Watchlist</h1>
      <RouterLink to="/" class="subtle">portfolio &rarr;</RouterLink>
    </header>

    <CollectionLine v-if="collection" :collection="collection" />

    <p class="subtle intro">
      <b>Green below</b> is the highest price at which each stock still passes
      its own category's rules &mdash; a ceiling, not a target. Under it is good;
      the ones above it are what you are waiting on. Nothing here is owned, so
      there is no weight and no position.
    </p>

    <nav class="tabs">
      <button :aria-pressed="filter === 'all'" @click="filter = 'all'">
        All ({{ stocks.length }})
      </button>
      <button :aria-pressed="filter === 'waiting'" @click="filter = 'waiting'">
        Waiting ({{ counts.waiting }})
      </button>
      <button :aria-pressed="filter === 'at-entry'" @click="filter = 'at-entry'">
        At entry ({{ counts['at-entry'] }})
      </button>
      <button :aria-pressed="filter === 'no-entry'" @click="filter = 'no-entry'">
        No entry price ({{ counts['no-entry'] }})
      </button>
    </nav>

    <p v-if="loading" class="state">Loading…</p>
    <p v-else-if="error" class="state error">{{ error }}</p>
    <p v-else-if="!shown.length" class="state">Nothing in this group.</p>

    <div v-else class="wl-head">
      <span></span>
      <span></span>
      <span></span>
      <span class="cell">price</span>
      <span class="cell">green below</span>
      <span class="cell">vs limit</span>
      <span class="cell l">52-week range</span>
      <span class="cell">6m</span>
    </div>

    <RouterLink
      v-for="item in shown"
      :key="item.ticker"
      :to="`/stocks/${item.ticker}`"
      class="row watch"
      :class="bucket(item)"
    >
      <SignalDot :signal="item.evaluation.signal" />
      <span class="ticker">{{ item.ticker }}</span>
      <CategoryLabel :category="item.category" />

      <span v-if="item.current" class="cell price">
        <span class="currency">{{ symbol(item.currency) }}</span>
        {{ brl(item.current.price) }}
      </span>
      <span v-else class="cell price is-empty">—</span>

      <span v-if="item.entry.price" class="cell price">
        <span class="currency">{{ symbol(item.currency) }}</span>
        {{ brl(item.entry.price) }}
      </span>
      <span v-else class="cell price is-empty">—</span>

      <span class="cell distance" :title="stillNeeds(item)">{{ versusLimit(item) }}</span>

      <span class="cell l">
        <RangeGauge v-if="item.range52w && item.current" :range="item.range52w" />
        <span v-else class="subtle">—</span>
      </span>

      <span
        class="cell"
        :class="
          item.current?.change6m
            ? isNegative(item.current.change6m)
              ? 'down'
              : 'up'
            : ''
        "
      >
        {{ item.current?.change6m ? num(item.current.change6m) + '%' : '—' }}
      </span>

      <!-- The reason there is no entry price, said out loud rather than left as
           a dash. "ROE below 15 — price cannot fix this" is the most useful
           sentence on this screen. -->
      <span v-if="why(item)" class="reason">{{ why(item) }}</span>
    </RouterLink>
  </div>
</template>
