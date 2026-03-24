<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { API_BASE_URL, api } from '../api/http'

type ImageRow = {
  id: number
  filename: string
  width: number | null
  height: number | null
  split: string
  status: string
  quality_score: number | null
  file_url: string
}

const route = useRoute()
const router = useRouter()

const projectId = computed(() => Number(route.params.projectId))

const loading = ref(false)
const error = ref<string>('')
const images = ref<ImageRow[]>([])

const uploading = ref(false)
const selectedFiles = ref<File[]>([])

const canUpload = computed(() => selectedFiles.value.length > 0 && !uploading.value)

const labelsText = ref('')
const labelsSaving = ref(false)
const projectLabels = computed(() => parseLabels(labelsText.value))
const canStartAnnotate = computed(() => !loading.value && projectLabels.value.length > 0)

const taskState = reactive({
  taskId: '' as string,
  status: '' as string,
  progress: 0 as number,
  message: '' as string,
})

let pollTimer: ReturnType<typeof setInterval> | null = null

function imageSrc(img: ImageRow): string {
  const base = API_BASE_URL.replace(/\/$/, '')
  const path = img.file_url.startsWith('/') ? img.file_url : `/${img.file_url}`
  return `${base}${path}`
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

async function fetchImages() {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return
  loading.value = true
  error.value = ''
  try {
    const resp = await api.get(`/api/projects/${projectId.value}/images`)
    images.value = resp.data?.data ?? []
  } catch (err: any) {
    error.value = err?.message ? String(err.message) : String(err)
  } finally {
    loading.value = false
  }
}

async function fetchProjectSettings() {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return
  try {
    const resp = await api.get(`/api/projects/${projectId.value}/settings`)
    const labels = resp.data?.data?.labels
    if (Array.isArray(labels)) {
      labelsText.value = labels.join(', ')
    }
  } catch {
    // non-blocking
  }
}

function onPickFiles(ev: Event) {
  const input = ev.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  selectedFiles.value = files
}

async function upload() {
  if (!canUpload.value) return
  uploading.value = true
  error.value = ''
  try {
    const form = new FormData()
    for (const f of selectedFiles.value) form.append('files[]', f)
    await api.post(`/api/projects/${projectId.value}/images/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    selectedFiles.value = []
    await fetchImages()
  } catch (err: any) {
    error.value = err?.message ? String(err.message) : String(err)
  } finally {
    uploading.value = false
  }
}

function backToProjects() {
  router.push({ name: 'projects' })
}

function openImage(imgId: number) {
  router.push({ name: 'project-image-detail', params: { projectId: projectId.value, imageId: imgId } })
}

function parseLabels(text: string): string[] {
  const raw = text
    .split(/[,\n]/g)
    .map((s) => s.trim())
    .filter(Boolean)
  const seen = new Set<string>()
  const cleaned: string[] = []
  for (const s of raw) {
    if (seen.has(s)) continue
    cleaned.push(s)
    seen.add(s)
  }
  return cleaned
}

async function saveLabels() {
  labelsSaving.value = true
  error.value = ''
  try {
    const labels = parseLabels(labelsText.value)
    await api.patch(`/api/projects/${projectId.value}/settings`, { labels })
    await fetchProjectSettings()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    labelsSaving.value = false
  }
}

async function fetchTaskStatus(taskId: string) {
  const resp = await api.get(`/api/tasks/${taskId}/status`)
  const data = resp.data?.data
  taskState.status = String(data?.status ?? '')
  taskState.progress = Number(data?.progress ?? 0)
  taskState.message = String(data?.message ?? '')

  // Update list while running so the user sees per-image status changes.
  if (taskState.status === 'STARTED') {
    void fetchImages()
  }
  if (taskState.status === 'SUCCESS' || taskState.status === 'FAILURE') {
    stopPolling()
    await fetchImages()
  }
}

async function startBatchAnnotate() {
  error.value = ''
  if (projectLabels.value.length === 0) {
    error.value = 'Please configure at least one label before running auto annotation.'
    return
  }
  try {
    stopPolling()
    taskState.taskId = ''
    taskState.status = ''
    taskState.progress = 0
    taskState.message = ''

    const resp = await api.post(`/api/projects/${projectId.value}/annotate`, { only_pending: true })
    taskState.taskId = String(resp.data?.data?.task_id ?? '')
    if (!taskState.taskId) throw new Error('no task_id returned')

    await fetchTaskStatus(taskState.taskId)
    pollTimer = setInterval(() => {
      if (!taskState.taskId) return
      void fetchTaskStatus(taskState.taskId)
    }, 700)
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  }
}

onMounted(() => {
  void fetchImages()
  void fetchProjectSettings()
})

onBeforeUnmount(() => {
  stopPolling()
})

watch(projectId, () => {
  void fetchImages()
  void fetchProjectSettings()
})
</script>

<template>
  <section class="wrap">
    <header class="header">
      <div>
        <h1>图片</h1>
        <div class="sub">
          Project #{{ projectId }} · 上传图片后即可进入下一阶段（自动标注/纠错）。
        </div>
      </div>
      <div class="header-actions">
        <button class="btn" type="button" @click="backToProjects">返回项目</button>
        <button class="btn" type="button" :disabled="loading" @click="fetchImages">刷新</button>
      </div>
    </header>

    <div class="card">
      <div class="row">
        <input class="input" type="file" multiple accept="image/*" @change="onPickFiles" />
        <button class="btn primary" type="button" :disabled="!canUpload" @click="upload">
          {{ uploading ? '上传中…' : '上传' }}
        </button>
      </div>
      <div v-if="selectedFiles.length > 0" class="hint">已选择 {{ selectedFiles.length }} 个文件</div>
      <div v-if="error" class="error">{{ error }}</div>
    </div>

    <div class="card">
      <div class="row">
        <label class="label">Labels</label>
        <input
          v-model="labelsText"
          class="input"
          placeholder="用逗号分隔，例如：crack, scratch, screw_hole"
        />
        <button class="btn" type="button" :disabled="labelsSaving" @click="saveLabels">
          {{ labelsSaving ? '保存中…' : '保存' }}
        </button>
      </div>
      <div class="hint">
        本系统不接收用户自然语言提示词；只使用项目 Labels 列表 + 固定系统提示词做 grounding，以降低提示词攻击风险。
      </div>
      <div class="row">
        <button class="btn primary" type="button" :disabled="!canStartAnnotate" @click="startBatchAnnotate">
          Batch Auto Annotate (M4)
        </button>
        <div v-if="taskState.taskId" class="task-meta">
          task={{ taskState.taskId.slice(0, 8) }}… · {{ taskState.status }} · {{ taskState.progress }}%
        </div>
      </div>
      <div v-if="projectLabels.length === 0" class="hint warn">
        Save at least one label before starting auto annotation.
      </div>
      <div v-if="taskState.taskId" class="task">
        <progress class="progress" :value="taskState.progress" max="100" />
        <div class="hint mono">{{ taskState.message }}</div>
      </div>
    </div>

    <div class="list">
      <div v-if="loading" class="hint">加载中…</div>
      <div v-else-if="images.length === 0" class="hint">暂无图片，先上传。</div>
      <div v-else class="grid">
        <article v-for="img in images" :key="img.id" class="item" @click="openImage(img.id)">
          <div class="thumb">
            <img :src="imageSrc(img)" :alt="img.filename" loading="lazy" />
          </div>
          <div class="title">{{ img.filename }}</div>
          <div class="meta">
            <span>#{{ img.id }}</span>
            <span class="dot">•</span>
            <span>{{ img.width }}×{{ img.height }}</span>
          </div>
          <div class="meta muted">
            <span>split: {{ img.split }}</span>
            <span class="dot">•</span>
            <span>status: {{ img.status }}</span>
          </div>
          <div class="cta">点击进入标注</div>
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

.header-actions {
  display: flex;
  gap: 10px;
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
}

.label {
  width: 70px;
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

.list {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 16px;
}

.hint {
  opacity: 0.75;
}

.hint.warn {
  color: rgba(248, 81, 73, 0.95);
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
}

.task {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress {
  width: 100%;
  height: 10px;
}

.task-meta {
  opacity: 0.8;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.item {
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  padding: 12px;
  cursor: pointer;
}

.item:hover {
  border-color: rgba(99, 102, 241, 0.45);
}

.thumb {
  width: 100%;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.title {
  margin-top: 10px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta {
  display: flex;
  align-items: center;
  gap: 6px;
  opacity: 0.8;
  font-size: 13px;
  margin-top: 4px;
}

.meta.muted {
  opacity: 0.6;
}

.dot {
  opacity: 0.6;
}

.cta {
  margin-top: 10px;
  opacity: 0.75;
  font-size: 12px;
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

.error {
  margin-top: 10px;
  color: rgba(248, 81, 73, 0.95);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 13px;
}
</style>
