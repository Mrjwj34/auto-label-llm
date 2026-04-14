<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import ProjectTabs from '../../components/ProjectTabs.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useProjectStore } from '../../stores/projectStore'
import { useSystemRuntimeStore } from '../../stores/systemRuntimeStore'
import { taskFamilyText } from '../../utils/uiText'

const route = useRoute()
const projectStore = useProjectStore()
const systemStore = useSystemRuntimeStore()

const projectId = computed(() => Number(route.params.projectId))
const currentWorkflowName = computed(() => projectStore.settings?.workflow.displayName ?? projectStore.currentProject?.workflowKey ?? '-')

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
  <div class="page-frame project-layout-frame">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ projectStore.currentProject?.name ?? '项目' }}</h1>
        <div class="page-meta">
          工作流={{ currentWorkflowName }}
          workflow key={{ projectStore.currentProject?.workflowKey ?? '-' }}
          任务族={{ taskFamilyText(projectStore.currentProject?.taskFamily ?? '-') }}
          创建时间={{ projectStore.currentProject?.createdAt ?? '-' }}
        </div>
      </div>

      <div class="project-layout-meta">
        <span class="project-layout-base">基础模型={{ systemStore.systemSettings?.llm.baseModel ?? '-' }}</span>
        <StatusChip :label="`激活版本 ${projectStore.settings?.activeModelTag ?? 'base'}`" tone="accent" />
      </div>
    </header>

    <ProjectTabs v-if="projectStore.currentProject" :project-id="projectStore.currentProject.id" />

    <div class="project-layout-content">
      <router-view />
    </div>
  </div>
</template>

<style scoped>
.project-layout-frame {
  min-width: 0;
  min-height: 100vh;
  min-height: 100dvh;
  align-content: start;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  padding-bottom: 0;
}

.project-layout-content {
  display: grid;
  width: 100%;
  min-width: 0;
  min-height: 0;
  height: 100%;
  grid-template-rows: minmax(0, 1fr);
  align-items: stretch;
}

.page-header {
  gap: 16px;
}

.page-title {
  font-size: clamp(28px, 3vw, 40px);
}

.page-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
}

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
