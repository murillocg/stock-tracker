<script setup lang="ts">
import { computed } from 'vue'
import type { Check } from '@/api'
import SignalDot from './SignalDot.vue'

const props = withDefaults(
  defineProps<{ checks: Check[]; withReasons?: boolean }>(),
  { withReasons: true },
)

// NOT_APPLICABLE and INSUFFICIENT_DATA are dimmed rather than hidden: knowing a
// check did not apply is itself information, and hiding it would make the card
// look like a shorter ruleset than it is.
const isMuted = (check: Check) =>
  check.signal === 'NOT_APPLICABLE' || check.signal === 'INSUFFICIENT_DATA'

// The prose belongs on the detail page. The portfolio list answers "where does
// this month's money go?", which is a comparison — and prose cannot be compared,
// only read one card at a time. The chips carry the same verdict in a form you
// can scan across twenty holdings, and the full text is still one click away.
//
// INSUFFICIENT_DATA is dropped from the reasons even on the detail page: "not
// available from any free source" is a fact about our providers, not a finding
// about the company, and repeating it under every US holding taught the eye to
// skip the whole block.
const reasons = computed(() =>
  props.withReasons
    ? props.checks.filter(
        (check) => check.signal !== 'GREEN' && check.signal !== 'INSUFFICIENT_DATA',
      )
    : [],
)
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
