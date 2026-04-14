import type {
  AnnotationRecord,
  BackendClient,
  DiagnosticsSnapshot,
  EvaluationRun,
  FailureSample,
  ImageDetail,
  ImageRecord,
  ProjectMetaPayload,
  ProjectSettingsPayload,
  ProjectSettingsUpdateResponse,
  ProjectSummary,
  ProjectWorkspace,
  ReviewQueueItem,
  RuntimeSettings,
  SettingsChange,
  SystemConfig,
  SystemProfile,
  SystemSettingsPayload,
  TaskSnapshot,
  TrainMetricPoint,
  TrainJob,
  WorkflowDefinition,
} from './types'

type ProjectState = {
  id: number
  name: string
  taskType: ProjectSummary['taskType']
  workflowKey: string
  labels: string[]
  activeModelTag: string
  createdAt: string
  runtimeProfile: string
  latestEvaluationDice: number | null
  latestFinetuneTag: string | null
  task: TaskSnapshot
  images: ImageDetail[]
  trainJobs: TrainJob[]
  evaluations: EvaluationRun[]
  failureSamples: FailureSample[]
}

type MockState = {
  workflows: WorkflowDefinition[]
  projects: ProjectState[]
  profiles: SystemProfile[]
  runtime: RuntimeSettings
  systemSettings: SystemSettingsPayload
  diagnostics: DiagnosticsSnapshot
  nextProjectId: number
  nextImageId: number
  nextAnnotationId: number
  nextTrainJobId: number
  nextEvaluationId: number
}

const delay = (ms = 90) => new Promise((resolve) => window.setTimeout(resolve, ms))
const SYSTEM_HOT_RELOAD_PATHS = [
  'llm.maxTokens',
  'postprocess.enableClose',
  'postprocess.closeKernel',
  'postprocess.enableDpSimplify',
  'postprocess.epsilonRatio',
  'postprocess.minAreaRatio',
  'quality.enable',
  'quality.thresholdReview',
  'quality.thresholdOk',
  'quality.useLlmConfidence',
  'quality.useSamScore',
  'quality.enableConsistencyCheck',
  'evaluation.split',
  'evaluation.iouThreshold',
  'evaluation.maxSamples',
]
const SYSTEM_RELOAD_REQUIRED_PATHS = ['modelProfile', 'llm.baseModel', 'sam.checkpoint', 'sam.device', 'sam.multimaskOutput']

function nowText(): string {
  return new Date().toISOString().slice(0, 19).replace('T', ' ')
}

function buildTrainMetricPoint(
  epoch: number,
  epochTotal: number,
  step: number,
  loss: number,
  learningRate: number,
): TrainMetricPoint {
  return {
    epoch,
    epochTotal,
    step,
    loss,
    learningRate,
    raw: `Epoch ${epoch}/${epochTotal} | loss: ${loss.toFixed(4)} | lr: ${learningRate.toFixed(6)}`,
  }
}

function buildLossCurveLabel(metrics: TrainMetricPoint[]): string {
  const last = metrics[metrics.length - 1]
  if (!last) return '曲线=等待中'
  const epoch = last.epoch ?? '-'
  const loss = last.loss != null ? last.loss.toFixed(4) : '-'
  return `曲线=${metrics.length} 点 · 轮次=${epoch} · 损失=${loss}`
}

function cloneTrainMetrics(metrics: TrainMetricPoint[]): TrainMetricPoint[] {
  return metrics.map((point) => ({ ...point }))
}

function cloneWorkflows(workflows: WorkflowDefinition[]): WorkflowDefinition[] {
  return workflows.map((workflow) => ({ ...workflow, capabilities: [...workflow.capabilities] }))
}

