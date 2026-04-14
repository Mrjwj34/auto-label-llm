<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import type { TaskType } from '../../backend/types'
import LabelListEditor from '../../components/LabelListEditor.vue'
import SectionPanel from '../../components/SectionPanel.vue'
import { useProjectStore } from '../../stores/projectStore'
import { taskFamilyText, taskTypeText } from '../../utils/uiText'

const router = useRouter()
const projectStore = useProjectStore()

const summary = computed(() => {
  const detectionProjects = projectStore.projects.filter((project) => project.taskType === 'detection').length
  const segmentationProjects = projectStore.projects.filter((project) => project.taskType === 'segmentation').length
  return {
    detectionProjects,
    segmentationProjects,
    workflowCount: projectStore.workflows.length,
  }
})

onMounted(() => {
  void projectStore.loadProjects()
})

function openProject(projectId: number) {
  void router.push(`/projects/${projectId}/overview`)
}

async function createProject() {
  const created = await projectStore.createProject()
  if (created) {
    void router.push(`/projects/${created.id}/overview`)
  }
}

function changeTaskType(event: Event) {
  const target = event.target as HTMLSelectElement
  projectStore.setCreateTaskType(target.value as TaskType)
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
        <button class="primary" @click="projectStore.openCreateDrawer()">新建项目</button>
      </div>
    </header>

    <SectionPanel>
      <template #header>
        <strong>筛选</strong>
      </template>
      <div class="projects-toolbar">
        <input v-model="projectStore.search" placeholder="搜索项目 / 工作流 / 任务类型" />
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
        <span>检测项目</span>
        <strong class="mono">{{ summary.detectionProjects }}</strong>
      </div>
      <div class="projects-kpi">
        <span>分割项目</span>
        <strong class="mono">{{ summary.segmentationProjects }}</strong>
      </div>
      <div class="projects-kpi">
        <span>工作流数</span>
        <strong class="mono">{{ summary.workflowCount }}</strong>
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
            <span>任务类型</span>
            <span>工作流</span>
            <span>任务族</span>
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
              <span class="mono">{{ taskTypeText(project.taskType) }}</span>
              <span class="mono">{{ project.workflowKey }}</span>
              <span class="mono">{{ taskFamilyText(project.taskFamily) }}</span>
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
            <label>任务类型</label>
            <select :value="projectStore.createDraft.taskType" @change="changeTaskType">
              <option v-for="taskType in projectStore.taskTypes" :key="taskType" :value="taskType">
                {{ taskTypeText(taskType) }}
              </option>
            </select>
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
                {{ workflow.displayName }}
              </button>
            </div>
          </div>
          <div class="projects-drawer-section">
            <label>标签</label>
            <LabelListEditor
              v-model="projectStore.createDraft.labels"
              placeholder="一次输入一个标签，例如：建筑"
              helper="按标签逐个维护；按回车或点击按钮即可添加。"
            />
          </div>
          <div v-if="projectStore.selectedWorkflow" class="projects-capabilities mono">
            <div>工作流={{ projectStore.selectedWorkflow.key }}</div>
            <div>任务类型={{ taskTypeText(projectStore.selectedWorkflow.taskType) }}</div>
            <div>任务族={{ taskFamilyText(projectStore.selectedWorkflow.taskFamily) }}</div>
            <div>自动标注={{ projectStore.selectedWorkflow.supportsAutoAnnotation ? '是' : '否' }}</div>
            <div>点修正={{ projectStore.selectedWorkflow.supportsPointRefine ? '是' : '否' }}</div>
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
  --projects-columns: minmax(220px, 2fr) minmax(96px, 0.9fr) minmax(180px, 1.5fr) minmax(120px, 1fr) minmax(180px, 1.2fr);
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
  gap: 8px;
}

.projects-workflow-item.active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.projects-capabilities {
  display: grid;
  gap: 6px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 12px;
}

@media (max-width: 1080px) {
  .projects-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
