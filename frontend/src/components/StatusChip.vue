<script setup lang="ts">
const props = defineProps<{
  tone?: 'neutral' | 'accent' | 'success' | 'warning' | 'danger'
  label: string
  compact?: boolean
}>()
</script>

<template>
  <span class="status-chip" :class="[props.tone ?? 'neutral', { compact: props.compact }]">{{ props.label }}</span>
</template>

<style scoped>
.status-chip {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--line);
  padding: 4px 8px;
  color: var(--text-soft);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
  background: #fff;
}

.status-chip.compact {
  padding: 2px 6px;
  font-size: 11px;
  letter-spacing: 0;
}

.status-chip.accent {
  border-color: rgba(11, 95, 255, 0.22);
  color: var(--accent);
}

.status-chip.success {
  border-color: rgba(17, 173, 124, 0.22);
  color: var(--success);
}

.status-chip.warning {
  border-color: rgba(191, 127, 32, 0.22);
  color: var(--warning);
}

.status-chip.danger {
  border-color: rgba(212, 72, 72, 0.22);
  color: var(--danger);
}
</style>
