<script setup lang="ts">
import type { LynchCategory } from '@/api'
import { CATEGORY_LABEL, CATEGORY_BASIS } from '@/labels'

defineProps<{ category: LynchCategory | null }>()
</script>

<template>
  <!-- Deliberately not colour-coded. Green, yellow and red already mean something
       specific here, and a green FAST_GROWER pill beside a red signal dot would
       read as a contradiction. The signals own the colour vocabulary; categories
       get shape and weight instead. -->
  <span v-if="category" class="category" :title="CATEGORY_BASIS[category]">
    {{ CATEGORY_LABEL[category] }}
  </span>
  <span v-else class="category is-unset">unclassified</span>
</template>
