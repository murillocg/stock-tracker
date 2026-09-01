<script setup lang="ts">
import { computed } from 'vue'
import { brl, isNegative, num, type PortfolioTotals } from '@/api'

const props = defineProps<{ totals: PortfolioTotals }>()

// The API says which currency it totalled in; hardcoding R$ here would quietly
// start lying the day the base currency changes.
const symbol = computed(() => (props.totals.currency === 'BRL' ? 'R$' : '$'))
</script>

<template>
  <div class="summary">
    <div class="sum">
      <span class="k">invested</span>
      <b>{{ symbol }} {{ brl(totals.invested) }}</b>
    </div>
    <div class="sum">
      <span class="k">worth today</span>
      <b>{{ symbol }} {{ brl(totals.marketValue) }}</b>
    </div>
    <div class="sum" :class="isNegative(totals.unrealisedGain) ? 'down' : 'up'">
      <span class="k">unrealised</span>
      <b>
        {{ isNegative(totals.unrealisedGain) ? '' : '+' }}{{ symbol }} {{ brl(totals.unrealisedGain) }}
        <small>{{ isNegative(totals.unrealisedGain) ? '' : '+' }}{{ num(totals.unrealisedGainPercent) }}%</small>
      </b>
    </div>
    <!-- Said out loud rather than hidden: a total that silently omits holdings
         is worse than one that admits it. Reached today only if the FX
         collection failed, since USD holdings are otherwise converted. -->
    <div v-if="totals.unpriced" class="sum">
      <span class="k">not counted</span>
      <b>{{ totals.unpriced }} holding(s)</b>
    </div>
  </div>
</template>
