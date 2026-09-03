<script setup lang="ts">
import { computed } from 'vue'
import { brl, type PriceRange } from '@/api'

const props = defineProps<{ range: PriceRange }>()

// Parsed only to place a marker, never for arithmetic that reaches the user.
const position = computed(() => Math.max(0, Math.min(100, Number(props.range.position))))
</script>

<template>
  <span
    class="range"
    :title="`52-week range ${brl(range.low)} to ${brl(range.high)} — currently ${brl(range.position)}% of the way up it`"
  >
    <span class="lo">{{ brl(range.low) }}</span>
    <span class="track"><i :style="{ left: position + '%' }"></i></span>
    <span class="hi">{{ brl(range.high) }}</span>
  </span>
</template>
