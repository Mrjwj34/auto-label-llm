<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import LabelListEditor from '../../components/LabelListEditor.vue'
import SectionPanel from '../../components/SectionPanel.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useProjectStore } from '../../stores/projectStore'
import { taskFamilyText, taskStatusText } from '../../utils/uiText'

const router = useRouter()
const projectStore = useProjectStore()

const workflowMap = computed(() => new Map(projectStore.workflows.map((workflow) => [workflow.key, workflow])))

const summary = computed(() => {
  const activeWorkflowCount = new Set(projectStore.projects.map((project) => project.workflowKey)).size
  const autoAnnotationProjects = projectStore.projects.filter(
    (project) => workflowMap.value.get(project.workflowKey)?.supportsAutoAnnotation,
  ).length
  const pointRefineProjects = projectStore.projects.filter(
    (project) => workflowMap.value.get(project.workflowKey)?.supportsPointRefine,
  ).length
  return {
    activeWorkflowCount,
    autoAnnotationProjects,
    pointRefineProjects,
  }
})

onMounted(() => {
  void projectStore.loadProjects()
})

async function openCreateDrawer() {
  if (!projectStore.workflows.length) {
    await projectStore.loadProjects()
  }
  projectStore.openCreateDrawer()
}

function openProject(projectId: number) {
  void router.push(`/projects/${projectId}/overview`)
}

async function createProject() {
  const created = await projectStore.createProject()
  if (created) {
    void router.push(`/projects/${created.id}/overview`)
  }
}

function workflowDisplayName(workflowKey: string): string {
  return workflowMap.value.get(workflowKey)?.displayName ?? workflowKey
}

function taskStatusTone(status: string): 'neutral' | 'warning' | 'success' | 'danger' {
  if (status === 'RUNNING' || status === 'QUEUED') return 'warning'
  if (status === 'SUCCESS') return 'success'
  if (status === 'FAILED') return 'danger'
  return 'neutral'
}
</script>

<template>
  <div class="page-frame">
    <header class="page-header">
      <div>
        <h1 class="page-title">项目</h1>
        <div class="page-meta mono">项目={{ projectStore.projects.length }} 工作流={{ projectStore.workflows.length }}</div>
      </div>
      <div class="projects-header-actions">
        <button @click="projectStore.loadProjects">刷新</button>
        <button class="primary" @click="openCreateDrawer">新建项目</button>
      </div>
    </header>

    <SectionPanel>
      <template #header>
        <strong>筛选</strong>
      </template>
      <div class="projects-toolbar">
        <input v-model="projectStore.search" placeholder="搜索项目 / 工作流 / 任务族" />
        <select v-model="projectStore.workflowFilter">
          <option value="all">全部工作流</option>
          <option v-for="workflow in projectStore.workflows" :key="workflow.key" :value="workflow.key">
            {{ workflow.displayName }}
          </option>
        </select>
      </div>
    </SectionPanel>

    <div class="projects-kpis">
      <div class="projects-kpi">
        <span>项目数</span>
        <strong class="mono">{{ projectStore.projects.length }}</strong>
      </div>
      <div class="projects-kpi">
        <span>使用中工作流</span>
        <strong class="mono">{{ summary.activeWorkflowCount }}</strong>
      </div>
      <div class="projects-kpi">
        <span>自动标注项目</span>
        <strong class="mono">{{ summary.autoAnnotationProjects }}</strong>
      </div>
      <div class="projects-kpi">
        <span>点修正项目</span>
        <strong class="mono">{{ summary.pointRefineProjects }}</strong>
      </div>
    </div>

    <SectionPanel>
      <template #header>
        <strong>项目列表</strong>
      </template>
      <div class="projects-table-scroll">
        <div class="projects-table">
          <div class="projects-table-head mono">
            <span>项目</span>
            <span>工作流</span>
            <span>任务族</span>
            <span>最近任务</span>
            <span>创建时间</span>
          </div>
          <transition-group name="grid" tag="div" class="projects-table-body">
            <button
              v-for="project in projectStore.filteredProjects"
              :key="project.id"
              class="projects-row"
              @click="openProject(project.id)"
            >
              <span class="projects-name">{{ project.name }}</span>
              <span class="projects-workflow-cell">
                <strong>{{ workflowDisplayName(project.workflowKey) }}</strong>
                <span class="mono">{{ project.workflowKey }}</span>
              </span>
              <span class="mono">{{ taskFamilyText(project.taskFamily) }}</span>
              <StatusChip :label="taskStatusText(project.lastTaskStatus)" :tone="taskStatusTone(project.lastTaskStatus)" />
              <span class="mono">{{ project.createdAt }}</span>
            </button>
          </transition-group>
          <div v-if="projectStore.filteredProjects.length === 0" class="projects-empty">没有符合条件的项目</div>
        </div>
      </div>
    </SectionPanel>

    <transition name="drawer">
      <div v-if="projectStore.createDrawerOpen" class="projects-drawer-mask" @click.self="projectStore.closeCreateDrawer()">
        <aside class="projects-drawer">
          <div class="projects-drawer-head">
            <strong>新建项目</strong>
            <button @click="projectStore.closeCreateDrawer()">关闭</button>
          </div>
          <div class="projects-drawer-section">
            <label>项目名称</label>
            <input v-model="projectStore.createDraft.name" placeholder="输入项目名称" />
          </div>
          <div class="projects-drawer-section">
            <label>工作流</label>
            <div class="projects-workflow-list">
              <button
                v-for="workflow in projectStore.availableCreateWorkflows"
                :key="workflow.key"
                class="projects-workflow-item"
                :class="{ active: workflow.key === projectStore.createDraft.workflowKey }"
                @click="projectStore.createDraft.workflowKey = workflow.key"
              >
                <strong>{{ workflow.displayName }}</strong>
                <span class="mono">{{ taskFamilyText(workflow.taskFamily) }}</span>
              </button>
            </div>
          </div>
          <div class="projects-drawer-section">
            <label>标签</label>
            <LabelListEditor v-model="projectStore.createDraft.labels" placeholder="一次输入一个标签，例如：建筑" />
          </div>
          <button
            class="primary"
            :disabled="!projectStore.createDraft.name.trim() || !projectStore.createDraft.workflowKey || projectStore.saving"
            @click="createProject"
          >
            创建
          </button>
        </aside>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.projects-header-actions,
