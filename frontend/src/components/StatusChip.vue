<script setup lang="ts">
const props = defineProps<{
  tone?: 'neutral' | 'accent' | 'success' | 'warning' | 'danger'
  label: string
}>()
</script>

<template>
  <span class="status-chip" :class="props.tone ?? 'neutral'">{{ props.label }}</span>
</template>

<style scoped>
.status-chip {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 5px 10px;
  color: var(--text-soft);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  background: rgba(255, 255, 255, 0.75);
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
