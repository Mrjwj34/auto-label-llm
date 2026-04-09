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
type EvaluationSplit = 'train' | 'val' | 'test'
type TaskTransport = 'idle' | 'polling' | 'websocket'

type FinetuneMetricPoint = {
  epoch?: number
  epoch_total?: number
  step?: number
  loss?: number
  learning_rate?: number
  raw?: string
}

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
  metrics?: FinetuneMetricPoint[]
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

type EvaluationDeltaValue = {
  current: number | null
  baseline: number | null
  delta: number | null
}

type EvaluationFailureSample = {
  image_id: number
  filename: string
  split: string
  tp: number
  fp: number
  fn: number
  error_count: number
  precision: number | null
  recall: number | null
  f1: number | null
  miou_bbox: number | null
  miou_mask: number | null
  dice: number | null
  unmatched_prediction_labels: string[]
  unmatched_ground_truth_labels: string[]
  inference_total_ms: number | null
}

type EvaluationComparisonImageChange = {
  image_id: number
  filename: string | null
  split: string | null
  current: {
    f1: number | null
    fp: number
    fn: number
    error_count: number
    miou_bbox: number | null
    miou_mask: number | null
    dice: number | null
  }
  baseline: {
    f1: number | null
    fp: number
    fn: number
    error_count: number
    miou_bbox: number | null
    miou_mask: number | null
    dice: number | null
  }
  delta: {
    error_count: number | null
    f1: number | null
    miou_bbox: number | null
  }
}

type EvaluationReport = {
  run_id: number
  project_id: number
  split: string
  model_tag: string
  metrics: Record<string, unknown>
  performance: Record<string, unknown> | null
  summary:
    | {
        perfect_images?: number
        images_with_failures?: number
        failure_samples?: EvaluationFailureSample[]
      }
    | null
}

type EvaluationComparison = {
  current_run: EvaluationRunRow
  baseline_run: EvaluationRunRow
  delta: {
    metrics: Record<string, EvaluationDeltaValue>
    performance: Record<string, EvaluationDeltaValue>
  }
  per_label: Record<string, Record<string, EvaluationDeltaValue>>
  current_failure_samples?: EvaluationFailureSample[]
  baseline_failure_samples?: EvaluationFailureSample[]
  top_regressions?: EvaluationComparisonImageChange[]
  top_improvements?: EvaluationComparisonImageChange[]
}

type ProjectSettingsMeta = {
  project_editable_paths: string[]
  active_system_profile: string
  resolved_project_profile: string
  note: string
}

type SettingsChange = {
  changed_paths: string[]
  hot_reload_paths: string[]
  reload_required_paths: string[]
  other_paths: string[]
  reload_required: boolean
  message: string
}

type SystemSettingsMeta = {
  hot_reload_paths: string[]
  reload_required_paths: string[]
  available_model_profiles: string[]
  active_system_profile: string
  resolved_runtime_profile: string
  storage_path: string
  note: string
}

type SystemRuntimeSettings = {
  model_profile: string
  llm: {
    base_model: string
    auto_order: string[]
    max_tokens: number
  }
  sam: {
    checkpoint: string
    device: 'cpu' | 'cuda'
    multimask_output: boolean
  }
  postprocess: {
    enable_close: boolean
    close_kernel: number
    enable_dp_simplify: boolean
    epsilon_ratio: number
    min_area_ratio: number
  }
  quality: {
    enable: boolean
    threshold_review: number
    threshold_ok: number
    use_llm_confidence: boolean
    use_sam_score: boolean
    enable_consistency_check: boolean
  }
  evaluation: {
    split: EvaluationSplit
    iou_threshold: number
    max_samples: number | null
  }
  _meta: SystemSettingsMeta
}

type SystemProfileRow = {
  name: string
  description: string
  backend: Record<string, unknown>
  frontend: Record<string, unknown>
  project_defaults: Record<string, unknown>
}

