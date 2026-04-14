export type TaskType = 'detection' | 'segmentation'
export type TaskFamily = 'bbox' | 'instance_mask'
export type TaskTransport = 'idle' | 'websocket' | 'polling'
export type TaskStatus = 'IDLE' | 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'FAILED'
export type ImageStatus = 'pending' | 'annotating' | 'done' | 'error'
export type AnnotationSource = 'auto' | 'manual' | 'corrected'
export type InteractionMode = 'bbox' | 'point'

export type WorkflowDefinition = {
  key: string
  displayName: string
  description: string
  taskType: TaskType
  taskFamily: TaskFamily
  supportsAutoAnnotation: boolean
  supportsManualBBox: boolean
  supportsPointRefine: boolean
  capabilities: string[]
}

export type ProjectMetaPayload = {
  taskTypes: TaskType[]
  defaultWorkflows: Record<TaskType, string>
  workflows: WorkflowDefinition[]
}

export type TaskSnapshot = {
  id: string
  kind: 'project_annotate' | 'finetune' | 'evaluation'
  status: TaskStatus
  progress: number
  transport: TaskTransport
  message: string
  updatedAt: string
}

export type ProjectSummary = {
  id: number
  name: string
  taskType: TaskType
  workflowKey: string
  taskFamily: TaskFamily
  createdAt: string
  imageCount: number
  reviewCount: number
  activeModelTag: string
  lastTaskStatus: TaskStatus
  lastTaskUpdatedAt: string
}

export type ReviewQueueItem = {
  imageId: number
  filename: string
  qualityScore: number | null
  annotationCount: number
  fallbackUsed: boolean
}

export type ImageRecord = {
  id: number
  filename: string
  width: number
  height: number
  split: 'train' | 'val' | 'test'
  status: ImageStatus
  qualityScore: number | null
  thumbnailUrl: string
  reviewState: 'review' | 'ok' | 'unscored'
  annotationCount: number
}

export type RuntimeRoute = {
  provider: string
  modelTag: string
  modelName: string
}

export type AnnotationRecord = {
  id: number
  label: string
  source: AnnotationSource
  confidence: number | null
  confirmed: boolean
  runtime: RuntimeRoute
  bbox: [number, number, number, number] | null
  polygon: [number, number][]
  positivePoints: number
  negativePoints: number
}

export type ImageDetail = ImageRecord & {
  imageUrl: string
  annotations: AnnotationRecord[]
}

export type ProjectWorkspace = {
  summary: ProjectSummary
  labels: string[]
  activeModelTag: string
  runtimeProfile: string
  latestEvaluationDice: number | null
  latestFinetuneTag: string | null
  images: ImageRecord[]
  reviewQueue: ReviewQueueItem[]
  task: TaskSnapshot
  workflow: WorkflowDefinition
}

export type TrainMetricPoint = {
  epoch?: number
  epochTotal?: number
  step?: number
  loss?: number
  learningRate?: number
  raw?: string
}

export type TrainJob = {
  id: number
  status: TaskStatus
  modelTag: string
  startedAt: string
  datasetPath: string
  lossCurveLabel: string
  logExcerpt: string[]
  metrics: TrainMetricPoint[]
  active: boolean
}

export type EvaluationRun = {
  id: number
  status: TaskStatus
  split: 'val' | 'test'
  modelTag: string
  precision: number
  recall: number
  f1: number
  miouBBox: number
  miouMask: number
  dice: number
  avgTotalMs: number
  fallbackImages: number
  createdAt: string
}

export type FailureSample = {
  imageId: number
  filename: string
  fp: number
  fn: number
  f1: number
}

export type RuntimeSettings = {
  activeProfile: string
  annotationBackend: string
  modelName: string
  requestTimeoutSeconds: number
  maxRetries: number
  reloadRequiredPaths: string[]
  profiles: Array<{
    name: string
    description: string
    annotationBackend: string
    modelName: string
  }>
}

export type SystemProfile = {
  name: string
  description: string
  annotationBackend: string
  modelName: string
}

export type SettingsChange = {
  changedPaths: string[]
  hotReloadPaths: string[]
  reloadRequiredPaths: string[]
  otherPaths: string[]
  reloadRequired: boolean
  message: string
}

export type SystemSettingsMeta = {
  hotReloadPaths: string[]
  reloadRequiredPaths: string[]
  availableModelProfiles: string[]
  activeSystemProfile: string
  resolvedRuntimeProfile: string
  storagePath: string
  note: string
}

