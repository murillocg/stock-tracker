<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ headroom: string | null }>()

// Deliberately not parsed for arithmetic — only to place a bar and pick a
// colour, neither of which a float error can spoil.
const value = computed(() => (props.headroom === null ? null : Number(props.headroom)))

// 2.5 is the top of the visible scale rather than the clamp ceiling of 4: no
// real holding gets near 4, and scaling to it would squash every bar into the
// left third where none of them could be told apart.
const width = computed(() => (value.value === null ? 0 : Math.min(100, (value.value / 2.5) * 100)))

const tone = computed(() => {
  if (value.value === null) return 'none'
  if (value.value >= 1.5) return 'good'
  if (value.value >= 1) return 'ok'
  return value.value >= 0.8 ? 'warn' : 'bad'
})

const shown = computed(() =>
  props.headroom === null ? '—' : Number(props.headroom).toFixed(2).replace('.', ','),
)
</script>

<template>
  <span
    class="headroom"
    :class="tone"
    :title="
      headroom === null
        ? 'No check in this category could be measured against a threshold.'
        : `${shown}x the room against this category's own targets. 1,00 is exactly at target.`
    "
  >
    <span class="track"><i :style="{ width: width + '%' }"></i></span>
    <b>{{ shown }}</b>
  </span>
</template>