type SystemConfig = {
  active_profile: string
  profiles: SystemProfileRow[]
  settings: SystemRuntimeSettings
  env_files: {
    backend: string
    frontend: string
  }
  runtime: {
    app_profile: string
    annotation_backend: string
    vllm_base_url: string
    vllm_model_name: string
    llm_request_timeout_seconds: number
    llm_max_retries: number
    llm_max_tokens: number
  }
  metadata: {
    hot_reload_fields: string[]
    restart_required_fields: string[]
    note: string
  }
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
const settingsSaving = ref(false)
const settingsMessage = ref('')
const settingsChange = ref<SettingsChange | null>(null)
const settingsMeta = ref<ProjectSettingsMeta | null>(null)
const systemSettingsMeta = ref<SystemSettingsMeta | null>(null)
const modelProfile = ref('auto')
const llmBaseModel = ref('qwen3-vl-2b')
const llmAutoOrderText = ref('2b, 4b, 8b')
const llmMaxTokens = ref(2048)
const samCheckpoint = ref('sam3')
const samDevice = ref<'cpu' | 'cuda'>('cuda')
const samMultimaskOutput = ref(false)
const postprocessEnableClose = ref(true)
const postprocessCloseKernel = ref(5)
const postprocessEnableDpSimplify = ref(true)
const postprocessEpsilonRatio = ref(0.002)
const postprocessMinAreaRatio = ref(0.0005)
const qualityEnabled = ref(true)
const qualityOkThreshold = ref(0.8)
const qualityUseLlmConfidence = ref(true)
const qualityUseSamScore = ref(true)
const qualityConsistencyCheck = ref(false)
const evaluationDefaultSplit = ref<EvaluationSplit>('val')
const evaluationIouThreshold = ref(0.5)
const evaluationMaxSamplesText = ref('')

const importFormat = ref<DatasetFormat>('yolo')
const importFile = ref<File | null>(null)
const importInputRef = ref<HTMLInputElement | null>(null)
const importingDataset = ref(false)
const exportingDataset = ref<DatasetFormat | ''>('')
const datasetMessage = ref('')
const canImportDataset = computed(() => !!importFile.value && !importingDataset.value)

const activeModelTag = ref('base')
const modelActivationTag = ref('base')
const modelActivating = ref(false)
const modelActivationMessage = ref('')
const qualityReviewThreshold = ref(0.6)
const imageSortMode = ref<ImageSortMode>('newest')
const splitUpdatingId = ref<number | null>(null)
const systemConfig = ref<SystemConfig | null>(null)
const systemLoading = ref(false)
const canSaveRuntimeSettings = computed(() => !settingsSaving.value && !systemLoading.value && systemConfig.value !== null)
const profileActivating = ref('')
const systemMessage = ref('')
const viteProfile = String(import.meta.env.VITE_APP_PROFILE ?? 'unknown')

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
const latestFinetuneMetricText = computed(() => {
  const points = latestFinetuneJob.value?.metrics ?? []
  if (points.length === 0) return 'curve=waiting'
  const last = points[points.length - 1] ?? {}
  const epoch = typeof last.epoch === 'number' ? last.epoch.toFixed(last.epoch % 1 === 0 ? 0 : 2) : '-'
  const loss = typeof last.loss === 'number' ? last.loss.toFixed(4) : '-'
  return `curve=${points.length} points · epoch=${epoch} · loss=${loss}`
})

const evaluationSplit = ref<'val' | 'test'>('val')
const evaluationModelTag = ref('base')
const evaluationRuns = ref<EvaluationRunRow[]>([])
const evaluationStarting = ref(false)
const evaluationLoading = ref(false)
const evaluationMessage = ref('')
const evaluationReport = ref<EvaluationReport | null>(null)
const evaluationComparison = ref<EvaluationComparison | null>(null)
const evaluationComparisonLoading = ref(false)
const evaluationBaselineRunId = ref('')
const latestEvaluationRun = computed(() => evaluationRuns.value[0] ?? null)
const canStartEvaluation = computed(
  () => !evaluationStarting.value && !['pending', 'running'].includes(latestEvaluationRun.value?.status ?? '')
)
const latestEvaluationMetricsText = computed(() => {
  if (!latestEvaluationRun.value?.metrics) return 'No metrics available yet.'
  return JSON.stringify(latestEvaluationRun.value.metrics, null, 2)
})
const availableProjectModelTags = computed(() => {
  const values = ['base', activeModelTag.value]
  for (const job of finetuneJobs.value) {
    if (job.status === 'done') values.push(job.model_tag)
  }
  return [...new Set(values.filter((value) => value.trim().length > 0))]
})
const latestEvaluationInferenceText = computed(() => {
  const inference = latestEvaluationRun.value?.config?.inference
  if (!inference || typeof inference !== 'object') return 'route=unavailable'
  const payload = inference as Record<string, unknown>
  const modelTag = String(payload.effective_model_tag ?? payload.requested_model_tag ?? latestEvaluationRun.value?.model_tag ?? '-')
  const modelName = String(payload.request_model_name ?? payload.base_model_name ?? '-')
  return `route=${modelTag} -> ${modelName}`
})
const availableBaselineEvaluationRuns = computed(() =>
  evaluationRuns.value.filter((run) => run.status === 'done' && run.id !== latestEvaluationRun.value?.id)
)
const latestEvaluationFailureSamples = computed(() => {
  const rows = evaluationReport.value?.summary?.failure_samples
  return Array.isArray(rows) ? rows : []
})
const evaluationComparisonMetricRows = computed(() => {
  const metrics = evaluationComparison.value?.delta.metrics ?? {}
  return [
    { key: 'precision', label: 'Precision', entry: metrics.precision ?? null, digits: 4 },
    { key: 'recall', label: 'Recall', entry: metrics.recall ?? null, digits: 4 },
    { key: 'f1', label: 'F1', entry: metrics.f1 ?? null, digits: 4 },
    { key: 'miou_bbox', label: 'mIoU bbox', entry: metrics.miou_bbox ?? null, digits: 4 },
    { key: 'miou_mask', label: 'mIoU mask', entry: metrics.miou_mask ?? null, digits: 4 },
    { key: 'dice', label: 'Dice', entry: metrics.dice ?? null, digits: 4 },
  ].filter((row) => row.entry !== null)
})
const evaluationComparisonPerformanceRows = computed(() => {
  const metrics = evaluationComparison.value?.delta.performance ?? {}
  return [
    { key: 'avg_total_ms', label: 'Avg total ms', entry: metrics.avg_total_ms ?? null, digits: 2 },
    { key: 'p95_total_ms', label: 'P95 total ms', entry: metrics.p95_total_ms ?? null, digits: 2 },
    { key: 'avg_llm_ms', label: 'Avg LLM ms', entry: metrics.avg_llm_ms ?? null, digits: 2 },
    { key: 'avg_sam_ms', label: 'Avg SAM ms', entry: metrics.avg_sam_ms ?? null, digits: 2 },
    { key: 'avg_postprocess_ms', label: 'Avg post ms', entry: metrics.avg_postprocess_ms ?? null, digits: 2 },
  ].filter((row) => row.entry !== null)
})
const evaluationPerLabelRows = computed(() => {
  const labels = evaluationComparison.value?.per_label ?? {}
  return Object.entries(labels)
    .map(([label, metrics]) => ({
      label,
      entry: metrics.f1 ?? null,
    }))
    .filter((row) => row.entry !== null)
    .sort((left, right) => {
      const rightDelta = right.entry?.delta ?? Number.NEGATIVE_INFINITY
      const leftDelta = left.entry?.delta ?? Number.NEGATIVE_INFINITY
      return rightDelta - leftDelta
    })
})

const taskState = reactive({
  taskId: '' as string,
  status: '' as string,
  progress: 0 as number,
  message: '' as string,
})
const taskTransport = ref<TaskTransport>('idle')

let pollTimer: ReturnType<typeof setInterval> | null = null
let finetunePollTimer: ReturnType<typeof setInterval> | null = null
let evaluationPollTimer: ReturnType<typeof setInterval> | null = null
let taskSocket: WebSocket | null = null

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
  if (taskSocket) {
    taskSocket.close()
    taskSocket = null
  }
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

function parseModelOrder(text: string): string[] {
  return parseLabels(text)
}

function parseOptionalInt(text: string): number | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed) || parsed <= 0) return null
  return Math.trunc(parsed)
}