function createThumb(label: string, hue: string): string {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="480" height="320" viewBox="0 0 480 320">
      <rect width="480" height="320" fill="#dbe8ff"/>
      <rect x="26" y="28" width="428" height="264" fill="#edf4ff" stroke="${hue}" stroke-width="4"/>
      <path d="M72 218L146 136L226 178L322 102L392 180L426 218V252H72Z" fill="${hue}" fill-opacity="0.16"/>
      <rect x="98" y="102" width="180" height="110" fill="${hue}" fill-opacity="0.12" stroke="${hue}" stroke-width="4"/>
      <text x="96" y="74" fill="#10233F" font-family="IBM Plex Sans,Arial" font-size="28" font-weight="700">${label}</text>
    </svg>
  `.trim()
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

function buildAnnotation(id: number, label: string, confirmed: boolean, source: AnnotationRecord['source']): AnnotationRecord {
  return {
    id,
    label,
    source,
    confidence: source === 'manual' ? null : 0.88,
    confirmed,
    runtime: {
      provider: 'openai-compatible',
      modelTag: 'base',
      modelName: 'qwen3-vl-2b',
    },
    bbox: [0.22, 0.31, 0.71, 0.63],
    polygon: [
      [0.19, 0.36],
      [0.31, 0.24],
      [0.58, 0.27],
      [0.69, 0.49],
      [0.61, 0.73],
      [0.33, 0.78],
      [0.2, 0.65],
    ],
    positivePoints: 2,
    negativePoints: 1,
  }
}

function bboxToRectPolygon(bbox: [number, number, number, number]): [number, number][] {
  const [xmin, ymin, xmax, ymax] = bbox
  return [
    [xmin, ymin],
    [xmax, ymin],
    [xmax, ymax],
    [xmin, ymax],
  ]
}

function createManualAnnotation(
  project: ProjectState,
  label: string,
  bbox: [number, number, number, number],
): AnnotationRecord {
  const workflow = getWorkflow(project.workflowKey)
  return {
    id: state.nextAnnotationId++,
    label,
    source: 'manual',
    confidence: null,
    confirmed: false,
    runtime: {
      provider: 'manual',
      modelTag: project.activeModelTag,
      modelName: state.runtime.modelName,
    },
    bbox,
    polygon: workflow.taskFamily === 'instance_mask' ? bboxToRectPolygon(bbox) : [],
    positivePoints: 0,
    negativePoints: 0,
  }
}

function buildImage(
  id: number,
  filename: string,
  split: ImageRecord['split'],
  status: ImageRecord['status'],
  qualityScore: number | null,
  annotationCount: number,
  hue: string,
  annotations: AnnotationRecord[],
): ImageDetail {
  return {
    id,
    filename,
    width: 1920,
    height: 1080,
    split,
    status,
    qualityScore,
    thumbnailUrl: createThumb(filename.replace('.png', ''), hue),
    reviewState: qualityScore == null ? 'unscored' : qualityScore < 0.65 ? 'review' : 'ok',
    annotationCount,
    imageUrl: createThumb(filename.replace('.png', ''), hue),
    annotations,
  }
}

function createWorkflows(): WorkflowDefinition[] {
  return [
    {
      key: 'generic_detection',
      displayName: '目标检测',
      description: 'bbox',
      taskType: 'detection',
      taskFamily: 'bbox',
      supportsAutoAnnotation: true,
      supportsManualBBox: true,
      supportsPointRefine: false,
      capabilities: ['llm_grounding', 'manual_bbox_edit', 'evaluation_adapter'],
    },
    {
      key: 'generic_instance_segmentation',
      displayName: '实例分割',
      description: 'bbox + polygon + point',
      taskType: 'segmentation',
      taskFamily: 'instance_mask',
      supportsAutoAnnotation: true,
      supportsManualBBox: true,
      supportsPointRefine: true,
      capabilities: ['llm_grounding', 'sam_refine', 'point_refine', 'evaluation_adapter'],
    },
  ]
}

function createProfiles(): SystemProfile[] {
  return [
    {
      name: 'dev_low_resource',
      description: '模拟 / CPU / 最小资源',
      annotationBackend: 'stub',
      modelName: 'qwen3-vl-2b',
    },
    {
      name: 'test_real_stack',
      description: '真实路由 / Redis / SAM2',
      annotationBackend: 'openai-compatible',
      modelName: 'qwen3-vl-2b',
    },
    {
      name: 'demo_prod',
      description: '演示配置',
      annotationBackend: 'openai-compatible',
      modelName: 'qwen3-vl-4b',
    },
  ]
}

function createSystemSettings(activeProfile = 'test_real_stack'): SystemSettingsPayload {
  return {
    modelProfile: activeProfile,
    llm: {
      baseModel: activeProfile === 'demo_prod' ? 'qwen3-vl-4b' : 'qwen3-vl-2b',
      autoOrder: ['2b', '4b', '8b'],
      maxTokens: 2048,
    },
    sam: {
      checkpoint: 'sam2',
      device: activeProfile === 'dev_low_resource' ? 'cpu' : 'cuda',
      multimaskOutput: false,
    },
    postprocess: {
      enableClose: true,
      closeKernel: 5,
      enableDpSimplify: true,
      epsilonRatio: 0.002,
      minAreaRatio: 0.0005,
    },
    quality: {
      enable: true,
      thresholdReview: 0.6,
      thresholdOk: 0.8,
      useLlmConfidence: true,
      useSamScore: true,
      enableConsistencyCheck: false,
    },
    evaluation: {
      split: 'val',
      iouThreshold: 0.5,
      maxSamples: 120,
    },
    _meta: {
      hotReloadPaths: [...SYSTEM_HOT_RELOAD_PATHS],
      reloadRequiredPaths: [...SYSTEM_RELOAD_REQUIRED_PATHS],
      availableModelProfiles: ['auto', 'fixed', 'dev_low_resource', 'test_real_stack', 'demo_prod'],
      activeSystemProfile: activeProfile,
      resolvedRuntimeProfile: activeProfile,
      storagePath: 'data/system/runtime_settings.json',
      note: '全局运行时设置会影响所有项目。可热更新字段会影响后续新任务；需重载字段需要显式切换配置档或重启前端。',
    },
  }
}

function cloneSystemSettings(settings: SystemSettingsPayload): SystemSettingsPayload {
  return {
    modelProfile: settings.modelProfile,
    llm: { ...settings.llm, autoOrder: [...settings.llm.autoOrder] },
    sam: { ...settings.sam },
    postprocess: { ...settings.postprocess },
    quality: { ...settings.quality },
    evaluation: { ...settings.evaluation },
    _meta: {
      ...settings._meta,
      hotReloadPaths: [...settings._meta.hotReloadPaths],
      reloadRequiredPaths: [...settings._meta.reloadRequiredPaths],
      availableModelProfiles: [...settings._meta.availableModelProfiles],
    },
  }
}

function buildRuntimeSummary(profiles: SystemProfile[], settings: SystemSettingsPayload): RuntimeSettings {
  const activeProfile = profiles.find((profile) => profile.name === settings._meta.activeSystemProfile) ?? profiles[0]
  return {
    activeProfile: activeProfile?.name ?? settings._meta.activeSystemProfile,
    annotationBackend: activeProfile?.annotationBackend ?? 'stub',
    modelName: settings.llm.baseModel,
    requestTimeoutSeconds: activeProfile?.name === 'dev_low_resource' ? 20 : 15,
    maxRetries: activeProfile?.name === 'dev_low_resource' ? 1 : 2,
    reloadRequiredPaths: [...settings._meta.reloadRequiredPaths],
    profiles: profiles.map((profile) => ({ ...profile })),
  }
}

function buildSystemConfig(profiles: SystemProfile[], runtime: RuntimeSettings, settings: SystemSettingsPayload): SystemConfig {
  return {
    activeProfile: runtime.activeProfile,
    profiles: profiles.map((profile) => ({ ...profile })),
    settings: cloneSystemSettings(settings),
    envFiles: {
      backend: '.env.active',
      frontend: 'frontend/.env.local',
    },
    runtime: {
      appProfile: runtime.activeProfile,
      annotationBackend: runtime.annotationBackend,
      modelName: runtime.modelName,
      llmRequestTimeoutSeconds: runtime.requestTimeoutSeconds,
      llmMaxRetries: runtime.maxRetries,
      llmMaxTokens: settings.llm.maxTokens,
    },
    metadata: {
      hotReloadFields: [...SYSTEM_HOT_RELOAD_PATHS],
      restartRequiredFields: ['frontend.vite_env', 'sam.device', 'sam.checkpoint'],
      note: '配置档会写入后端与前端环境文件；前端 Vite 环境变量变更后需要重启。',
    },
  }
}

function createInitialState(): MockState {
  const workflows = createWorkflows()
  const profiles = createProfiles()
  const systemSettings = createSystemSettings('test_real_stack')
  return {
    workflows,
    profiles,
    projects: [
      {
        id: 12,
        name: '建筑质检批次 01',
        taskType: 'segmentation',
        workflowKey: 'generic_instance_segmentation',
        labels: ['建筑', '棚屋', '屋顶'],
        activeModelTag: 'base',
        createdAt: '2026-04-12 09:18:42',
        runtimeProfile: 'test_real_stack',
        latestEvaluationDice: 0.78,
        latestFinetuneTag: 'lora:4',
        task: {
          id: 'annotate-12',
          kind: 'project_annotate',
          status: 'RUNNING',
          progress: 67,
          transport: 'websocket',
          message: '图片 16/24 已生成 4 个多边形',
          updatedAt: nowText(),
        },
        images: [
          buildImage(1801, 'img_018.png', 'train', 'done', 0.42, 4, '#0B5FFF', [buildAnnotation(901, '建筑', false, 'auto')]),
          buildImage(1701, 'img_017.png', 'train', 'annotating', 0.57, 3, '#1A7CFF', [buildAnnotation(902, '建筑', false, 'auto')]),
          buildImage(1601, 'img_016.png', 'val', 'pending', null, 0, '#2F8BFF', []),
          buildImage(1501, 'img_014.png', 'train', 'done', 0.51, 3, '#549CFF', [buildAnnotation(903, '建筑', false, 'auto')]),
          buildImage(1401, 'img_006.png', 'test', 'done', 0.58, 2, '#80B5FF', [buildAnnotation(904, '棚屋', true, 'corrected')]),
        ],
        trainJobs: [
          {
            id: 4,
            status: 'SUCCESS',
            modelTag: 'lora:4',
            startedAt: '2026-04-14 09:12:03',
            datasetPath: 'data/projects/12/exports/finetune/job_4/project_12_train.jsonl',
            logPath: 'logs/finetune/4.log',
            taskId: 'finetune-4',
            config: {
              dataset: 'project_12_train',
              num_train_epochs: 3,
              learning_rate: 0.0001,
              per_device_train_batch_size: 1,
              gradient_accumulation_steps: 8,
              logging_steps: 1,
            },
            lossCurveLabel: '曲线=214 点 · 轮次=3 · 损失=0.3184',
            logExcerpt: ['step=188 loss=0.3521', 'step=214 loss=0.3184', '适配器已保存到 lora/job_4'],
            metrics: [
              buildTrainMetricPoint(1, 3, 70, 0.612, 0.0001),
              buildTrainMetricPoint(2, 3, 140, 0.431, 0.0001),
              buildTrainMetricPoint(3, 3, 214, 0.3184, 0.0001),
            ],
            active: false,
          },
        ],
        evaluations: [
          {
            id: 31,
            status: 'SUCCESS',
            split: 'val',
            modelTag: 'base',
            precision: 0.82,
            recall: 0.76,
            f1: 0.79,
            miouBBox: 0.73,
            miouMask: 0.71,
            dice: 0.78,
            avgTotalMs: 1240,
            fallbackImages: 0,
            createdAt: '2026-04-14 10:42:18',
          },
          {
            id: 29,
            status: 'SUCCESS',
            split: 'val',
            modelTag: 'lora:4',
            precision: 0.79,
            recall: 0.74,
            f1: 0.76,
            miouBBox: 0.71,
            miouMask: 0.69,
            dice: 0.74,
            avgTotalMs: 1306,
            fallbackImages: 1,
            createdAt: '2026-04-13 18:11:02',
          },
        ],
        failureSamples: [
          { imageId: 1401, filename: 'img_006.png', fp: 1, fn: 2, f1: 0.53 },
          { imageId: 1501, filename: 'img_014.png', fp: 0, fn: 1, f1: 0.74 },
        ],
      },
      {
        id: 10,
        name: '道路病害检测',
        taskType: 'detection',
        workflowKey: 'generic_detection',
        labels: ['裂缝', '坑洞', '修补'],
        activeModelTag: 'base',
        createdAt: '2026-04-11 15:06:20',
        runtimeProfile: 'dev_low_resource',
        latestEvaluationDice: null,
        latestFinetuneTag: null,
        task: {
          id: 'annotate-10',
          kind: 'project_annotate',
          status: 'SUCCESS',
          progress: 100,
          transport: 'polling',
          message: '24 张图片已完成',
          updatedAt: nowText(),
        },
        images: [
          buildImage(1001, 'road_011.png', 'train', 'done', 0.74, 4, '#0B5FFF', [buildAnnotation(905, '裂缝', true, 'corrected')]),
          buildImage(1002, 'road_010.png', 'train', 'done', 0.69, 3, '#317DFF', [buildAnnotation(906, '修补', false, 'auto')]),
          buildImage(1003, 'road_009.png', 'val', 'done', 0.83, 2, '#4E95FF', [buildAnnotation(907, '坑洞', true, 'auto')]),
        ],
        trainJobs: [],
        evaluations: [],
        failureSamples: [],
      },
    ],
    runtime: buildRuntimeSummary(profiles, systemSettings),
    systemSettings,
    diagnostics: {
      lastRunAt: '2026-04-14 15:24:08',
      services: [
        { name: 'frontend', status: 'healthy' },
        { name: 'api', status: 'healthy' },
        { name: 'worker', status: 'healthy' },
        { name: 'vllm', status: 'degraded' },
        { name: 'redis', status: 'healthy' },
      ],
      selftest: [
        { name: 'api_health', status: 'PASS' },
        { name: 'redis_connectivity', status: 'PASS' },
        { name: 'vllm_minimal_inference', status: 'TIMEOUT' },
        { name: 'task_chain_validation', status: 'SKIPPED' },
      ],
      caches: [
        { name: 'models/qwen3-vl-2b', status: 'ready' },
        { name: 'models/sam2', status: 'ready' },
        { name: 'hf_cache', status: '92GB' },
      ],
      commands: ['doctor', 'selftest', 'logs vllm', 'models status'],
    },
    nextProjectId: 20,
    nextImageId: 2000,
    nextAnnotationId: 1000,
    nextTrainJobId: 8,
    nextEvaluationId: 40,
  }
}

const state: MockState = createInitialState()

export function resetMockBackend(): void {
  const fresh = createInitialState()
  state.workflows = fresh.workflows
  state.profiles = fresh.profiles
  state.projects = fresh.projects
  state.runtime = fresh.runtime
  state.systemSettings = fresh.systemSettings
  state.diagnostics = fresh.diagnostics
  state.nextProjectId = fresh.nextProjectId
  state.nextImageId = fresh.nextImageId
  state.nextAnnotationId = fresh.nextAnnotationId
  state.nextTrainJobId = fresh.nextTrainJobId
  state.nextEvaluationId = fresh.nextEvaluationId
}

function getWorkflow(key: string): WorkflowDefinition {
  const workflow = state.workflows.find((item) => item.key === key)
  if (!workflow) {
    throw new Error(`Unknown workflow: ${key}`)
  }
  return workflow
}

function deriveTaskFamily(workflowKey: string): ProjectSummary['taskFamily'] {
  return getWorkflow(workflowKey).taskFamily
}

function getProjectOrThrow(projectId: number): ProjectState {
  const project = state.projects.find((item) => item.id === projectId)
  if (!project) {
    throw new Error(`Project ${projectId} not found`)
  }
  return project
}

function reviewQueueFor(project: ProjectState): ReviewQueueItem[] {
  return project.images
    .filter((image) => image.qualityScore != null && Number(image.qualityScore) < 0.65)
    .sort((left, right) => (left.qualityScore ?? 1) - (right.qualityScore ?? 1))
    .map((image) => ({
      imageId: image.id,
      filename: image.filename,
      qualityScore: image.qualityScore,
      annotationCount: image.annotationCount,
      fallbackUsed: image.annotations.some((annotation) => annotation.runtime.modelTag === 'fallback'),
    }))
}

function projectSummary(project: ProjectState): ProjectSummary {
  return {
    id: project.id,
    name: project.name,
    taskType: project.taskType,
    workflowKey: project.workflowKey,
    taskFamily: deriveTaskFamily(project.workflowKey),
    createdAt: project.createdAt,
    imageCount: project.images.length,
    reviewCount: reviewQueueFor(project).length,
    activeModelTag: project.activeModelTag,
    lastTaskStatus: project.task.status,
    lastTaskUpdatedAt: project.task.updatedAt,
  }
}

function projectMetaPayload(): ProjectMetaPayload {
  return {
    taskTypes: ['detection', 'segmentation'],
    defaultWorkflows: {
      detection: 'generic_detection',
      segmentation: 'generic_instance_segmentation',
    },
    workflows: cloneWorkflows(state.workflows),
  }
}

function projectSettingsPayload(project: ProjectState): ProjectSettingsPayload {
  const workflow = getWorkflow(project.workflowKey)
  return {
    workflowKey: workflow.key,
    taskFamily: workflow.taskFamily,
    workflow: { ...workflow, capabilities: [...workflow.capabilities] },
    labels: [...project.labels],
    activeModelTag: project.activeModelTag,
    _meta: {
      projectEditablePaths: ['labels', 'workflow_key', 'active_model_tag'],
      availableWorkflows: cloneWorkflows(state.workflows),
      activeSystemProfile: state.runtime.activeProfile,
      resolvedProjectProfile: project.runtimeProfile,
      note: '项目级保存工作流、标签与激活版本；运行时默认值统一走全局设置。',
    },
  }
}

function buildProjectSettingsChange(
  patch: Partial<Pick<ProjectSettingsPayload, 'workflowKey' | 'labels' | 'activeModelTag'>>,
): SettingsChange {
  const changedPaths: string[] = Object.keys(patch)
    .map((key) => {
      if (key === 'workflowKey') return 'workflow_key'
      if (key === 'activeModelTag') return 'active_model_tag'
      return key
    })
    .sort()
  const hotReloadPaths: string[] = changedPaths.filter((path) => path === 'labels')
  const reloadRequiredPaths: string[] = []
  const otherPaths = changedPaths.filter((path) => !hotReloadPaths.includes(path))
  return {
    changedPaths,
    hotReloadPaths,
    reloadRequiredPaths,
    otherPaths,
    reloadRequired: false,
    message: changedPaths.length === 0 ? '没有检测到变更。' : '已保存项目设置。新的任务将使用最新工作流、标签与激活版本。',
  }
}

function cloneImageDetail(image: ImageDetail): ImageDetail {
  return {
    ...image,
    annotations: image.annotations.map((annotation) => ({ ...annotation, runtime: { ...annotation.runtime }, polygon: [...annotation.polygon] })),
  }
}

function cloneWorkspace(project: ProjectState): ProjectWorkspace {
  return {
    summary: projectSummary(project),
    labels: [...project.labels],
    activeModelTag: project.activeModelTag,
    runtimeProfile: project.runtimeProfile,
    latestEvaluationDice: project.latestEvaluationDice,
    latestFinetuneTag: project.latestFinetuneTag,
    images: project.images.map((image) => ({
      id: image.id,
      filename: image.filename,
      width: image.width,
      height: image.height,
      split: image.split,
      status: image.status,
      qualityScore: image.qualityScore,
      thumbnailUrl: image.thumbnailUrl,
      reviewState: image.reviewState,
      annotationCount: image.annotationCount,
    })),
    reviewQueue: reviewQueueFor(project),
    task: { ...project.task },
    workflow: { ...getWorkflow(project.workflowKey), capabilities: [...getWorkflow(project.workflowKey).capabilities] },
  }
}

function refreshProjectQuality(project: ProjectState): void {
  for (const image of project.images) {
    const allConfirmed = image.annotations.length > 0 && image.annotations.every((annotation) => annotation.confirmed)
    if (allConfirmed) {
      image.qualityScore = 0.94
      image.reviewState = 'ok'
    } else if (image.qualityScore == null) {
      image.reviewState = 'unscored'
    } else {
      image.reviewState = image.qualityScore < 0.65 ? 'review' : 'ok'
    }
  }
}

function startTaskSimulation(project: ProjectState): void {
  const taskId = project.task.id
  const timer = window.setInterval(() => {
    const liveProject = state.projects.find((item) => item.task.id === taskId)
    if (!liveProject) {
      window.clearInterval(timer)
      return
    }
    if (liveProject.task.status !== 'RUNNING') {
      window.clearInterval(timer)
      return
    }
    const nextProgress = Math.min(100, liveProject.task.progress + 11)
    liveProject.task.progress = nextProgress
    liveProject.task.updatedAt = nowText()
    const doneCount = Math.floor((nextProgress / 100) * liveProject.images.length)
    liveProject.images.forEach((image, index) => {
      if (index < doneCount) {
        image.status = 'done'
        if (image.annotations.length === 0) {
          const annotationId = state.nextAnnotationId++
          image.annotations = [buildAnnotation(annotationId, liveProject.labels[0] ?? '目标', false, 'auto')]
          image.annotationCount = image.annotations.length
          image.qualityScore = 0.58 + index * 0.04
          image.reviewState = (image.qualityScore ?? 0) < 0.65 ? 'review' : 'ok'
        }
      } else if (index === doneCount) {
        image.status = 'annotating'
      }
    })
    liveProject.task.message = `图片 ${Math.min(doneCount + 1, liveProject.images.length)}/${liveProject.images.length} 已生成 ${liveProject.labels.length || 1} 条结果`
    if (nextProgress >= 100) {
      liveProject.task.status = 'SUCCESS'
      liveProject.task.transport = 'websocket'
      liveProject.task.message = `${liveProject.images.length} 张图片已完成`
      liveProject.images.forEach((image) => {
        if (image.status !== 'error') image.status = 'done'
      })
      window.clearInterval(timer)
    }
  }, 680)
}

function startTrainSimulation(project: ProjectState, jobId: number): void {
  const simulatedMetrics = [
    buildTrainMetricPoint(1, 4, 61, 0.612, 0.0001),
    buildTrainMetricPoint(2, 4, 122, 0.431, 0.0001),
    buildTrainMetricPoint(3, 4, 183, 0.317, 0.0001),
    buildTrainMetricPoint(4, 4, 286, 0.2817, 0.00008),
  ]
  const timer = window.setInterval(() => {
    const liveProject = getProjectOrThrow(project.id)
    const job = liveProject.trainJobs.find((item) => item.id === jobId)
    if (!job || job.status !== 'RUNNING') {
      window.clearInterval(timer)
      return
    }
    const nextPoint = simulatedMetrics[job.metrics.length]
    if (!nextPoint) {
      job.status = 'SUCCESS'
      job.lossCurveLabel = buildLossCurveLabel(job.metrics)
      job.logExcerpt = [
        `step=${job.metrics[job.metrics.length - 2]?.step ?? 183} loss=${job.metrics[job.metrics.length - 2]?.loss?.toFixed(4) ?? '0.3170'}`,
        `step=${job.metrics[job.metrics.length - 1]?.step ?? 286} loss=${job.metrics[job.metrics.length - 1]?.loss?.toFixed(4) ?? '0.2817'}`,
        `适配器已保存到 lora/job_${job.id}`,
      ]
      liveProject.latestFinetuneTag = job.modelTag
      window.clearInterval(timer)
      return
    }
    job.metrics.push({ ...nextPoint })
    job.lossCurveLabel = buildLossCurveLabel(job.metrics)
    job.logExcerpt = [
      ...job.logExcerpt.slice(-2),
      nextPoint.raw ?? `step=${nextPoint.step ?? '-'} loss=${nextPoint.loss ?? '-'}`,
    ].slice(-3)
  }, 620)
}

function startEvaluationSimulation(project: ProjectState, runId: number): void {
  const timer = window.setInterval(() => {
    const liveProject = getProjectOrThrow(project.id)
    const run = liveProject.evaluations.find((item) => item.id === runId)
    if (!run || run.status !== 'RUNNING') {
      window.clearInterval(timer)
      return
    }
    run.status = 'SUCCESS'
    run.precision = 0.84
    run.recall = 0.79
    run.f1 = 0.81
    run.miouBBox = 0.75
    run.miouMask = 0.73
    run.dice = 0.8
    run.avgTotalMs = 1186
    liveProject.latestEvaluationDice = run.dice
    liveProject.failureSamples = [
      { imageId: 1701, filename: 'img_017.png', fp: 1, fn: 1, f1: 0.68 },
      { imageId: 1601, filename: 'img_016.png', fp: 0, fn: 2, f1: 0.51 },
    ]
    window.clearInterval(timer)
  }, 1400)
}

function buildSettingsChange(patch: Partial<SystemSettingsPayload>): SettingsChange {
  const changedPaths = Object.entries(patch).flatMap(([key, value]) => {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return Object.keys(value).map((childKey) => `${key}.${childKey}`)
    }
    return [key]
  })
  const hotReloadPaths = changedPaths.filter((path) => SYSTEM_HOT_RELOAD_PATHS.includes(path))
  const reloadRequiredPaths = changedPaths.filter((path) => SYSTEM_RELOAD_REQUIRED_PATHS.includes(path))
  const otherPaths = changedPaths.filter((path) => !hotReloadPaths.includes(path) && !reloadRequiredPaths.includes(path))
  return {
    changedPaths,
    hotReloadPaths,
    reloadRequiredPaths,
    otherPaths,
    reloadRequired: reloadRequiredPaths.length > 0,
    message:
      reloadRequiredPaths.length > 0
        ? '已保存设置。部分字段需要重新切换配置档或重载前端后生效。'
        : '已保存设置。新的任务将立即使用最新配置。',
  }
}

export const mockBackend: BackendClient = {
  async getProjectMeta() {
    await delay()
    return projectMetaPayload()
  },
  async listProjects() {
    await delay()
    return state.projects.map(projectSummary).sort((left, right) => right.id - left.id)
  },
  async createProject(input) {
    await delay()
    const workflow = getWorkflow(input.workflowKey ?? (input.taskType === 'detection' ? 'generic_detection' : 'generic_instance_segmentation'))
    if (workflow.taskType !== input.taskType) {
      throw new Error(`workflow ${workflow.key} 与任务类型 ${input.taskType} 不兼容`)
    }
    const project: ProjectState = {
      id: state.nextProjectId++,
      name: input.name.trim(),
      taskType: input.taskType,
      workflowKey: workflow.key,
      labels: [],
      activeModelTag: 'base',
      createdAt: nowText(),
      runtimeProfile: state.runtime.activeProfile,
      latestEvaluationDice: null,
      latestFinetuneTag: null,
      task: {
        id: `annotate-${state.nextProjectId}`,
        kind: 'project_annotate',
        status: 'IDLE',
        progress: 0,
        transport: 'idle',
        message: '暂无任务',
        updatedAt: nowText(),
      },
      images: [
        buildImage(state.nextImageId++, 'seed_001.png', 'train', 'pending', null, 0, '#0B5FFF', []),
        buildImage(state.nextImageId++, 'seed_002.png', 'val', 'pending', null, 0, '#2F8BFF', []),
      ],
      trainJobs: [],
      evaluations: [],
      failureSamples: [],
    }
    state.projects.unshift(project)
    return { id: project.id }
  },
  async getProjectWorkspace(projectId) {
    await delay()
    return cloneWorkspace(getProjectOrThrow(projectId))
  },
  async getProjectSettings(projectId) {
    await delay()
    const project = getProjectOrThrow(projectId)
    return projectSettingsPayload(project)
  },
  async updateProjectSettings(projectId, patch) {
    await delay()
    const project = getProjectOrThrow(projectId)
    if (patch.workflowKey) {
      const workflow = getWorkflow(patch.workflowKey)
      if (workflow.taskType !== project.taskType) {
        throw new Error(`workflow ${workflow.key} 与项目任务类型 ${project.taskType} 不兼容`)
      }
      project.workflowKey = workflow.key
    }
    if (patch.labels) {
      project.labels = patch.labels.map((item) => item.trim()).filter(Boolean)
    }
    if (patch.activeModelTag) {
      const cleanedTag = patch.activeModelTag.trim()
      if (!cleanedTag) {
        throw new Error('activeModelTag is required')
      }
      if (cleanedTag !== 'base' && !project.trainJobs.some((job) => job.modelTag === cleanedTag && job.status === 'SUCCESS')) {
        throw new Error(`model ${cleanedTag} is not available for activation`)
      }
      project.activeModelTag = cleanedTag
      project.trainJobs = project.trainJobs.map((job) => ({
        ...job,
        active: job.modelTag === cleanedTag,
      }))
    }
    const response: ProjectSettingsUpdateResponse = {
      settings: projectSettingsPayload(project),
      change: buildProjectSettingsChange(patch),
    }
    return response
  },
  async activateProjectModel(projectId, modelTag) {
    await delay()
    const project = getProjectOrThrow(projectId)
    const cleanedTag = modelTag.trim()
    if (!cleanedTag) {
      throw new Error('modelTag is required')
    }
    if (cleanedTag !== 'base' && !project.trainJobs.some((job) => job.modelTag === cleanedTag && job.status === 'SUCCESS')) {
      throw new Error(`model ${cleanedTag} is not available for activation`)
    }
    project.activeModelTag = cleanedTag
    project.trainJobs = project.trainJobs.map((job) => ({
      ...job,
      active: job.modelTag === cleanedTag,
    }))
    return {
      settings: projectSettingsPayload(project),
      message: cleanedTag === 'base' ? '已切回基础模型。' : `已激活 ${cleanedTag}。`,
    }
  },
  async startBatchAnnotate(projectId) {
    await delay()
    const project = getProjectOrThrow(projectId)
    project.task = {
      id: `annotate-${projectId}-${Date.now()}`,
      kind: 'project_annotate',
      status: 'RUNNING',
      progress: 5,
      transport: 'websocket',
      message: '已排队',
      updatedAt: nowText(),
    }
    startTaskSimulation(project)
    return { ...project.task }
  },
  async getAnnotationStudio(projectId, imageId) {
    await delay()
    const project = getProjectOrThrow(projectId)
    const queue = reviewQueueFor(project)
    const defaultImageId = imageId ?? queue[0]?.imageId ?? project.images[0]?.id
    const image = project.images.find((item) => item.id === defaultImageId) ?? null
    return {
      project: projectSummary(project),
      workflow: { ...getWorkflow(project.workflowKey), capabilities: [...getWorkflow(project.workflowKey).capabilities] },
      queue,
      image: image ? cloneImageDetail(image) : null,
    }
  },
  async createAnnotation(projectId, imageId, input) {
    await delay()
    const project = getProjectOrThrow(projectId)
    const image = project.images.find((item) => item.id === imageId)
    if (!image) {
      throw new Error('Image not found')
    }
    const label = input.label.trim()
    if (!label) {
      throw new Error('Label is required')
    }
    const [xmin, ymin, xmax, ymax] = input.bbox
    const clamped: [number, number, number, number] = [
      Math.max(0, Math.min(1, xmin)),
      Math.max(0, Math.min(1, ymin)),
      Math.max(0, Math.min(1, xmax)),
      Math.max(0, Math.min(1, ymax)),
    ]
    if (clamped[2] - clamped[0] < 0.002 || clamped[3] - clamped[1] < 0.002) {
      throw new Error('Bbox is too small')
    }
    image.annotations = [...image.annotations, createManualAnnotation(project, label, clamped)]
    image.annotationCount = image.annotations.length
    image.status = 'done'
    image.qualityScore = image.qualityScore == null ? 0.82 : image.qualityScore
    refreshProjectQuality(project)
    return cloneImageDetail(image)
  },
  async confirmAnnotation(projectId, imageId, annotationId) {
    await delay()
    const project = getProjectOrThrow(projectId)
    const image = project.images.find((item) => item.id === imageId)
    if (!image) {
      throw new Error('Image not found')
    }
    image.annotations = image.annotations.map((annotation) =>
      annotation.id === annotationId ? { ...annotation, confirmed: true, source: 'corrected' } : annotation,
    )
    refreshProjectQuality(project)
    return cloneImageDetail(image)
  },
  async deleteAnnotation(projectId, imageId, annotationId) {
    await delay()
    const project = getProjectOrThrow(projectId)
    const image = project.images.find((item) => item.id === imageId)
    if (!image) {
      throw new Error('Image not found')
    }
    image.annotations = image.annotations.filter((annotation) => annotation.id !== annotationId)
    image.annotationCount = image.annotations.length
    if (image.annotationCount === 0) {
      image.qualityScore = null
      image.reviewState = 'unscored'
    }
    refreshProjectQuality(project)
    return cloneImageDetail(image)
  },
  async listTrainJobs(projectId) {
    await delay()
    return getProjectOrThrow(projectId).trainJobs.map((job) => ({
      ...job,
      config: job.config ? { ...job.config } : undefined,
      logExcerpt: [...job.logExcerpt],
      metrics: cloneTrainMetrics(job.metrics),
    }))
  },
  async startTrain(projectId) {
    await delay()
    const project = getProjectOrThrow(projectId)
    const job: TrainJob = {
      id: state.nextTrainJobId++,
      status: 'RUNNING',
      modelTag: `lora:${state.nextTrainJobId - 1}`,
      startedAt: nowText(),
      datasetPath: `data/projects/${projectId}/exports/finetune/job_${state.nextTrainJobId - 1}/project_${projectId}_train.jsonl`,
      logPath: `logs/finetune/${state.nextTrainJobId - 1}.log`,
      taskId: `finetune-${state.nextTrainJobId - 1}`,
      config: {
        dataset: `project_${projectId}_train`,
        num_train_epochs: 4,
        learning_rate: 0.0001,
        per_device_train_batch_size: 1,
        gradient_accumulation_steps: 8,
        logging_steps: 1,
      },
      lossCurveLabel: '曲线=等待中',
      logExcerpt: ['正在导出数据集', '正在获取 GPU 锁', '训练已启动'],
      metrics: [],
      active: false,
    }
    project.trainJobs.unshift(job)
    startTrainSimulation(project, job.id)
    return project.trainJobs.map((item) => ({
      ...item,
      config: item.config ? { ...item.config } : undefined,
      logExcerpt: [...item.logExcerpt],
      metrics: cloneTrainMetrics(item.metrics),
    }))
  },
  async listEvaluations(projectId) {
    await delay()
    const project = getProjectOrThrow(projectId)
    return {
      runs: project.evaluations.map((run) => ({ ...run })),
      failures: project.failureSamples.map((failure) => ({ ...failure })),
    }
  },
  async startEvaluation(projectId) {
    await delay()
    const project = getProjectOrThrow(projectId)
    const run: EvaluationRun = {
      id: state.nextEvaluationId++,
      status: 'RUNNING',
      split: 'val',
      modelTag: project.activeModelTag,
      precision: 0,
      recall: 0,
      f1: 0,
      miouBBox: 0,
      miouMask: 0,
      dice: 0,
      avgTotalMs: 0,
      fallbackImages: 0,
      createdAt: nowText(),
    }
    project.evaluations.unshift(run)
    startEvaluationSimulation(project, run.id)
    return {
      runs: project.evaluations.map((item) => ({ ...item })),
      failures: project.failureSamples.map((failure) => ({ ...failure })),
    }
  },
  async getRuntimeSettings() {
    await delay()
    return {
      ...state.runtime,
      profiles: state.runtime.profiles.map((profile) => ({ ...profile })),
      reloadRequiredPaths: [...state.runtime.reloadRequiredPaths],
    }
  },
  async activateProfile(profileName) {
    const config = await this.activateSystemProfile(profileName)
    return {
      activeProfile: config.activeProfile,
      annotationBackend: config.runtime.annotationBackend,
      modelName: config.runtime.modelName,
      requestTimeoutSeconds: config.runtime.llmRequestTimeoutSeconds,
      maxRetries: config.runtime.llmMaxRetries,
      reloadRequiredPaths: [...config.settings._meta.reloadRequiredPaths],
      profiles: config.profiles.map((profile) => ({ ...profile })),
    }
  },
  async getSystemConfig() {
    await delay()
    return buildSystemConfig(state.profiles, state.runtime, state.systemSettings)
  },
  async getSystemSettings() {
    await delay()
    return cloneSystemSettings(state.systemSettings)
  },
  async updateSystemSettings(patch) {
    await delay()
    const nextSettings = cloneSystemSettings(state.systemSettings)
    if (patch.modelProfile != null) nextSettings.modelProfile = patch.modelProfile
    if (patch.llm) nextSettings.llm = { ...nextSettings.llm, ...patch.llm, autoOrder: [...(patch.llm.autoOrder ?? nextSettings.llm.autoOrder)] }
    if (patch.sam) nextSettings.sam = { ...nextSettings.sam, ...patch.sam }
    if (patch.postprocess) nextSettings.postprocess = { ...nextSettings.postprocess, ...patch.postprocess }
    if (patch.quality) nextSettings.quality = { ...nextSettings.quality, ...patch.quality }
    if (patch.evaluation) nextSettings.evaluation = { ...nextSettings.evaluation, ...patch.evaluation }
    nextSettings._meta = {
      ...nextSettings._meta,
      activeSystemProfile: state.runtime.activeProfile,
      resolvedRuntimeProfile: nextSettings.modelProfile === 'auto' ? state.runtime.activeProfile : nextSettings.modelProfile,
    }
    state.systemSettings = nextSettings
    state.runtime = buildRuntimeSummary(state.profiles, state.systemSettings)
    state.runtime.modelName = nextSettings.llm.baseModel
    return {
      settings: cloneSystemSettings(state.systemSettings),
      change: buildSettingsChange(patch),
    }
  },
  async activateSystemProfile(profileName) {
    await delay()
    const profile = state.profiles.find((item) => item.name === profileName)
    if (!profile) {
      throw new Error(`Unknown profile: ${profileName}`)
    }
    state.systemSettings.modelProfile = profile.name
    state.systemSettings.llm.baseModel = profile.modelName
    state.systemSettings.sam.device = profile.name === 'dev_low_resource' ? 'cpu' : 'cuda'
    state.systemSettings._meta.activeSystemProfile = profile.name
    state.systemSettings._meta.resolvedRuntimeProfile = profile.name
    state.runtime = buildRuntimeSummary(state.profiles, state.systemSettings)
    return buildSystemConfig(state.profiles, state.runtime, state.systemSettings)
  },
  async getDiagnostics() {
    await delay()
    return {
      ...state.diagnostics,
      services: state.diagnostics.services.map((item) => ({ ...item })),
      selftest: state.diagnostics.selftest.map((item) => ({ ...item })),
      caches: state.diagnostics.caches.map((item) => ({ ...item })),
      commands: [...state.diagnostics.commands],
    }
  },
  async runSelftest() {
    await delay(240)
    state.diagnostics.lastRunAt = nowText()
    state.diagnostics.selftest = [
      { name: 'api_health', status: 'PASS' },
      { name: 'redis_connectivity', status: 'PASS' },
      { name: 'vllm_minimal_inference', status: 'PASS' },
      { name: 'task_chain_validation', status: 'PASS' },
    ]
    state.diagnostics.services = state.diagnostics.services.map((service) =>
      service.name === 'vllm' ? { ...service, status: 'healthy' } : service,
    )
    return {
      ...state.diagnostics,
      services: state.diagnostics.services.map((item) => ({ ...item })),
      selftest: state.diagnostics.selftest.map((item) => ({ ...item })),
      caches: state.diagnostics.caches.map((item) => ({ ...item })),
      commands: [...state.diagnostics.commands],
    }
  },
}
