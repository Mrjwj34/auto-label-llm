<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/http'

type TaskType = 'detection' | 'segmentation'

type WorkflowDefinition = {
  key: string
  display_name: string
  description: string
  task_type: TaskType
  task_family: string
  supports_auto_annotation: boolean
  supports_manual_bbox: boolean
  supports_point_refine: boolean
  capabilities: string[]
}

type Project = {
  id: number
  name: string
  task_type: TaskType
  workflow_key: string
  task_family: string
  created_at: string
}

type ProjectMeta = {
  task_types: TaskType[]
  default_workflows: Record<TaskType, string>
  workflows: WorkflowDefinition[]
}

const router = useRouter()

const loading = ref(false)
const error = ref<string>('')
const projects = ref<Project[]>([])
const projectMeta = ref<ProjectMeta | null>(null)
const metaLoading = ref(false)

const newName = ref('demo')
const newTaskType = ref<TaskType>('detection')
const newWorkflowKey = ref('generic_detection')

const canCreate = computed(() => newName.value.trim().length > 0)
const workflowOptions = computed(() =>
  (projectMeta.value?.workflows ?? []).filter((workflow) => workflow.task_type === newTaskType.value),
)
const selectedWorkflow = computed(
  () => workflowOptions.value.find((workflow) => workflow.key === newWorkflowKey.value) ?? workflowOptions.value[0] ?? null,
)

function syncWorkflowWithTaskType(taskType: TaskType) {
  const defaults = projectMeta.value?.default_workflows
  const available = (projectMeta.value?.workflows ?? []).filter((workflow) => workflow.task_type === taskType)
  const current = available.find((workflow) => workflow.key === newWorkflowKey.value)
  if (current) return
  newWorkflowKey.value = defaults?.[taskType] ?? available[0]?.key ?? ''
}

async function fetchProjectMeta() {
  metaLoading.value = true
  try {
    const resp = await api.get('/api/projects/meta')
    projectMeta.value = resp.data?.data ?? null
    syncWorkflowWithTaskType(newTaskType.value)
  } catch (err: any) {
    error.value = err?.message ? String(err.message) : String(err)
  } finally {
    metaLoading.value = false
  }
}

async function fetchProjects() {
  loading.value = true
  error.value = ''
  try {
    const resp = await api.get('/api/projects')
    projects.value = resp.data?.data ?? []
  } catch (err: any) {
    error.value = err?.message ? String(err.message) : String(err)
  } finally {
    loading.value = false
  }
}

async function createProject() {
  if (!canCreate.value) return
  error.value = ''
  try {
    await api.post('/api/projects', {
      name: newName.value.trim(),
      task_type: newTaskType.value,
      workflow_key: newWorkflowKey.value || undefined,
    })
    await fetchProjects()
  } catch (err: any) {
    error.value = err?.message ? String(err.message) : String(err)
  }
}

async function deleteProject(projectId: number) {
  if (!confirm(`删除项目 #${projectId}？该项目下的图片也会被删除。`)) return
  error.value = ''
  try {
    await api.delete(`/api/projects/${projectId}`)
    await fetchProjects()
  } catch (err: any) {
    error.value = err?.message ? String(err.message) : String(err)
  }
}

function openProject(projectId: number) {
  router.push({ name: 'project-images', params: { projectId } })
}

onMounted(() => {
  void fetchProjectMeta()
  void fetchProjects()
})

watch(newTaskType, (taskType) => {
  syncWorkflowWithTaskType(taskType)
})
</script>

<template>
  <section class="wrap">
    <header class="header">
      <div>
        <h1>项目</h1>
        <div class="sub">创建一个项目，然后上传图片开始标注闭环。</div>
      </div>
      <button class="btn" type="button" :disabled="loading" @click="fetchProjects">刷新</button>
    </header>

    <div class="card">
      <div class="row">
        <label class="label">名称</label>
        <input v-model="newName" class="input" data-testid="project-name-input" placeholder="project name" />
      </div>
      <div class="row">
        <label class="label">任务类型</label>
        <select v-model="newTaskType" class="input" data-testid="project-task-type">
          <option value="detection">detection (bbox)</option>
          <option value="segmentation">segmentation (mask/polygon)</option>
        </select>
      </div>
      <div class="row">
        <label class="label">工作流</label>
        <select v-model="newWorkflowKey" class="input" data-testid="project-workflow-key" :disabled="metaLoading">
          <option v-for="workflow in workflowOptions" :key="workflow.key" :value="workflow.key">
            {{ workflow.display_name }} · {{ workflow.task_family }}
          </option>
        </select>
      </div>
      <div v-if="selectedWorkflow" class="subtle">
        {{ selectedWorkflow.description }}
      </div>
      <div class="actions">
        <button
          class="btn primary"
          type="button"
          data-testid="project-create-btn"
          :disabled="!canCreate"
          @click="createProject"
        >
          创建项目
        </button>
      </div>
      <div v-if="error" class="error">{{ error }}</div>
    </div>

    <div class="list">
      <div v-if="loading" class="hint">加载中…</div>
      <div v-else-if="projects.length === 0" class="hint">暂无项目，先创建一个。</div>
      <div v-else class="grid">
        <article v-for="p in projects" :key="p.id" class="item">
          <div class="title">{{ p.name }}</div>
          <div class="meta">
            <span>#{{ p.id }}</span>
            <span class="dot">•</span>
            <span>{{ p.task_type }}</span>
          </div>
          <div class="meta">
            <span class="mono">{{ p.workflow_key }}</span>
            <span class="dot">•</span>
            <span>{{ p.task_family }}</span>
          </div>
          <div class="meta muted">{{ p.created_at }}</div>
          <div class="item-actions">
            <button class="btn" type="button" :data-testid="`project-open-${p.id}`" @click="openProject(p.id)">打开</button>
            <button class="btn danger" type="button" @click="deleteProject(p.id)">删除</button>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<style scoped>
.wrap {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}

.sub {
  opacity: 0.7;
  margin-top: 6px;
}

.subtle {
  opacity: 0.72;
  font-size: 13px;
  margin-bottom: 10px;
}

.card {
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  padding: 14px;
}

.row {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 10px;
}

.label {
  width: 88px;
  opacity: 0.75;
}

.input {
  flex: 1;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(0, 0, 0, 0.15);
  color: inherit;
}

.actions {
  display: flex;
  justify-content: flex-end;
}

.list {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 16px;
}

.hint {
  opacity: 0.75;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.item {
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  padding: 12px;
}

.title {
  font-weight: 650;
  margin-bottom: 6px;
}

.meta {
  display: flex;
  align-items: center;
  gap: 6px;
  opacity: 0.8;
  font-size: 13px;
}

.meta.muted {
  opacity: 0.6;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
}

.dot {
  opacity: 0.6;
}

.item-actions {
  display: flex;
  gap: 10px;
  margin-top: 12px;
}

.btn {
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.06);
  color: inherit;
  padding: 8px 12px;
  border-radius: 10px;
}

.btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.btn.primary {
  border-color: rgba(99, 102, 241, 0.55);
}

.btn.danger {
  border-color: rgba(248, 81, 73, 0.55);
}

.error {
  margin-top: 10px;
  color: rgba(248, 81, 73, 0.95);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 13px;
}
</style>