export type SystemSettingsPayload = {
  modelProfile: string
  llm: {
    baseModel: string
    autoOrder: string[]
    maxTokens: number
  }
  sam: {
    checkpoint: string
    device: 'cpu' | 'cuda'
    multimaskOutput: boolean
  }
  postprocess: {
    enableClose: boolean
    closeKernel: number
    enableDpSimplify: boolean
    epsilonRatio: number
    minAreaRatio: number
  }
  quality: {
    enable: boolean
    thresholdReview: number
    thresholdOk: number
    useLlmConfidence: boolean
    useSamScore: boolean
    enableConsistencyCheck: boolean
  }
  evaluation: {
    split: 'train' | 'val' | 'test'
    iouThreshold: number
    maxSamples: number | null
  }
  _meta: SystemSettingsMeta
}

export type SystemConfig = {
  activeProfile: string
  profiles: SystemProfile[]
  settings: SystemSettingsPayload
  envFiles: {
    backend: string
    frontend: string
  }
  runtime: {
    appProfile: string
    annotationBackend: string
    modelName: string
    llmRequestTimeoutSeconds: number
    llmMaxRetries: number
    llmMaxTokens: number
  }
  metadata: {
    hotReloadFields: string[]
    restartRequiredFields: string[]
    note: string
  }
}

export type ProjectSettingsMeta = {
  projectEditablePaths: string[]
  availableWorkflows: WorkflowDefinition[]
  activeSystemProfile: string
  resolvedProjectProfile: string
  note: string
}

export type ServiceHealth = {
  name: string
  status: 'healthy' | 'degraded' | 'failed'
}

export type SelftestCheck = {
  name: string
  status: 'PASS' | 'FAIL' | 'TIMEOUT' | 'SKIPPED'
}

export type DiagnosticsSnapshot = {
  lastRunAt: string
  services: ServiceHealth[]
  selftest: SelftestCheck[]
  caches: Array<{
    name: string
    status: string
  }>
  commands: string[]
}

export type ProjectSettingsPayload = {
  workflowKey: string
  taskFamily: TaskFamily
  workflow: WorkflowDefinition
  labels: string[]
  activeModelTag: string
  _meta: ProjectSettingsMeta
}

export type ProjectSettingsUpdateResponse = {
  settings: ProjectSettingsPayload
  change: SettingsChange
}

export type ProjectTabKey = 'overview' | 'data' | 'annotate' | 'train' | 'evaluate' | 'settings'

export interface BackendClient {
  getProjectMeta(): Promise<ProjectMetaPayload>
  listProjects(): Promise<ProjectSummary[]>
  createProject(input: { name: string; taskType: TaskType; workflowKey?: string }): Promise<{ id: number }>
  getProjectWorkspace(projectId: number): Promise<ProjectWorkspace>
  getProjectSettings(projectId: number): Promise<ProjectSettingsPayload>
  updateProjectSettings(projectId: number, patch: Partial<Pick<ProjectSettingsPayload, 'workflowKey' | 'labels'>>): Promise<ProjectSettingsUpdateResponse>
  startBatchAnnotate(projectId: number): Promise<TaskSnapshot>
  getAnnotationStudio(projectId: number, imageId?: number): Promise<{
    project: ProjectSummary
    workflow: WorkflowDefinition
    queue: ReviewQueueItem[]
    image: ImageDetail | null
  }>
  confirmAnnotation(projectId: number, imageId: number, annotationId: number): Promise<ImageDetail>
  deleteAnnotation(projectId: number, imageId: number, annotationId: number): Promise<ImageDetail>
  listTrainJobs(projectId: number): Promise<TrainJob[]>
  startTrain(projectId: number): Promise<TrainJob[]>
  listEvaluations(projectId: number): Promise<{ runs: EvaluationRun[]; failures: FailureSample[] }>
  startEvaluation(projectId: number): Promise<{ runs: EvaluationRun[]; failures: FailureSample[] }>
  getRuntimeSettings(): Promise<RuntimeSettings>
  activateProfile(profileName: string): Promise<RuntimeSettings>
  getSystemConfig(): Promise<SystemConfig>
  getSystemSettings(): Promise<SystemSettingsPayload>
  updateSystemSettings(patch: Partial<SystemSettingsPayload>): Promise<{ settings: SystemSettingsPayload; change: SettingsChange }>
  activateSystemProfile(profileName: string): Promise<SystemConfig>
  getDiagnostics(): Promise<DiagnosticsSnapshot>
  runSelftest(): Promise<DiagnosticsSnapshot>
}
