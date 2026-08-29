<script setup lang="ts">
import { computed } from 'vue'
import type { Check } from '@/api'
import SignalDot from './SignalDot.vue'

const props = defineProps<{ checks: Check[] }>()

// NOT_APPLICABLE and INSUFFICIENT_DATA are dimmed rather than hidden: knowing a
// check did not apply is itself information, and hiding it would make the card
// look like a shorter ruleset than it is.
const isMuted = (check: Check) =>
  check.signal === 'NOT_APPLICABLE' || check.signal === 'INSUFFICIENT_DATA'

// Reasons are shown for everything that is NOT plainly fine. A green card stays
// quiet; anything asking for attention says why, on the card, rather than behind
// a hover the user has to discover.
const reasons = computed(() => props.checks.filter((check) => check.signal !== 'GREEN'))
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

  <ul v-if="reasons.length" class="reasons">
    <li v-for="reason in reasons" :key="reason.name">
      <SignalDot :signal="reason.signal" />
      <span><strong>{{ reason.name }}</strong> — {{ reason.explanation }}</span>
    </li>
  </ul>
</template>
