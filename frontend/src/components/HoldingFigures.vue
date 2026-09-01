<script setup lang="ts">
import { brl, isNegative, num, type Position, type Valuation } from '@/api'

withDefaults(
  defineProps<{
    position: Position | null
    valuation: Valuation | null
    currency: string
    /** Whether a price was collected at all. Distinguishes the two ways a
        holding ends up unvalued, which need different fixes. */
    priced?: boolean
    /** One line, for the portfolio list. The detail page keeps the full set. */
    compact?: boolean
  }>(),
  { compact: false, priced: true },
)

const symbol = (currency: string) => (currency === 'BRL' ? 'R$' : '$')
</script>

<template>
  <!-- Strings throughout. The API sends Decimals as text, and parsing them into
       JavaScript numbers would reintroduce the float error Decimal exists to
       avoid — so formatting and sign are both decided textually. -->
  <div v-if="position" class="figures" :class="{ compact }">
    <span class="fig">
      <span class="k">holding</span>
      <b>{{ num(position.quantity) }}</b>
      <span class="k">@ {{ brl(position.averagePrice ?? '0') }}</span>
    </span>

    <template v-if="valuation">
      <span class="fig">
        <span v-if="!compact" class="k">worth</span>
        <b>{{ symbol(currency) }} {{ brl(valuation.marketValue) }}</b>
        <!-- The converted figure only for holdings that are not already in the
             base currency: repeating an identical number beside itself for the
             Brazilian book would be noise, and it is what makes the weight
             column legible for the rest. -->
        <span v-if="valuation.baseMarketValue && currency !== 'BRL'" class="k">
          &middot; R$ {{ brl(valuation.baseMarketValue) }}
        </span>
      </span>

      <span class="fig" :class="isNegative(valuation.unrealisedGain) ? 'down' : 'up'">
        <b>
          {{ isNegative(valuation.unrealisedGain) ? '' : '+' }}{{ num(valuation.unrealisedGainPercent) }}%
        </b>
        <span v-if="!compact" class="k">
          {{ isNegative(valuation.unrealisedGain) ? '' : '+' }}{{ brl(valuation.unrealisedGain) }}
        </span>
      </span>
    </template>

    <!-- Two different failures, and they were saying the same thing. No price
         means the collector has not reached this ticker yet; no rate means USDBRL
         was not collected. Sending someone to check the exchange rate when the
         stock simply has no quote wastes their time. -->
    <span v-else-if="!priced" class="fig k">no price collected yet</span>
    <span v-else class="fig k">not valued &mdash; needs an exchange rate</span>
  </div>
</template>