function formatQuality(score: number | null): string {
  if (score == null) return 'unscored'
  return score.toFixed(3)
}

function metricNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function formatMetric(value: unknown, digits = 4): string {
  const numeric = metricNumber(value)
  if (numeric == null) return '-'
  return numeric.toFixed(digits)
}

function formatMetricCompact(value: unknown, digits = 4): string {
  const numeric = metricNumber(value)
  if (numeric == null) return '-'
  return digits <= 2 ? numeric.toFixed(digits) : numeric.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '')
}

function formatDelta(value: number | null | undefined, digits = 4): string {
  if (value == null || !Number.isFinite(value)) return '-'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(digits)}`
}

function deltaClass(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) return 'delta-neutral'
  return value > 0 ? 'delta-positive' : 'delta-negative'
}

function formatLabelList(labels: string[] | undefined): string {
  if (!Array.isArray(labels) || labels.length === 0) return 'none'
  return labels.join(', ')
}

function needsReview(img: ImageRow): boolean {
  return img.quality_score != null && img.quality_score < qualityReviewThreshold.value
}

function reviewLabel(img: ImageRow): string {
  if (img.quality_score == null) return 'Unscored'
  if (needsReview(img)) return 'Needs Review'
  if (img.quality_score >= qualityOkThreshold.value) return 'High Confidence'
  return 'Watch'
}

function settingsStatusClass(): string {
  return settingsChange.value?.reload_required ? 'settings-warn' : 'settings-success'
}

function profileDefaultBaseModel(profile: SystemProfileRow): string {
  const llm = profile.project_defaults?.llm
  if (llm && typeof llm === 'object' && 'base_model' in llm) {
    return String((llm as Record<string, unknown>).base_model ?? '-')
  }
  return '-'
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
    const data = resp.data?.data ?? {}
    activeModelTag.value = String(data.active_model_tag ?? 'base')
    modelActivationTag.value = activeModelTag.value
    settingsMeta.value = (data._meta ?? null) as ProjectSettingsMeta | null

    const labels = data.labels
    if (Array.isArray(labels)) {
      labelsText.value = labels.join(', ')
    }
  } catch {
    // non-blocking
  }
}

function applySystemRuntimeSettings(data: Partial<SystemRuntimeSettings> | null | undefined) {
  const payload = data ?? {}
  systemSettingsMeta.value = (payload._meta ?? null) as SystemSettingsMeta | null

  modelProfile.value = String(payload.model_profile ?? 'auto')

  const llm = (payload.llm ?? {}) as Partial<SystemRuntimeSettings['llm']>
  llmBaseModel.value = String(llm.base_model ?? 'qwen3-vl-2b')
  llmAutoOrderText.value = Array.isArray(llm.auto_order) ? llm.auto_order.join(', ') : '2b, 4b, 8b'
  llmMaxTokens.value = Number(llm.max_tokens ?? 2048)

  const sam = (payload.sam ?? {}) as Partial<SystemRuntimeSettings['sam']>
  samCheckpoint.value = String(sam.checkpoint ?? 'sam3')
  samDevice.value = sam.device === 'cpu' ? 'cpu' : 'cuda'
  samMultimaskOutput.value = Boolean(sam.multimask_output)

  const postprocess = (payload.postprocess ?? {}) as Partial<SystemRuntimeSettings['postprocess']>
  postprocessEnableClose.value = Boolean(postprocess.enable_close ?? true)
  postprocessCloseKernel.value = Number(postprocess.close_kernel ?? 5)
  postprocessEnableDpSimplify.value = Boolean(postprocess.enable_dp_simplify ?? true)
  postprocessEpsilonRatio.value = Number(postprocess.epsilon_ratio ?? 0.002)
  postprocessMinAreaRatio.value = Number(postprocess.min_area_ratio ?? 0.0005)

  const quality = (payload.quality ?? {}) as Partial<SystemRuntimeSettings['quality']>
  if (quality && typeof quality.threshold_review === 'number') {
    qualityReviewThreshold.value = Number(quality.threshold_review)
  }
  qualityEnabled.value = Boolean(quality?.enable ?? true)
  qualityOkThreshold.value = Number(quality?.threshold_ok ?? 0.8)
  qualityUseLlmConfidence.value = Boolean(quality?.use_llm_confidence ?? true)
  qualityUseSamScore.value = Boolean(quality?.use_sam_score ?? true)
  qualityConsistencyCheck.value = Boolean(quality?.enable_consistency_check ?? false)

  const evaluation = (payload.evaluation ?? {}) as Partial<SystemRuntimeSettings['evaluation']>
  const candidateDefaultSplit = String(evaluation?.split ?? 'val')
  evaluationDefaultSplit.value =
    candidateDefaultSplit === 'train' ? 'train' : candidateDefaultSplit === 'test' ? 'test' : 'val'
  evaluationSplit.value = candidateDefaultSplit === 'test' ? 'test' : 'val'
  evaluationIouThreshold.value = Number(evaluation?.iou_threshold ?? 0.5)
  evaluationMaxSamplesText.value = evaluation?.max_samples == null ? '' : String(evaluation.max_samples)
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
  await patchProjectSettings({ labels: parseLabels(labelsText.value) })
  labelsSaving.value = false
}

async function patchProjectSettings(patch: Record<string, unknown>) {
  error.value = ''

  try {
    await api.patch(`/api/projects/${projectId.value}/settings`, patch)
    await fetchProjectSettings()
    await fetchImages()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  }
}

async function saveRuntimeSettings() {
  if (!canSaveRuntimeSettings.value) {
    error.value = 'System runtime settings are still loading. Please wait a moment and try again.'
    return
  }

  error.value = ''
  settingsMessage.value = ''
  settingsChange.value = null
  settingsSaving.value = true

  try {
    const resp = await api.patch('/api/system/settings', {
      model_profile: modelProfile.value,
      llm: {
        base_model: llmBaseModel.value.trim(),
        auto_order: parseModelOrder(llmAutoOrderText.value),
        max_tokens: Number(llmMaxTokens.value),
      },
      sam: {
        checkpoint: samCheckpoint.value.trim(),
        device: samDevice.value,
        multimask_output: samMultimaskOutput.value,
      },
      postprocess: {
        enable_close: postprocessEnableClose.value,
        close_kernel: Number(postprocessCloseKernel.value),
        enable_dp_simplify: postprocessEnableDpSimplify.value,
        epsilon_ratio: Number(postprocessEpsilonRatio.value),
        min_area_ratio: Number(postprocessMinAreaRatio.value),
      },
      quality: {
        enable: qualityEnabled.value,
        threshold_review: Number(qualityReviewThreshold.value),
        threshold_ok: Number(qualityOkThreshold.value),
        use_llm_confidence: qualityUseLlmConfidence.value,
        use_sam_score: qualityUseSamScore.value,
        enable_consistency_check: qualityConsistencyCheck.value,
      },
      evaluation: {
        split: evaluationDefaultSplit.value,
        iou_threshold: Number(evaluationIouThreshold.value),
        max_samples: parseOptionalInt(evaluationMaxSamplesText.value),
      },
    })
    const payload = resp.data?.data ?? {}
    settingsChange.value = (payload.change ?? null) as SettingsChange | null
    settingsMessage.value = String(resp.data?.message ?? payload.change?.message ?? 'Saved settings.')
    applySystemRuntimeSettings((payload.settings ?? null) as Partial<SystemRuntimeSettings> | null)
    await fetchSystemConfig()
    await fetchProjectSettings()
    await fetchImages()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    settingsSaving.value = false
  }
}

async function activateProjectModel() {
  modelActivating.value = true
  error.value = ''
  modelActivationMessage.value = ''
  try {
    const resp = await api.post(`/api/projects/${projectId.value}/models/activate`, {
      model_tag: modelActivationTag.value,
    })
    modelActivationMessage.value = String(resp.data?.message ?? 'Model activated.')
    await fetchProjectSettings()
    await fetchFinetuneJobs()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    modelActivating.value = false
  }
}

async function fetchSystemConfig() {
  systemLoading.value = true
  try {
    const resp = await api.get('/api/system/config')
    const data = (resp.data?.data ?? null) as SystemConfig | null
    systemConfig.value = data
    applySystemRuntimeSettings(data?.settings)
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    systemLoading.value = false
  }
}

async function activateSystemProfile(profileName: string) {
  profileActivating.value = profileName
  error.value = ''
  systemMessage.value = ''
  try {
    const resp = await api.post('/api/system/model/activate', { profile: profileName })
    systemMessage.value = String(resp.data?.message ?? 'Profile switched.')
    await fetchSystemConfig()
    await fetchProjectSettings()
    await fetchImages()
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  } finally {
    profileActivating.value = ''
  }
}

async function fetchTaskStatus(taskId: string) {
  const resp = await api.get(`/api/tasks/${taskId}/status`)
  applyTaskPayload((resp.data?.data ?? null) as Record<string, unknown> | null)
}

function applyTaskPayload(data: Record<string, unknown> | null) {
  taskState.status = String(data?.status ?? '')
  taskState.progress = Number(data?.progress ?? 0)
  taskState.message = String(data?.message ?? '')

  if (taskState.status === 'STARTED') {
    void fetchImages()
  }
  if (taskState.status === 'SUCCESS' || taskState.status === 'FAILURE') {
    stopPolling()
    void fetchImages()
  }
}

function taskWebSocketUrl(taskId: string): string {
  const base = API_BASE_URL.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:').replace(/\/$/, '')
  return `${base}/ws/tasks/${taskId}`
}

function startTaskPolling(taskId: string) {
  if (pollTimer) clearInterval(pollTimer)
  taskTransport.value = 'polling'
  pollTimer = setInterval(() => {
    if (!taskState.taskId) return
    void fetchTaskStatus(taskId)
  }, 700)
}

function connectTaskSocket(taskId: string) {
  if (typeof WebSocket === 'undefined') {
    startTaskPolling(taskId)
    return
  }

  taskTransport.value = 'websocket'
  const socket = new WebSocket(taskWebSocketUrl(taskId))
  let opened = false
  taskSocket = socket

  socket.onopen = () => {
    opened = true
  }
  socket.onmessage = (event) => {
    try {
      applyTaskPayload(JSON.parse(String(event.data ?? '{}')) as Record<string, unknown>)
    } catch {
      // keep transport fallback available
    }
  }
  socket.onerror = () => {
    if (!opened && taskSocket === socket) {
      taskSocket = null
      startTaskPolling(taskId)
    }
  }
  socket.onclose = () => {
    const shouldFallback = taskSocket === socket
    if (shouldFallback) {
      taskSocket = null
    }
    if (shouldFallback && !pollTimer && taskState.taskId === taskId && taskState.status !== 'SUCCESS' && taskState.status !== 'FAILURE') {
      startTaskPolling(taskId)
    }
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
    taskTransport.value = 'idle'

    const resp = await api.post(`/api/projects/${projectId.value}/annotate`, { only_pending: true })
    taskState.taskId = String(resp.data?.data?.task_id ?? '')
    if (!taskState.taskId) throw new Error('no task_id returned')

    await fetchTaskStatus(taskState.taskId)
    if (taskState.status !== 'SUCCESS' && taskState.status !== 'FAILURE') {
      connectTaskSocket(taskState.taskId)
    }
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
    modelActivationMessage.value = `Activated model lora:${jobId}.`
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
    if (!availableBaselineEvaluationRuns.value.some((run) => String(run.id) === evaluationBaselineRunId.value)) {
      evaluationBaselineRunId.value = availableBaselineEvaluationRuns.value[0]
        ? String(availableBaselineEvaluationRuns.value[0].id)
        : ''
    }

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
    void refreshEvaluationInsights()
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

async function fetchEvaluationReport(runId: number) {
  const resp = await api.get(`/api/evaluations/${runId}/report`)
  evaluationReport.value = (resp.data?.data ?? null) as EvaluationReport | null
}

async function fetchEvaluationComparison(runId: number) {
  if (!availableBaselineEvaluationRuns.value.length) {
    evaluationComparison.value = null
    return
  }
  evaluationComparisonLoading.value = true
  try {
    const params = evaluationBaselineRunId.value ? { baseline_run_id: Number(evaluationBaselineRunId.value) } : undefined
    const resp = await api.get(`/api/evaluations/${runId}/compare`, { params })
    evaluationComparison.value = (resp.data?.data ?? null) as EvaluationComparison | null
  } catch (err: any) {
    if (Number(err?.response?.status ?? 0) === 404) {
      evaluationComparison.value = null
      return
    }
    throw err
  } finally {
    evaluationComparisonLoading.value = false
  }
}

async function refreshEvaluationInsights() {
  const latest = latestEvaluationRun.value
  if (!latest || latest.status !== 'done') {
    evaluationReport.value = null
    evaluationComparison.value = null
    return
  }
  try {
    await fetchEvaluationReport(latest.id)
    await fetchEvaluationComparison(latest.id)
  } catch (err: any) {
    error.value = err?.response?.data?.message
      ? String(err.response.data.message)
      : err?.message
        ? String(err.message)
        : String(err)
  }
}

async function startEvaluation() {
  evaluationStarting.value = true
  error.value = ''
  evaluationMessage.value = ''
  try {
    const resp = await api.post(`/api/projects/${projectId.value}/evaluate`, {
      split: evaluationSplit.value,
      model_tag: evaluationModelTag.value,
    })
    const runId = Number(resp.data?.data?.run_id ?? 0)
    if (!runId) throw new Error('no run_id returned')
    evaluationMessage.value = `Evaluation run #${runId} started on split=${evaluationSplit.value} with model=${evaluationModelTag.value}.`
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
  void fetchSystemConfig()
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
  void fetchSystemConfig()
  void fetchFinetuneJobs()
  void fetchEvaluationRuns()
})

