<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  modelValue: string[]
  placeholder?: string
  helper?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [string[]]
}>()

const draft = ref('')

function normalizeLabels(input: string): string[] {
  return input
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function updateLabels(nextLabels: string[]) {
  emit('update:modelValue', nextLabels)
}

function addDraftLabel() {
  const incoming = normalizeLabels(draft.value)
  if (!incoming.length) return

  const nextLabels = [...props.modelValue]
  for (const label of incoming) {
    if (!nextLabels.includes(label)) {
      nextLabels.push(label)
    }
  }

  updateLabels(nextLabels)
  draft.value = ''
}

function removeLabel(label: string) {
  updateLabels(props.modelValue.filter((item) => item !== label))
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' && event.key !== ',') return
  event.preventDefault()
  addDraftLabel()
}
</script>

<template>
  <div class="label-editor">
    <div v-if="modelValue.length > 0" class="label-editor-list">
      <button v-for="label in modelValue" :key="label" class="label-chip" type="button" @click="removeLabel(label)">
        <span>{{ label }}</span>
        <strong aria-hidden="true">×</strong>
      </button>
    </div>

    <div class="label-editor-input">
      <input v-model="draft" :placeholder="placeholder ?? '输入一个标签后按回车'" @keydown="handleKeydown" />
      <button type="button" @click="addDraftLabel">添加标签</button>
    </div>

    <div v-if="helper" class="label-editor-helper">{{ helper }}</div>
  </div>
</template>

<style scoped>
.label-editor {
  display: grid;
  gap: 10px;
}

.label-editor-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.label-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  padding: 6px 10px;
}

.label-editor-input {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.label-editor-helper {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 720px) {
  .label-editor-input {
    grid-template-columns: 1fr;
  }
}
</style>
