<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { API_BASE_URL, api } from '../api/http'

type ImageRow = {
  id: number
  project_id: number
  filename: string
  width: number | null
  height: number | null
  split: 'train' | 'val' | 'test'
  status: string
  quality_score: number | null
  file_url: string
}

type DatasetFormat = 'yolo' | 'coco'
type ImageSortMode = 'newest' | 'quality_asc' | 'quality_desc'

type FinetuneJobRow = {
  id: number
  project_id: number
  status: 'pending' | 'running' | 'done' | 'failed'
  dataset_path: string | null
  lora_path: string | null
  log_path: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string | null
  model_tag: string
  is_active: boolean | null
  config: Record<string, unknown> | null
}

type EvaluationRunRow = {
  id: number
  project_id: number
  status: 'pending' | 'running' | 'done' | 'failed'
  split: string
  model_tag: string
  metrics: Record<string, unknown> | null
  report_path: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string | null
  config: Record<string, unknown> | null
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

const importFormat = ref<DatasetFormat>('yolo')
const importFile = ref<File | null>(null)
const importInputRef = ref<HTMLInputElement | null>(null)
const importingDataset = ref(false)
const exportingDataset = ref<DatasetFormat | ''>('')
const datasetMessage = ref('')
const canImportDataset = computed(() => !!importFile.value && !importingDataset.value)

const activeModelTag = ref('base')
const qualityReviewThreshold = ref(0.6)
const imageSortMode = ref<ImageSortMode>('newest')
const splitUpdatingId = ref<number | null>(null)

const finetuneJobs = ref<FinetuneJobRow[]>([])
const finetuneLog = ref('')
const finetuneStarting = ref(false)
const finetuneLoading = ref(false)
const finetuneActivatingId = ref<number | null>(null)
const finetuneMessage = ref('')
const latestFinetuneJob = computed(() => finetuneJobs.value[0] ?? null)
const canStartFinetune = computed(
  () => !finetuneStarting.value && !['pending', 'running'].includes(latestFinetuneJob.value?.status ?? '')
)

const evaluationSplit = ref<'val' | 'test'>('val')
const evaluationRuns = ref<EvaluationRunRow[]>([])
const evaluationStarting = ref(false)
const evaluationLoading = ref(false)
const evaluationMessage = ref('')
const latestEvaluationRun = computed(() => evaluationRuns.value[0] ?? null)
const canStartEvaluation = computed(
  () => !evaluationStarting.value && !['pending', 'running'].includes(latestEvaluationRun.value?.status ?? '')
)
const latestEvaluationMetricsText = computed(() => {
  if (!latestEvaluationRun.value?.metrics) return 'No metrics available yet.'
  return JSON.stringify(latestEvaluationRun.value.metrics, null, 2)
})

const taskState = reactive({
  taskId: '' as string,
  status: '' as string,
  progress: 0 as number,
  message: '' as string,
})

let pollTimer: ReturnType<typeof setInterval> | null = null
let finetunePollTimer: ReturnType<typeof setInterval> | null = null
let evaluationPollTimer: ReturnType<typeof setInterval> | null = null

const sortedImages = computed(() => {
  const rows = [...images.value]
  if (imageSortMode.value === 'newest') {
    rows.sort((left, right) => right.id - left.id)
    return rows
  }

  rows.sort((left, right) => {
    const leftScore = left.quality_score ?? (imageSortMode.value === 'quality_asc' ? Number.POSITIVE_INFINITY : -1)
    const rightScore = right.quality_score ?? (imageSortMode.value === 'quality_asc' ? Number.POSITIVE_INFINITY : -1)
    if (leftScore === rightScore) return right.id - left.id
    return imageSortMode.value === 'quality_asc' ? leftScore - rightScore : rightScore - leftScore
  })
  return rows
})

function imageSrc(img: ImageRow): string {
  const base = API_BASE_URL.replace(/\/$/, '')
  const path = img.file_url.startsWith('/') ? img.file_url : `/${img.file_url}`
  return `${base}${path}`
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

function stopFinetunePolling() {
  if (finetunePollTimer) clearInterval(finetunePollTimer)
  finetunePollTimer = null
}

function stopEvaluationPolling() {
  if (evaluationPollTimer) clearInterval(evaluationPollTimer)
  evaluationPollTimer = null
}

function parseLabels(text: string): string[] {
  const raw = text
    .split(/[,\n]/g)
    .map((value) => value.trim())
    .filter(Boolean)
  const seen = new Set<string>()
  const cleaned: string[] = []
  for (const value of raw) {
    if (seen.has(value)) continue
    cleaned.push(value)
    seen.add(value)
  }
  return cleaned
}

function formatQuality(score: number | null): string {
  if (score == null) return 'unscored'
  return score.toFixed(3)
}

function needsReview(img: ImageRow): boolean {
  return img.quality_score != null && img.quality_score < qualityReviewThreshold.value
}

function reviewLabel(img: ImageRow): string {
  if (img.quality_score == null) return 'Unscored'
  return needsReview(img) ? 'Needs Review' : 'OK'
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
    activeModelTag.value = String(resp.data?.data?.active_model_tag ?? 'base')

    const labels = resp.data?.data?.labels
    if (Array.isArray(labels)) {
      labelsText.value = labels.join(', ')
    }

    const quality = resp.data?.data?.quality
    if (quality && typeof quality.threshold_review === 'number') {
      qualityReviewThreshold.value = Number(quality.threshold_review)
    }

    const evaluation = resp.data?.data?.evaluation
    const candidateSplit = String(evaluation?.split ?? 'val')
    evaluationSplit.value = candidateSplit === 'test' ? 'test' : 'val'
  } catch {
    // non-blocking
  }
}

function onPickFiles(ev: Event) {
  const input = ev.target as HTMLInputElement
  selectedFiles.value = Array.from(input.files ?? [])
}

async function upload() {
  if (!canUpload.value) return
  uploading.value = true
  error.value = ''
  try {
    const form = new FormData()
    for (const file of selectedFiles.value) form.append('files[]', file)
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

function onPickImportFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  importFile.value = input.files?.[0] ?? null
}

async function exportDataset(format: DatasetFormat) {
  exportingDataset.value = format
  error.value = ''
  datasetMessage.value = ''
  try {
    const resp = await api.get(`/api/projects/${projectId.value}/export`, {
      params: { format },
      responseType: 'blob',
    })
    const blob = new Blob([resp.data], { type: resp.headers['content-type'] ?? 'application/zip' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const disposition = String(resp.headers['content-disposition'] ?? '')
    const match = disposition.match(/filename="?([^"]+)"?/)
    link.href = url
    link.download = match?.[1] ?? `project-${projectId.value}-${format}.zip`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    datasetMessage.value = `Downloaded ${format.toUpperCase()} archive (${blob.size} bytes).`
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    exportingDataset.value = ''
  }
}

async function importDataset() {
  if (!importFile.value) {
    error.value = 'Please choose a dataset zip first.'
    return
  }
  importingDataset.value = true
  error.value = ''
  datasetMessage.value = ''
  try {
    const form = new FormData()
    form.append('format', importFormat.value)
    form.append('file', importFile.value)
    const resp = await api.post(`/api/projects/${projectId.value}/import`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const data = resp.data?.data ?? {}
    datasetMessage.value = `Imported ${Number(data.imported_count ?? 0)} images / ${Number(data.annotation_count ?? 0)} annotations via ${importFormat.value.toUpperCase()}.`
    importFile.value = null
    if (importInputRef.value) importInputRef.value.value = ''
    await fetchProjectSettings()
    await fetchImages()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    importingDataset.value = false
  }
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

async function updateImageSplit(imageId: number, split: 'train' | 'val' | 'test') {
  splitUpdatingId.value = imageId
  error.value = ''
  try {
    await api.patch(`/api/images/${imageId}`, { split })
    await fetchImages()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    splitUpdatingId.value = null
  }
}

async function fetchFinetuneLog(jobId: number) {
  const resp = await api.get(`/api/finetune/${jobId}/log`)
  finetuneLog.value = String(resp.data?.data?.log ?? '')
}

async function fetchFinetuneJobs() {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return
  finetuneLoading.value = true
  try {
    const resp = await api.get(`/api/projects/${projectId.value}/finetune-jobs`)
    const rows = Array.isArray(resp.data?.data) ? (resp.data.data as FinetuneJobRow[]) : []
    finetuneJobs.value = rows

    const latest = rows[0] ?? null
    if (latest) {
      await fetchFinetuneLog(latest.id)
    } else {
      finetuneLog.value = ''
    }

    if (latest && (latest.status === 'pending' || latest.status === 'running')) {
      if (!finetunePollTimer) {
        finetunePollTimer = setInterval(() => {
          void fetchFinetuneJobs()
          void fetchProjectSettings()
        }, 800)
      }
    } else {
      stopFinetunePolling()
    }
  } catch (err: any) {
    if (finetuneJobs.value.length === 0) {
      finetuneLog.value = ''
    }
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
    stopFinetunePolling()
  } finally {
    finetuneLoading.value = false
  }
}

async function startFinetune() {
  finetuneStarting.value = true
  error.value = ''
  finetuneMessage.value = ''
  try {
    const resp = await api.post('/api/finetune/start', { project_id: projectId.value })
    const jobId = Number(resp.data?.data?.job_id ?? 0)
    if (!jobId) throw new Error('no job_id returned')
    finetuneMessage.value = `Finetune job #${jobId} started.`
    await fetchFinetuneJobs()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    finetuneStarting.value = false
  }
}

async function activateFinetune(jobId: number) {
  finetuneActivatingId.value = jobId
  error.value = ''
  finetuneMessage.value = ''
  try {
    await api.post(`/api/finetune/${jobId}/activate`)
    finetuneMessage.value = `Activated model lora:${jobId}.`
    await fetchProjectSettings()
    await fetchFinetuneJobs()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    finetuneActivatingId.value = null
  }
}

async function fetchEvaluationRuns() {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return
  evaluationLoading.value = true
  try {
    const resp = await api.get(`/api/projects/${projectId.value}/evaluations`)
    const rows = Array.isArray(resp.data?.data) ? (resp.data.data as EvaluationRunRow[]) : []
    evaluationRuns.value = rows

    const latest = rows[0] ?? null
    if (latest && (latest.status === 'pending' || latest.status === 'running')) {
      if (!evaluationPollTimer) {
        evaluationPollTimer = setInterval(() => {
          void fetchEvaluationRuns()
        }, 900)
      }
    } else {
      stopEvaluationPolling()
    }
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
    stopEvaluationPolling()
  } finally {
    evaluationLoading.value = false
  }
}

async function startEvaluation() {
  evaluationStarting.value = true
  error.value = ''
  evaluationMessage.value = ''
  try {
    const resp = await api.post(`/api/projects/${projectId.value}/evaluate`, {
      split: evaluationSplit.value,
      model_tag: activeModelTag.value,
    })
    const runId = Number(resp.data?.data?.run_id ?? 0)
    if (!runId) throw new Error('no run_id returned')
    evaluationMessage.value = `Evaluation run #${runId} started on split=${evaluationSplit.value}.`
    await fetchEvaluationRuns()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    evaluationStarting.value = false
  }
}

function backToProjects() {
  router.push({ name: 'projects' })
}

function openImage(imgId: number) {
  router.push({ name: 'project-image-detail', params: { projectId: projectId.value, imageId: imgId } })
}

onMounted(() => {
  void fetchImages()
  void fetchProjectSettings()
  void fetchFinetuneJobs()
  void fetchEvaluationRuns()
})

onBeforeUnmount(() => {
  stopPolling()
  stopFinetunePolling()
  stopEvaluationPolling()
})

watch(projectId, () => {
  void fetchImages()
  void fetchProjectSettings()
  void fetchFinetuneJobs()
  void fetchEvaluationRuns()
})
</script>

<template>
  <section class="wrap">
    <header class="header">
      <div>
        <h1>Images</h1>
        <div class="sub">Upload images, curate labels, run auto annotation, and review quality or evaluation results in one page.</div>
      </div>
      <div class="header-actions">
        <button class="btn" type="button" @click="backToProjects">Back to Projects</button>
        <button class="btn" type="button" :disabled="loading" @click="fetchImages">Refresh</button>
      </div>
    </header>

    <div class="card">
      <div class="row">
        <input class="input" data-testid="image-upload-input" type="file" multiple accept="image/*" @change="onPickFiles" />
        <button class="btn primary" type="button" :disabled="!canUpload" @click="upload">
          {{ uploading ? 'Uploading...' : 'Upload Images' }}
        </button>
      </div>
      <div v-if="selectedFiles.length > 0" class="hint">Selected {{ selectedFiles.length }} file(s).</div>
      <div v-if="error" class="error">{{ error }}</div>
    </div>

    <div class="card">
      <div class="row">
        <label class="label">Labels</label>
        <input
          v-model="labelsText"
          data-testid="labels-input"
          class="input"
          placeholder="comma separated labels, for example crack, scratch, screw_hole"
        />
        <button class="btn" data-testid="labels-save-btn" type="button" :disabled="labelsSaving" @click="saveLabels">
          {{ labelsSaving ? 'Saving...' : 'Save Labels' }}
        </button>
      </div>
      <div class="hint">
        Auto annotation uses the project label list only. Users do not provide free-form prompts.
      </div>
      <div class="row">
        <button
          class="btn primary"
          data-testid="batch-annotate-btn"
          type="button"
          :disabled="!canStartAnnotate"
          @click="startBatchAnnotate"
        >
          Batch Auto Annotate (M4)
        </button>
        <div v-if="taskState.taskId" class="task-meta">
          task={{ taskState.taskId.slice(0, 8) }} - {{ taskState.status }} - {{ taskState.progress }}%
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

    <div class="card">
      <div class="row wrap-row">
        <label class="label">Dataset</label>
        <div class="dataset-actions">
          <button
            class="btn"
            data-testid="export-yolo-btn"
            type="button"
            :disabled="exportingDataset !== ''"
            @click="exportDataset('yolo')"
          >
            {{ exportingDataset === 'yolo' ? 'Exporting...' : 'Export YOLO Zip' }}
          </button>
          <button
            class="btn"
            data-testid="export-coco-btn"
            type="button"
            :disabled="exportingDataset !== ''"
            @click="exportDataset('coco')"
          >
            {{ exportingDataset === 'coco' ? 'Exporting...' : 'Export COCO Zip' }}
          </button>
        </div>
      </div>
      <div class="hint">
        Export includes confirmed annotations only. Import appends images and marks imported annotations as confirmed ground truth.
      </div>
      <div class="row wrap-row">
        <label class="label">Import</label>
        <select v-model="importFormat" class="input compact" data-testid="dataset-import-format">
          <option value="yolo">YOLO Zip</option>
          <option value="coco">COCO Zip</option>
        </select>
        <input
          ref="importInputRef"
          class="input"
          data-testid="dataset-import-input"
          type="file"
          accept=".zip,application/zip"
          @change="onPickImportFile"
        />
        <button
          class="btn primary"
          data-testid="dataset-import-btn"
          type="button"
          :disabled="!canImportDataset"
          @click="importDataset"
        >
          {{ importingDataset ? 'Importing...' : 'Import Dataset' }}
        </button>
      </div>
      <div v-if="importFile" class="hint">Ready to import: {{ importFile.name }}</div>
      <div v-if="datasetMessage" class="hint dataset-status" data-testid="dataset-status">{{ datasetMessage }}</div>
    </div>

    <div class="card">
      <div class="row wrap-row">
        <label class="label">Finetune</label>
        <div class="dataset-actions">
          <button
            class="btn primary"
            data-testid="finetune-start-btn"
            type="button"
            :disabled="!canStartFinetune"
            @click="startFinetune"
          >
            {{ finetuneStarting ? 'Starting...' : 'Start Finetune (M8)' }}
          </button>
          <button
            v-if="latestFinetuneJob && latestFinetuneJob.status === 'done' && !latestFinetuneJob.is_active"
            class="btn"
            data-testid="finetune-activate-btn"
            type="button"
            :disabled="finetuneActivatingId === latestFinetuneJob.id"
            @click="activateFinetune(latestFinetuneJob.id)"
          >
            {{ finetuneActivatingId === latestFinetuneJob.id ? 'Activating...' : `Activate ${latestFinetuneJob.model_tag}` }}
          </button>
        </div>
      </div>
      <div class="hint">
        Finetune uses confirmed annotations from train images only. Current active model:
        <span class="mono" data-testid="active-model-tag">{{ activeModelTag }}</span>
      </div>
      <div v-if="finetuneMessage" class="hint finetune-status">{{ finetuneMessage }}</div>
      <div v-if="latestFinetuneJob" class="task">
        <div class="task-meta" data-testid="finetune-status">
          job={{ latestFinetuneJob.id }} - {{ latestFinetuneJob.status }} - {{ latestFinetuneJob.model_tag }}
        </div>
        <div class="hint mono">dataset={{ latestFinetuneJob.dataset_path ?? '-' }}</div>
        <div class="hint mono">artifact={{ latestFinetuneJob.lora_path ?? '-' }}</div>
        <div class="hint mono">log={{ latestFinetuneJob.log_path ?? '-' }}</div>
        <pre class="log-box" data-testid="finetune-log">{{ finetuneLog || 'No log output yet.' }}</pre>
      </div>
      <div v-else-if="!finetuneLoading" class="hint">No finetune job yet. Start one after confirming train annotations.</div>
    </div>

    <div class="card">
      <div class="row wrap-row">
        <label class="label">Evaluate</label>
        <select v-model="evaluationSplit" class="input compact" data-testid="evaluation-split-select">
          <option value="val">val</option>
          <option value="test">test</option>
        </select>
        <button
          class="btn primary"
          data-testid="evaluation-start-btn"
          type="button"
          :disabled="!canStartEvaluation"
          @click="startEvaluation"
        >
          {{ evaluationStarting ? 'Starting...' : 'Run Evaluation (M9)' }}
        </button>
      </div>
      <div class="hint">
        Evaluation compares fresh auto-annotation predictions against confirmed ground truth on val/test images. Quality sorting uses the project threshold:
        <span class="mono">{{ qualityReviewThreshold.toFixed(2) }}</span>
      </div>
      <div v-if="evaluationMessage" class="hint evaluation-status">{{ evaluationMessage }}</div>
      <div v-if="latestEvaluationRun" class="task">
        <div class="task-meta" data-testid="evaluation-status">
          run={{ latestEvaluationRun.id }} - {{ latestEvaluationRun.status }} - split={{ latestEvaluationRun.split }} - model={{ latestEvaluationRun.model_tag }}
        </div>
        <div class="hint mono">report={{ latestEvaluationRun.report_path ?? '-' }}</div>
        <pre class="log-box" data-testid="evaluation-metrics">{{ latestEvaluationMetricsText }}</pre>
      </div>
      <div v-else-if="!evaluationLoading" class="hint">No evaluation run yet. Confirm some val/test annotations before starting.</div>
    </div>

    <div class="list">
      <div class="list-toolbar">
        <div class="hint">Lower quality scores are shown first when sorting by risk.</div>
        <div class="sort-group">
          <label class="label-inline" for="image-sort-select">Sort</label>
          <select id="image-sort-select" v-model="imageSortMode" class="input compact" data-testid="image-sort-select">
            <option value="newest">Newest</option>
            <option value="quality_asc">Quality Asc</option>
            <option value="quality_desc">Quality Desc</option>
          </select>
        </div>
      </div>

      <div v-if="loading" class="hint">Loading images...</div>
      <div v-else-if="sortedImages.length === 0" class="hint">No images yet. Upload a few to continue.</div>
      <div v-else class="grid">
        <article
          v-for="img in sortedImages"
          :key="img.id"
          class="item"
          :data-testid="`image-card-${img.id}`"
          @click="openImage(img.id)"
        >
          <div class="thumb">
            <img :src="imageSrc(img)" :alt="img.filename" loading="lazy" />
          </div>
          <div class="title">{{ img.filename }}</div>
          <div class="meta">
            <span>#{{ img.id }}</span>
            <span class="dot">|</span>
            <span>{{ img.width }}x{{ img.height }}</span>
          </div>
          <div class="meta muted">
            <span>status: {{ img.status }}</span>
            <span class="dot">|</span>
            <span :data-testid="`image-quality-${img.id}`">quality: {{ formatQuality(img.quality_score) }}</span>
          </div>
          <div class="meta">
            <span
              class="quality-pill"
              :class="needsReview(img) ? 'review' : 'ok'"
              :data-testid="`image-review-${img.id}`"
            >
              {{ reviewLabel(img) }}
            </span>
            <span class="dot">|</span>
            <span>split:</span>
            <select
              class="split-select"
              :data-testid="`image-split-select-${img.id}`"
              :value="img.split"
              :disabled="splitUpdatingId === img.id"
              @click.stop
              @pointerdown.stop
              @change="updateImageSplit(img.id, ($event.target as HTMLSelectElement).value as 'train' | 'val' | 'test')"
            >
              <option value="train">train</option>
              <option value="val">val</option>
              <option value="test">test</option>
            </select>
          </div>
          <div class="cta">Open image detail</div>
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

.wrap-row {
  flex-wrap: wrap;
}

.dataset-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.label {
  width: 70px;
  opacity: 0.75;
}

.label-inline {
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

.input.compact {
  flex: 0 0 160px;
}

.list {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 16px;
}

.list-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
}

.sort-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hint {
  opacity: 0.75;
}

.hint.warn {
  color: rgba(248, 81, 73, 0.95);
}

.dataset-status {
  color: rgba(56, 211, 159, 0.95);
}

.finetune-status {
  color: rgba(125, 211, 252, 0.95);
}

.evaluation-status {
  color: rgba(250, 204, 21, 0.95);
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

.log-box {
  margin: 0;
  padding: 12px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: inherit;
  font-size: 12px;
  line-height: 1.5;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
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
  flex-wrap: wrap;
}

.meta.muted {
  opacity: 0.65;
}

.dot {
  opacity: 0.6;
}

.quality-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.quality-pill.review {
  color: rgba(248, 81, 73, 0.95);
  border-color: rgba(248, 81, 73, 0.45);
  background: rgba(248, 81, 73, 0.1);
}

.quality-pill.ok {
  color: rgba(56, 211, 159, 0.95);
  border-color: rgba(56, 211, 159, 0.35);
  background: rgba(56, 211, 159, 0.08);
}

.split-select {
  min-width: 74px;
  padding: 4px 8px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(0, 0, 0, 0.15);
  color: inherit;
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

@media (max-width: 720px) {
  .header,
  .list-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .header-actions,
  .sort-group {
    justify-content: space-between;
  }

  .label {
    width: 100%;
  }

  .row {
    align-items: stretch;
    flex-direction: column;
  }

  .input.compact {
    flex: 1 1 auto;
  }
}
</style>
