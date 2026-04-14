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
    .split(/[\n,，/]+/)
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
      <div v-for="label in modelValue" :key="label" class="label-chip">
        <span>{{ label }}</span>
        <button type="button" class="label-chip-remove" aria-label="删除标签" @click.stop="removeLabel(label)">
          ×
        </button>
      </div>
    </div>

    <div class="label-editor-input">
      <input v-model="draft" :placeholder="placeholder ?? '输入标签后按回车'" @keydown="handleKeydown" />
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
  position: relative;
  display: inline-flex;
  min-width: 0;
  align-items: center;
  border: 1px solid var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  padding: 6px 30px 6px 10px;
}

.label-chip span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.label-chip-remove {
  position: absolute;
  top: 50%;
  right: 8px;
  display: inline-grid;
  width: 14px;
  height: 14px;
  place-items: center;
  border: none;
  background: transparent;
  padding: 0;
  color: inherit;
  line-height: 1;
}

.label-chip-remove:hover {
  background: rgba(11, 95, 255, 0.08);
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
