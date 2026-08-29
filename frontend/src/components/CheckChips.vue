<script setup lang="ts">
import type { Check } from '@/api'
import SignalDot from './SignalDot.vue'

defineProps<{ checks: Check[] }>()

// NOT_APPLICABLE and INSUFFICIENT_DATA are dimmed rather than hidden: knowing a
// check did not apply is itself information, and hiding it would make the card
// look like a shorter ruleset than it is.
const isMuted = (check: Check) =>
  check.signal === 'NOT_APPLICABLE' || check.signal === 'INSUFFICIENT_DATA'
</script>

<template>
  <div class="checks">
    <span
      v-for="check in checks"
      :key="check.name"
      class="chip"
      :class="{ 'is-muted': isMuted(check) }"
      :title="check.explanation"
    >
      <SignalDot :signal="check.signal" />
      {{ check.name }}
      <strong>{{ check.value ?? '—' }}</strong>
    </span>
  </div>
</template>
