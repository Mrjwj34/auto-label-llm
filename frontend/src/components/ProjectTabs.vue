<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import type { ProjectTabKey } from '../backend/types'
import { projectTabText } from '../utils/uiText'

const props = defineProps<{
  projectId: number
}>()

const route = useRoute()

const tabs: Array<{ key: ProjectTabKey; label: string }> = [
  { key: 'overview', label: projectTabText('overview') },
  { key: 'data', label: projectTabText('data') },
  { key: 'annotate', label: projectTabText('annotate') },
  { key: 'train', label: projectTabText('train') },
  { key: 'evaluate', label: projectTabText('evaluate') },
  { key: 'settings', label: projectTabText('settings') },
]

function isActive(key: ProjectTabKey): boolean {
  return route.path.endsWith(`/${key}`)
}
</script>

<template>
  <nav class="project-tabs">
    <RouterLink
      v-for="tab in tabs"
      :key="tab.key"
      :to="`/projects/${props.projectId}/${tab.key}`"
      class="project-tab"
      :class="{ active: isActive(tab.key) }"
    >
      {{ tab.label }}
    </RouterLink>
  </nav>
</template>

<style scoped>
.project-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  border-bottom: 1px solid var(--line);
  overflow: clip;
  align-items: flex-end;
}

.project-tab {
  position: relative;
  padding: 12px 14px 14px;
  color: var(--text-soft);
  text-decoration: none;
  white-space: nowrap;
  transition:
    color 160ms ease,
    background-color 160ms ease;
}

.project-tab::after {
  position: absolute;
  right: 10px;
  bottom: -1px;
  left: 10px;
  height: 3px;
  background: var(--accent);
  transform: scaleX(0);
  transform-origin: center;
  transition: transform 200ms cubic-bezier(0.22, 1, 0.36, 1);
  content: '';
}

.project-tab:hover {
  color: var(--text-strong);
  background: rgba(11, 95, 255, 0.05);
}

.project-tab.active {
  color: var(--accent);
  font-weight: 600;
}

.project-tab.active::after {
  transform: scaleX(1);
}
</style>