watch(availableProjectModelTags, (values) => {
  if (!values.length) {
    evaluationModelTag.value = 'base'
    return
  }
  if (!values.includes(evaluationModelTag.value)) {
    evaluationModelTag.value = values.includes(activeModelTag.value) ? activeModelTag.value : (values[0] ?? 'base')
  }
})

watch(evaluationBaselineRunId, () => {
  if (latestEvaluationRun.value?.status === 'done') {
    void fetchEvaluationComparison(latestEvaluationRun.value.id)
  }
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
        <div v-if="taskState.taskId" class="task-meta" data-testid="batch-task-meta">
          task={{ taskState.taskId.slice(0, 8) }} - {{ taskState.status }} - {{ taskState.progress }}%
        </div>
      </div>
      <div v-if="projectLabels.length === 0" class="hint warn">
        Save at least one label before starting auto annotation.
      </div>
      <div v-if="taskState.taskId" class="task">
        <div class="hint mono" data-testid="batch-task-transport">transport={{ taskTransport }}</div>
        <progress class="progress" :value="taskState.progress" max="100" data-testid="batch-task-progress" />
        <div class="hint mono" data-testid="batch-task-message">{{ taskState.message }}</div>
      </div>
    </div>

    <div class="card">
      <div class="row wrap-row">
        <label class="label">M10</label>
        <div class="settings-headline">
          <div class="hint">
            Runtime settings are persisted system-wide. Labels and LoRA activation stay project-specific. Hot-reload fields affect new tasks immediately; reload-required fields need an explicit profile/model reload.
          </div>
          <div class="hint mono">
            active-system=<span data-testid="active-system-profile">{{ settingsMeta?.active_system_profile ?? '-' }}</span>
            · resolved-runtime=<span data-testid="resolved-project-profile">{{ systemSettingsMeta?.resolved_runtime_profile ?? '-' }}</span>
            · active-model=<span data-testid="project-active-model-tag">{{ activeModelTag }}</span>
          </div>
        </div>
      </div>

      <div class="settings-grid">
        <section class="settings-block">
          <h2 class="settings-title">Model Routing</h2>
          <div class="row wrap-row">
            <label class="label">Active</label>
            <select v-model="modelActivationTag" class="input compact" data-testid="project-model-activate-select">
              <option v-for="tag in availableProjectModelTags" :key="tag" :value="tag">{{ tag }}</option>
            </select>
            <button
              class="btn"
              data-testid="project-model-activate-btn"
              type="button"
              :disabled="modelActivating"
              @click="activateProjectModel"
            >
              {{ modelActivating ? 'Activating...' : 'Activate Model' }}
            </button>
          </div>
          <div class="row wrap-row">
            <label class="label">Profile</label>
            <select v-model="modelProfile" class="input compact" data-testid="project-model-profile-select">
              <option
                v-for="profile in systemSettingsMeta?.available_model_profiles ?? ['auto', 'fixed', 'dev_low_resource', 'test_real_stack', 'demo_prod']"
                :key="profile"
                :value="profile"
              >
                {{ profile }}
              </option>
            </select>
            <input
              v-model="llmBaseModel"
              class="input"
              data-testid="project-llm-base-model-input"
              placeholder="qwen3-vl-2b"
            />
          </div>
          <div class="row wrap-row">
            <label class="label">LLM</label>
            <input
              v-model="llmAutoOrderText"
              class="input"
              data-testid="project-llm-auto-order-input"
              placeholder="2b, 4b, 8b"
            />
            <input
              v-model.number="llmMaxTokens"
              class="input compact"
              data-testid="project-llm-max-tokens-input"
              type="number"
              min="64"
              max="8192"
            />
          </div>
          <div class="row wrap-row">
            <label class="label">SAM</label>
            <input
              v-model="samCheckpoint"
              class="input"
              data-testid="project-sam-checkpoint-input"
              placeholder="sam3"
            />
            <select v-model="samDevice" class="input compact" data-testid="project-sam-device-select">
              <option value="cuda">cuda</option>
              <option value="cpu">cpu</option>
            </select>
            <label class="checkbox">
              <input v-model="samMultimaskOutput" data-testid="project-sam-multimask-checkbox" type="checkbox" />
              <span>multimask</span>
            </label>
          </div>
        </section>

        <section class="settings-block">
          <h2 class="settings-title">Postprocess</h2>
          <div class="row wrap-row">
            <label class="checkbox">
              <input v-model="postprocessEnableClose" data-testid="postprocess-enable-close" type="checkbox" />
              <span>close</span>
            </label>
            <label class="checkbox">
              <input
                v-model="postprocessEnableDpSimplify"
                data-testid="postprocess-enable-dp-simplify"
                type="checkbox"
              />
              <span>dp simplify</span>
            </label>
          </div>
          <div class="row wrap-row">
            <label class="label">Kernel</label>
            <input
              v-model.number="postprocessCloseKernel"
              class="input compact"
              data-testid="postprocess-close-kernel-input"
              type="number"
              min="1"
              max="31"
            />
            <input
              v-model.number="postprocessEpsilonRatio"
              class="input compact"
              data-testid="postprocess-epsilon-ratio-input"
              type="number"
              step="0.001"
              min="0"
              max="1"
            />
            <input
              v-model.number="postprocessMinAreaRatio"
              class="input compact"
              data-testid="postprocess-min-area-ratio-input"
              type="number"
              step="0.0001"
              min="0"
              max="1"
            />
          </div>
        </section>

        <section class="settings-block">
          <h2 class="settings-title">Quality</h2>
          <div class="row wrap-row">
            <label class="checkbox">
              <input v-model="qualityEnabled" data-testid="quality-enable-checkbox" type="checkbox" />
              <span>enable scoring</span>
            </label>
            <label class="checkbox">
              <input
                v-model="qualityUseLlmConfidence"
                data-testid="quality-use-llm-checkbox"
                type="checkbox"
              />
              <span>use llm confidence</span>
            </label>
            <label class="checkbox">
              <input v-model="qualityUseSamScore" data-testid="quality-use-sam-checkbox" type="checkbox" />
              <span>use sam score</span>
            </label>
            <label class="checkbox">
              <input
                v-model="qualityConsistencyCheck"
                data-testid="quality-consistency-checkbox"
                type="checkbox"
              />
              <span>consistency check</span>
            </label>
          </div>
          <div class="row wrap-row">
            <label class="label">Threshold</label>
            <input
              v-model.number="qualityReviewThreshold"
              class="input compact"
              data-testid="quality-threshold-review-input"
              type="number"
              step="0.01"
              min="0"
              max="1"
            />
            <input
              v-model.number="qualityOkThreshold"
              class="input compact"
              data-testid="quality-threshold-ok-input"
              type="number"
              step="0.01"
              min="0"
              max="1"
            />
          </div>
        </section>

        <section class="settings-block">
          <h2 class="settings-title">Evaluation Defaults</h2>
          <div class="row wrap-row">
            <label class="label">Split</label>
            <select v-model="evaluationDefaultSplit" class="input compact" data-testid="evaluation-default-split-select">
              <option value="train">train</option>
              <option value="val">val</option>
              <option value="test">test</option>
            </select>
            <input
              v-model.number="evaluationIouThreshold"
              class="input compact"
              data-testid="evaluation-iou-threshold-input"
              type="number"
              step="0.01"
              min="0"
              max="1"
            />
            <input
              v-model="evaluationMaxSamplesText"
              class="input compact"
              data-testid="evaluation-max-samples-input"
              placeholder="blank = all"
            />
          </div>
        </section>
      </div>

      <div v-if="settingsMessage" class="hint" :class="settingsStatusClass()" data-testid="settings-save-status">
        {{ settingsMessage }}
      </div>
      <div v-if="modelActivationMessage" class="hint settings-success" data-testid="project-model-activate-message">
        {{ modelActivationMessage }}
      </div>
      <div v-if="settingsChange?.reload_required_paths?.length" class="hint settings-warn" data-testid="settings-reload-paths">
        Reload required:
        <span class="mono">{{ settingsChange?.reload_required_paths.join(', ') }}</span>
      </div>
      <div v-if="systemSettingsMeta?.storage_path" class="hint mono">
        system-settings={{ systemSettingsMeta.storage_path }}
      </div>
      <div class="row wrap-row">
        <button
          class="btn primary"
          data-testid="project-settings-save-btn"
          type="button"
          :disabled="!canSaveRuntimeSettings"
          @click="saveRuntimeSettings"
        >
          {{ settingsSaving ? 'Saving...' : 'Save System Runtime Settings' }}
        </button>
      </div>
    </div>

    <div class="card">
      <div class="row wrap-row">
        <label class="label">Profiles</label>
        <div class="settings-headline">
          <div class="hint">
            One click switches between low-resource development, later real-stack integration, and demo/production-like defaults.
          </div>
          <div class="hint mono">
            backend-active=<span data-testid="system-active-profile">{{ systemConfig?.active_profile ?? 'loading' }}</span>
            · vite-now={{ viteProfile }}
          </div>
        </div>
      </div>

      <div v-if="systemLoading && !systemConfig" class="hint">Loading system profiles...</div>
      <div v-else class="profile-grid">
        <button
          v-for="profile in systemConfig?.profiles ?? []"
          :key="profile.name"
          class="profile-card"
          :class="{ active: systemConfig?.active_profile === profile.name }"
          :data-testid="`system-profile-${profile.name}`"
          type="button"
          :disabled="profileActivating === profile.name"
          @click="activateSystemProfile(profile.name)"
        >
          <div class="profile-title">{{ profile.name }}</div>
          <div class="profile-desc">{{ profile.description }}</div>
          <div class="hint mono">
            backend={{ String(profile.backend.ANNOTATION_BACKEND ?? '-') }} · model={{ String(profile.backend.VLLM_MODEL_NAME ?? '-') }}
          </div>
          <div class="hint mono">project-base={{ profileDefaultBaseModel(profile) }}</div>
        </button>
      </div>

      <div class="hint mono">
        env-files: backend={{ systemConfig?.env_files.backend ?? '-' }} · frontend={{ systemConfig?.env_files.frontend ?? '-' }}
      </div>
      <div class="hint mono">
        runtime:
        <span data-testid="system-runtime-backend">{{ systemConfig?.runtime.annotation_backend ?? '-' }}</span>
        ·
        <span data-testid="system-runtime-model">{{ systemConfig?.runtime.vllm_model_name ?? '-' }}</span>
        · timeout=<span data-testid="system-runtime-timeout">{{ systemConfig?.runtime.llm_request_timeout_seconds ?? '-' }}</span>
      </div>
      <div v-if="systemMessage" class="hint settings-warn" data-testid="system-profile-message">{{ systemMessage }}</div>
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
            {{ finetuneStarting ? 'Starting...' : 'Start Finetune' }}
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
        <div class="hint mono">runner={{ String(latestFinetuneJob.config?.runner_backend ?? '-') }}</div>
        <div class="hint mono">{{ latestFinetuneMetricText }}</div>
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
        <select v-model="evaluationModelTag" class="input compact" data-testid="evaluation-model-tag-select">
          <option v-for="modelTag in availableProjectModelTags" :key="modelTag" :value="modelTag">
            {{ modelTag }}
          </option>
        </select>
        <button
          class="btn primary"
          data-testid="evaluation-start-btn"
          type="button"
          :disabled="!canStartEvaluation"
          @click="startEvaluation"
        >
          {{ evaluationStarting ? 'Starting...' : 'Run Evaluation (M15)' }}
        </button>
      </div>
      <div class="hint">
        Evaluation compares fresh auto-annotation predictions against confirmed ground truth on val/test images. M15 adds run comparison, failure analysis, and timing summaries. Quality sorting still uses the project threshold:
        <span class="mono">{{ qualityReviewThreshold.toFixed(2) }}</span>
      </div>
      <div v-if="evaluationMessage" class="hint evaluation-status">{{ evaluationMessage }}</div>
      <div v-if="latestEvaluationRun" class="task">
        <div class="task-meta" data-testid="evaluation-status">
          run={{ latestEvaluationRun.id }} - {{ latestEvaluationRun.status }} - split={{ latestEvaluationRun.split }} - model={{ latestEvaluationRun.model_tag }}
        </div>
        <div class="hint mono" data-testid="evaluation-inference-route">{{ latestEvaluationInferenceText }}</div>
        <div class="hint mono">report={{ latestEvaluationRun.report_path ?? '-' }}</div>

        <div v-if="latestEvaluationRun.metrics" class="evaluation-grid">
          <section class="evaluation-panel">
            <h3 class="evaluation-title">Latest Metrics</h3>
            <div class="metric-grid">
              <article class="metric-card" data-testid="evaluation-metric-precision">
                <span class="metric-label">Precision</span>
                <strong>{{ formatMetricCompact(latestEvaluationRun.metrics?.precision) }}</strong>
              </article>
              <article class="metric-card" data-testid="evaluation-metric-recall">
                <span class="metric-label">Recall</span>
                <strong>{{ formatMetricCompact(latestEvaluationRun.metrics?.recall) }}</strong>
              </article>
              <article class="metric-card" data-testid="evaluation-metric-f1">
                <span class="metric-label">F1</span>
                <strong>{{ formatMetricCompact(latestEvaluationRun.metrics?.f1) }}</strong>
              </article>
              <article class="metric-card" data-testid="evaluation-metric-miou-bbox">
                <span class="metric-label">mIoU bbox</span>
                <strong>{{ formatMetricCompact(latestEvaluationRun.metrics?.miou_bbox) }}</strong>
              </article>
              <article class="metric-card" data-testid="evaluation-metric-miou-mask">
                <span class="metric-label">mIoU mask</span>
                <strong>{{ formatMetricCompact(latestEvaluationRun.metrics?.miou_mask) }}</strong>
              </article>
              <article class="metric-card" data-testid="evaluation-metric-dice">
                <span class="metric-label">Dice</span>
                <strong>{{ formatMetricCompact(latestEvaluationRun.metrics?.dice) }}</strong>
              </article>
            </div>

            <div v-if="evaluationReport?.performance" class="metric-grid compact-grid">
              <article class="metric-card">
                <span class="metric-label">Avg total ms</span>
                <strong>{{ formatMetricCompact(evaluationReport.performance.avg_total_ms, 2) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">Avg LLM ms</span>
                <strong>{{ formatMetricCompact(evaluationReport.performance.avg_llm_ms, 2) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">Avg SAM ms</span>
                <strong>{{ formatMetricCompact(evaluationReport.performance.avg_sam_ms, 2) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">Fallback images</span>
                <strong>{{ formatMetricCompact(evaluationReport.performance.fallback_images, 0) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">Failure images</span>
                <strong>{{ formatMetricCompact(evaluationReport.summary?.images_with_failures, 0) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">Perfect images</span>
                <strong>{{ formatMetricCompact(evaluationReport.summary?.perfect_images, 0) }}</strong>
              </article>
            </div>

            <details class="details-block">
              <summary>Raw metrics JSON</summary>
              <pre class="log-box" data-testid="evaluation-metrics">{{ latestEvaluationMetricsText }}</pre>
            </details>
          </section>

          <section class="evaluation-panel">
            <div class="row wrap-row compare-headline">
              <h3 class="evaluation-title">Compare Runs</h3>
              <select v-model="evaluationBaselineRunId" class="input compact" data-testid="evaluation-compare-baseline-select">
                <option value="">Auto previous run</option>
                <option v-for="run in availableBaselineEvaluationRuns" :key="run.id" :value="String(run.id)">
                  #{{ run.id }} - {{ run.model_tag }} - {{ run.split }}
                </option>
              </select>
            </div>

            <div v-if="evaluationComparisonLoading" class="hint">Loading comparison...</div>
            <template v-else-if="evaluationComparison">
              <div class="hint mono">
                baseline=#{{ evaluationComparison.baseline_run.id }} {{ evaluationComparison.baseline_run.model_tag }}
                路 current=#{{ evaluationComparison.current_run.id }} {{ evaluationComparison.current_run.model_tag }}
              </div>
              <div class="compare-table" data-testid="evaluation-comparison-summary">
                <div class="compare-header">
                  <span>Metric</span>
                  <span>Baseline</span>
                  <span>Current</span>
                  <span>Delta</span>
                </div>
                <div v-for="row in evaluationComparisonMetricRows" :key="row.key" class="compare-row">
                  <span>{{ row.label }}</span>
                  <span>{{ formatMetric(row.entry?.baseline, row.digits) }}</span>
                  <span>{{ formatMetric(row.entry?.current, row.digits) }}</span>
                  <span :class="deltaClass(row.entry?.delta)">{{ formatDelta(row.entry?.delta, row.digits) }}</span>
                </div>
              </div>

              <div v-if="evaluationComparisonPerformanceRows.length" class="compare-table secondary-table">
                <div class="compare-header">
                  <span>Perf</span>
                  <span>Baseline</span>
                  <span>Current</span>
                  <span>Delta</span>
                </div>
                <div v-for="row in evaluationComparisonPerformanceRows" :key="row.key" class="compare-row">
                  <span>{{ row.label }}</span>
                  <span>{{ formatMetric(row.entry?.baseline, row.digits) }}</span>
                  <span>{{ formatMetric(row.entry?.current, row.digits) }}</span>
                  <span :class="deltaClass(row.entry?.delta)">{{ formatDelta(row.entry?.delta, row.digits) }}</span>
                </div>
              </div>

              <div v-if="evaluationPerLabelRows.length" class="comparison-list">
                <div class="comparison-subtitle">Per-label F1 delta</div>
                <article v-for="row in evaluationPerLabelRows.slice(0, 6)" :key="row.label" class="comparison-card">
                  <div class="comparison-card-title">{{ row.label }}</div>
                  <div class="hint mono">
                    baseline={{ formatMetric(row.entry?.baseline) }} 路 current={{ formatMetric(row.entry?.current) }}
                  </div>
                  <div class="hint mono" :class="deltaClass(row.entry?.delta)">delta={{ formatDelta(row.entry?.delta) }}</div>
                </article>
              </div>

              <div v-if="evaluationComparison.top_regressions?.length" class="comparison-list">
                <div class="comparison-subtitle">Top regressions</div>
                <article
                  v-for="item in evaluationComparison.top_regressions.slice(0, 3)"
                  :key="`regression-${item.image_id}`"
                  class="comparison-card"
                >
                  <div class="comparison-card-title">#{{ item.image_id }} {{ item.filename ?? 'image' }}</div>
                  <div class="hint mono">
                    err={{ item.baseline.error_count }} -> {{ item.current.error_count }}
                    路 f1={{ formatMetric(item.baseline.f1) }} -> {{ formatMetric(item.current.f1) }}
                  </div>
                  <div class="hint mono" :class="deltaClass(item.delta.f1)">
                    delta err={{ item.delta.error_count ?? '-' }} 路 f1={{ formatDelta(item.delta.f1) }}
                  </div>
                </article>
              </div>
            </template>
            <div v-else class="hint">Run at least two completed evaluations to unlock comparison.</div>
          </section>

          <section class="evaluation-panel">
            <h3 class="evaluation-title">Failure Samples</h3>
            <div v-if="latestEvaluationFailureSamples.length" class="failure-list" data-testid="evaluation-failure-samples">
              <article v-for="sample in latestEvaluationFailureSamples" :key="sample.image_id" class="failure-card">
                <div class="failure-card-title">#{{ sample.image_id }} {{ sample.filename }}</div>
                <div class="hint mono">
                  fp={{ sample.fp }} 路 fn={{ sample.fn }} 路 f1={{ formatMetric(sample.f1) }} 路 bbox={{ formatMetric(sample.miou_bbox) }}
                </div>
                <div class="hint mono">
                  pred-miss={{ formatLabelList(sample.unmatched_prediction_labels) }}
                </div>
                <div class="hint mono">
                  gt-miss={{ formatLabelList(sample.unmatched_ground_truth_labels) }}
                </div>
              </article>
            </div>
            <div v-else class="hint">No failed samples in the latest completed run.</div>
          </section>
        </div>
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

.settings-headline {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 12px;
}

.settings-block {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.settings-title {
  margin: 0;
  font-size: 14px;
}

.checkbox {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  opacity: 0.85;
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

.settings-success {
  color: rgba(56, 211, 159, 0.95);
}

.settings-warn {
  color: rgba(250, 204, 21, 0.95);
}

.finetune-status {
  color: rgba(125, 211, 252, 0.95);
}

.evaluation-status {
  color: rgba(250, 204, 21, 0.95);
}

.evaluation-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.evaluation-panel {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.12);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.evaluation-title {
  margin: 0;
  font-size: 14px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.metric-grid.compact-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.metric-card {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.03);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.metric-label {
  font-size: 12px;
  opacity: 0.72;
}

.details-block {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 10px;
}

.details-block summary {
  cursor: pointer;
  opacity: 0.82;
}

.compare-headline {
  justify-content: space-between;
}

.compare-table {
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  overflow: hidden;
}

.secondary-table {
  margin-top: 4px;
}

.compare-header,
.compare-row {
  display: grid;
  grid-template-columns: minmax(90px, 1.3fr) repeat(3, minmax(0, 1fr));
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  font-size: 12px;
}

.compare-header {
  background: rgba(255, 255, 255, 0.05);
  font-weight: 650;
}

.compare-row:nth-child(odd) {
  background: rgba(255, 255, 255, 0.02);
}

.comparison-list,
.failure-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.comparison-subtitle {
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  opacity: 0.68;
}

.comparison-card,
.failure-card {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.03);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.comparison-card-title,
.failure-card-title {
  font-weight: 650;
}

.delta-positive {
  color: rgba(56, 211, 159, 0.95);
}

.delta-negative {
  color: rgba(248, 81, 73, 0.95);
}

.delta-neutral {
  opacity: 0.72;
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

.profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin: 12px 0;
}

.profile-card {
  text-align: left;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: inherit;
  padding: 12px;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  cursor: pointer;
}

.profile-card.active {
  border-color: rgba(56, 211, 159, 0.5);
  background: rgba(56, 211, 159, 0.08);
}

.profile-title {
  font-weight: 650;
}

.profile-desc {
  font-size: 13px;
  opacity: 0.78;
  min-height: 36px;
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

  .settings-grid {
    grid-template-columns: 1fr;
  }

  .metric-grid,
  .metric-grid.compact-grid {
    grid-template-columns: 1fr;
  }

  .compare-header,
  .compare-row {
    grid-template-columns: 1fr 1fr;
  }

  .input.compact {
    flex: 1 1 auto;
  }
}
</style>
