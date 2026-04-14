<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import LabelListEditor from '../../components/LabelListEditor.vue'
import SectionPanel from '../../components/SectionPanel.vue'
import StatusChip from '../../components/StatusChip.vue'
import { useProjectStore } from '../../stores/projectStore'
import { taskFamilyText, taskStatusText, taskTypeText } from '../../utils/uiText'

const router = useRouter()
const projectStore = useProjectStore()

const workflowMap = computed(() => new Map(projectStore.workflows.map((workflow) => [workflow.key, workflow])))
const selectedWorkflow = computed(() => projectStore.selectedWorkflow)

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

function workflowOptionText(workflowKey: string): string {
  const workflow = workflowMap.value.get(workflowKey)
  if (!workflow) return workflowKey
  return `${workflow.displayName} / ${taskFamilyText(workflow.taskFamily)}`
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
        <div class="page-meta">项目={{ projectStore.projects.length }} 工作流={{ projectStore.workflows.length }}</div>
      </div>
      <div class="projects-header-actions">
        <button @click="projectStore.loadProjects">刷新</button>
        <button class="primary" @click="openCreateDrawer">新建项目</button>
      </div>
    </header>

    <SectionPanel>
      <template #header><strong>筛选</strong></template>
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

    <SectionPanel>
      <template #header><strong>项目列表</strong></template>
      <div class="projects-table-scroll">
        <div class="projects-table">
          <div class="projects-table-head">
            <span>项目</span>
            <span>工作流</span>
            <span>任务族</span>
            <span>激活版本</span>
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
              <span>{{ workflowDisplayName(project.workflowKey) }}</span>
              <span class="mono">{{ taskFamilyText(project.taskFamily) }}</span>
              <span class="mono">{{ project.activeModelTag }}</span>
              <StatusChip :label="taskStatusText(project.lastTaskStatus)" :tone="taskStatusTone(project.lastTaskStatus)" compact />
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

          <div class="projects-drawer-body">
            <section class="projects-drawer-block">
              <div class="projects-form-grid">
                <label class="projects-form-row projects-form-row-wide">
                  <span>项目名称</span>
                  <input v-model="projectStore.createDraft.name" placeholder="例如：园区外立面缺陷复核" />
                </label>

                <label class="projects-form-row projects-form-row-wide">
                  <span>工作流</span>
                  <select v-model="projectStore.createDraft.workflowKey">
                    <option v-for="workflow in projectStore.availableCreateWorkflows" :key="workflow.key" :value="workflow.key">
                      {{ workflowOptionText(workflow.key) }}
                    </option>
                  </select>
                </label>

                <div class="projects-workflow-card">
                  <div class="projects-workflow-facts">
                    <div class="projects-workflow-fact">
                      <span>工作流</span>
                      <strong>{{ selectedWorkflow?.displayName ?? '未选择工作流' }}</strong>
                    </div>
                    <div class="projects-workflow-fact">
                      <span>任务类型</span>
                      <strong>{{ taskTypeText(selectedWorkflow?.taskType ?? '--') }}</strong>
                    </div>
                    <div class="projects-workflow-fact">
                      <span>任务族</span>
                      <strong>{{ taskFamilyText(selectedWorkflow?.taskFamily ?? '--') }}</strong>
                    </div>
                  </div>
                  <div class="projects-capability-list">
                    <span v-for="capability in selectedWorkflow?.capabilities ?? []" :key="capability" class="projects-capability-chip">
                      {{ capability }}
                    </span>
                    <span v-if="(selectedWorkflow?.capabilities?.length ?? 0) === 0" class="projects-capability-chip muted">暂无能力说明</span>
                  </div>
                </div>

                <div class="projects-form-row projects-form-row-wide">
                  <span>标签</span>
                  <LabelListEditor v-model="projectStore.createDraft.labels" placeholder="输入标签，例如：裂缝、剥落、锈蚀" />
                </div>
              </div>
            </section>
          </div>

          <div class="projects-drawer-actions">
            <button
              class="primary"
              :disabled="!projectStore.createDraft.name.trim() || !projectStore.createDraft.workflowKey || projectStore.saving"
              @click="createProject"
            >
              创建项目
            </button>
          </div>
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

.projects-table-scroll {
  overflow-x: auto;
}

.projects-table {
  --projects-columns: minmax(220px, 1.8fr) minmax(180px, 1.2fr) minmax(120px, 0.8fr) minmax(120px, 0.9fr) minmax(92px, 0.72fr) minmax(180px, 1fr);
  min-width: 940px;
}

.projects-table-head,
.projects-row {
  display: grid;
  grid-template-columns: var(--projects-columns);
  align-items: center;
  gap: 12px;
}

.projects-table-head {
  border-bottom: 1px solid var(--line);
  padding: 0 0 12px;
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
  padding: 12px 0;
  text-align: left;
}

.projects-row:hover {
  background: var(--accent-soft);
}

.projects-name {
  color: var(--text-strong);
  font-weight: 700;
}

.projects-row :deep(.status-chip) {
  justify-self: start;
}

.projects-empty {
  padding: 16px 0 0;
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
  width: min(560px, 100%);
  grid-template-rows: auto 1fr auto;
  gap: 20px;
  border-left: 1px solid var(--line);
  background: var(--panel);
  padding: 20px;
}

.projects-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.projects-drawer-body {
  display: grid;
  gap: 16px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.projects-drawer-block {
  display: grid;
  gap: 16px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 18px;
}

.projects-form-grid {
  display: grid;
  gap: 18px;
}

.projects-form-row {
  display: grid;
  gap: 10px;
}

.projects-form-row-wide {
  grid-column: 1 / -1;
}

.projects-form-row > span {
  color: var(--text-muted);
  font-size: 12px;
  text-transform: uppercase;
}

.projects-workflow-card {
  display: grid;
  gap: 14px;
  border: 1px solid var(--line);
  background: var(--panel);
  padding: 16px;
}

.projects-workflow-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.projects-workflow-fact {
  display: grid;
  gap: 6px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  padding: 12px;
}

.projects-workflow-fact span {
  color: var(--text-muted);
  font-size: 12px;
}

.projects-capability-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.projects-capability-chip {
  border: 1px solid var(--line);
  background: #fff;
  padding: 6px 10px;
  color: var(--text-soft);
  font-size: 12px;
}

.projects-capability-chip.muted {
  color: var(--text-muted);
}

.projects-drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 4px;
}

@media (max-width: 720px) {
  .projects-drawer {
    width: 100%;
  }

  .projects-workflow-facts {
    grid-template-columns: 1fr;
  }
}
</style>