.projects-toolbar {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.projects-toolbar > * {
  min-width: 220px;
  flex: 1 1 220px;
}

.projects-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.projects-kpi {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 14px 16px;
}

.projects-kpi span {
  color: var(--text-muted);
  font-size: 13px;
}

.projects-kpi strong {
  color: var(--text-strong);
  font-size: 24px;
}

.projects-table-scroll {
  overflow-x: auto;
}

.projects-table {
  --projects-columns: minmax(220px, 2fr) minmax(220px, 1.8fr) minmax(120px, 0.9fr) minmax(120px, 1fr) minmax(180px, 1.2fr);
  min-width: 880px;
}

.projects-table-head,
.projects-row {
  display: grid;
  grid-template-columns: var(--projects-columns);
  align-items: center;
  gap: 14px;
}

.projects-table-head {
  border-bottom: 1px solid var(--line);
  padding: 0 0 14px;
  color: var(--text-muted);
  font-size: 12px;
  text-transform: uppercase;
}

.projects-table-body {
  display: grid;
}

.projects-row {
  width: 100%;
  min-width: 0;
  border: none;
  border-bottom: 1px solid var(--line);
  background: transparent;
  padding: 14px 0;
  text-align: left;
}

.projects-row:hover {
  background: var(--panel-soft);
}

.projects-name {
  color: var(--text-strong);
  font-weight: 700;
}

.projects-workflow-cell {
  display: grid;
  gap: 4px;
}

.projects-workflow-cell strong {
  color: var(--text-strong);
}

.projects-empty {
  padding: 18px 0 4px;
  color: var(--text-muted);
}

.projects-drawer-mask {
  position: fixed;
  inset: 0;
  display: flex;
  justify-content: flex-end;
  background: rgba(16, 35, 63, 0.18);
}

.projects-drawer {
  display: grid;
  width: min(420px, 100%);
  gap: 18px;
  border-left: 1px solid var(--line);
  background: var(--panel);
  padding: 20px;
}

.projects-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.projects-drawer-section {
  display: grid;
  gap: 8px;
}

.projects-drawer-section label {
  color: var(--text-muted);
  font-size: 13px;
}

.projects-workflow-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.projects-workflow-item {
  display: grid;
  gap: 8px;
  justify-items: start;
  min-height: 96px;
  padding: 16px;
  border-radius: 20px;
}

.projects-workflow-item strong {
  color: var(--text-strong);
  font-size: 16px;
}

.projects-workflow-item .mono {
  color: var(--text-muted);
  font-size: 12px;
}

.projects-workflow-item.active {
  border-color: var(--accent);
  background: linear-gradient(180deg, rgba(31, 111, 255, 0.12), rgba(31, 111, 255, 0.04));
  box-shadow: inset 0 0 0 1px rgba(31, 111, 255, 0.1);
}

@media (max-width: 1080px) {
  .projects-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .projects-workflow-list {
    grid-template-columns: 1fr;
  }
}
</style>
