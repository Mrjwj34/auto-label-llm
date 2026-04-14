<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import ProjectTabs from '../../components/ProjectTabs.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useProjectStore } from '../../stores/projectStore'
import { useSystemRuntimeStore } from '../../stores/systemRuntimeStore'
import { taskFamilyText, taskTypeText } from '../../utils/uiText'

const route = useRoute()
const projectStore = useProjectStore()
const systemStore = useSystemRuntimeStore()

const projectId = computed(() => Number(route.params.projectId))

onMounted(() => {
  if (Number.isFinite(projectId.value)) {
    void Promise.all([projectStore.loadProject(projectId.value), systemStore.loadRuntime()])
  }
})

watch(projectId, (nextProjectId) => {
  if (Number.isFinite(nextProjectId)) {
    void Promise.all([projectStore.loadProject(nextProjectId), systemStore.loadRuntime()])
  }
})
</script>

<template>
  <div class="page-frame">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ projectStore.currentProject?.name ?? '项目' }}</h1>
        <div class="page-meta mono">
          任务类型={{ taskTypeText(projectStore.currentProject?.taskType ?? '-') }} 工作流={{ projectStore.currentProject?.workflowKey ?? '-' }}
          任务族={{ taskFamilyText(projectStore.currentProject?.taskFamily ?? '-') }} 创建时间={{ projectStore.currentProject?.createdAt ?? '-' }}
        </div>
      </div>
      <div class="project-layout-meta">
        <span class="project-layout-base mono">基础模型={{ systemStore.systemSettings?.llm.baseModel ?? '-' }}</span>
        <StatusChip :label="`模型标签 ${projectStore.settings?.activeModelTag ?? 'base'}`" tone="accent" />
      </div>
    </header>

    <ProjectTabs v-if="projectStore.currentProject" :project-id="projectStore.currentProject.id" />

    <router-view />
  </div>
</template>

<style scoped>
.project-layout-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.project-layout-base {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
