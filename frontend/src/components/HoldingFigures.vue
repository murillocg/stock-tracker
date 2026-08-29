<script setup lang="ts">
import { brl, isNegative, type Position, type Valuation } from '@/api'

defineProps<{
  position: Position | null
  valuation: Valuation | null
  currency: string
}>()

const symbol = (currency: string) => (currency === 'BRL' ? 'R$' : '$')
</script>

<template>
  <!-- Strings throughout. The API sends Decimals as text, and parsing them into
       JavaScript numbers would reintroduce the float error Decimal exists to
       avoid — so formatting and sign are both decided textually. -->
  <div v-if="position" class="figures">
    <span class="fig">
      <span class="k">holding</span>
      <b>{{ position.quantity }}</b>
      <span class="k">@ {{ position.averagePrice }}</span>
    </span>

    <template v-if="valuation">
      <span class="fig">
        <span class="k">worth</span>
        <b>{{ symbol(currency) }} {{ brl(valuation.marketValue) }}</b>
      </span>

      <span class="fig" :class="isNegative(valuation.unrealisedGain) ? 'down' : 'up'">
        <b>
          {{ isNegative(valuation.unrealisedGain) ? '' : '+' }}{{ valuation.unrealisedGainPercent }}%
        </b>
        <span class="k">
          {{ isNegative(valuation.unrealisedGain) ? '' : '+' }}{{ brl(valuation.unrealisedGain) }}
        </span>
      </span>
    </template>

    <span v-else class="fig k">not priced &mdash; needs an exchange rate</span>
  </div>
</template>
