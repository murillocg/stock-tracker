<script setup lang="ts">
import type { Signal } from '@/api'
import { SIGNAL_LABEL } from '@/labels'

defineProps<{ signal: Signal; withLabel?: boolean }>()
</script>

<template>
  <span v-if="withLabel" class="badge">
    <span class="dot" :class="signal" />
    {{ SIGNAL_LABEL[signal] }}
  </span>
  <span v-else class="dot" :class="signal" :title="SIGNAL_LABEL[signal]" />
</template>
