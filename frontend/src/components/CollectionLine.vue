<script setup lang="ts">
import { computed } from 'vue'
import { relativeTime, type CollectionStatus } from '@/api'

const props = defineProps<{ collection: CollectionStatus }>()

/** A run stamp if we have one, otherwise the trading day it collected. */
const last = computed(() => {
  const { lastRun, lastCollected } = props.collection
  if (lastRun) return { text: new Date(lastRun).toLocaleString(), hint: relativeTime(lastRun) }
  if (lastCollected) return { text: lastCollected, hint: '' }
  return null
})

const next = computed(() => {
  const { nextRun } = props.collection
  if (!nextRun) return null
  return { text: new Date(nextRun).toLocaleString(), hint: relativeTime(nextRun) }
})

// A run that fails every ticker still runs, so these two can disagree — and when
// they do, that gap is the most useful thing on the screen. Only worth saying
// out loud when it is more than a day, since a run late on the 31st legitimately
// carries the 31st's data.
const stale = computed(() => {
  const { lastRun, lastCollected } = props.collection
  if (!lastRun || !lastCollected) return false
  const gap = new Date(lastRun).getTime() - new Date(`${lastCollected}T23:59:59`).getTime()
  return gap > 24 * 60 * 60 * 1000
})
</script>

<template>
  <p class="collection subtle">
    <span v-if="last">
      collected <b>{{ last.text }}</b>
      <template v-if="last.hint"> · {{ last.hint }}</template>
    </span>
    <span v-else>no data collected yet</span>

    <span v-if="next" class="sep">
      next run <b>{{ next.text }}</b> · {{ next.hint }}
    </span>

    <span v-if="stale" class="sep warn">
      the last run brought back nothing newer than {{ collection.lastCollected }}
    </span>
  </p>
</template>
