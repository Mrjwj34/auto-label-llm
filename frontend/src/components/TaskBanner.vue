<script setup lang="ts">
import type { TaskSnapshot } from '../backend/types'
import StatusChip from './StatusChip.vue'
import { taskKindText, taskStatusText, taskTransportText } from '../utils/uiText'

defineProps<{
  task: TaskSnapshot
}>()
</script>

<template>
  <div class="task-banner" :class="{ running: task.status === 'RUNNING' }">
    <div class="task-banner-main">
      <div class="task-banner-head">
        <strong>{{ taskKindText(task.kind) }}</strong>
        <StatusChip
          :label="taskStatusText(task.status)"
          :tone="
            task.status === 'SUCCESS'
              ? 'success'
              : task.status === 'FAILED'
                ? 'danger'
                : task.status === 'RUNNING'
                  ? 'accent'
                  : 'neutral'
          "
        />
      </div>
      <div class="task-banner-meta">
        <span>{{ task.id }}</span>
        <span>{{ taskTransportText(task.transport) }}</span>
        <span>{{ task.updatedAt }}</span>
      </div>
    </div>
    <div class="task-banner-progress">
      <div class="task-banner-track">
        <div class="task-banner-fill" :style="{ width: `${task.progress}%` }" />
      </div>
      <div class="task-banner-message">{{ task.message }}</div>
    </div>
  </div>
</template>

<style scoped>
.task-banner {
  display: grid;
  gap: 12px;
  border: 1px solid #0c5ae0;
  background: #0b5fff;
  padding: 14px 16px;
  color: #fff;
}

.task-banner-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.task-banner-head {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 18px;
}

.task-banner-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  color: rgba(255, 255, 255, 0.74);
  font-family: var(--font-mono);
  font-size: 13px;
}

.task-banner-progress {
  display: grid;
  gap: 10px;
}

.task-banner-track {
  overflow: hidden;
  height: 8px;
  background: rgba(255, 255, 255, 0.14);
}

.task-banner-fill {
  height: 100%;
  background: #d7e6ff;
  transition: width 220ms ease;
}

.task-banner-message {
  color: rgba(255, 255, 255, 0.86);
  font-family: var(--font-mono);
  font-size: 14px;
}

</style>
