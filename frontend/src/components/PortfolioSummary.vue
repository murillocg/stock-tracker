<script setup lang="ts">
import { brl, isNegative, type PortfolioTotals } from '@/api'

defineProps<{ totals: PortfolioTotals }>()
</script>

<template>
  <div class="summary">
    <div class="sum">
      <span class="k">invested</span>
      <b>R$ {{ brl(totals.invested) }}</b>
    </div>
    <div class="sum">
      <span class="k">worth today</span>
      <b>R$ {{ brl(totals.marketValue) }}</b>
    </div>
    <div class="sum" :class="isNegative(totals.unrealisedGain) ? 'down' : 'up'">
      <span class="k">unrealised</span>
      <b>
        {{ isNegative(totals.unrealisedGain) ? '' : '+' }}R$ {{ brl(totals.unrealisedGain) }}
        <small>{{ isNegative(totals.unrealisedGain) ? '' : '+' }}{{ totals.unrealisedGainPercent }}%</small>
      </b>
    </div>
    <!-- Said out loud rather than hidden: a total that silently omits holdings
         is worse than one that admits it. -->
    <div v-if="totals.unpriced" class="sum">
      <span class="k">not counted</span>
      <b>{{ totals.unpriced }} holding(s)</b>
    </div>
  </div>
</template>
