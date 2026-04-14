import type {
  AnnotationSource,
  ImageStatus,
  ProjectTabKey,
  SelftestCheck,
  ServiceHealth,
  TaskFamily,
  TaskSnapshot,
  TaskStatus,
  TaskTransport,
} from '../backend/types'

const taskStatusLabels: Record<TaskStatus, string> = {
  IDLE: '空闲',
  QUEUED: '排队中',
  RUNNING: '运行中',
  SUCCESS: '完成',
  FAILED: '失败',
}

const taskTransportLabels: Record<TaskTransport, string> = {
  idle: '未连接',
  websocket: 'WebSocket',
  polling: '轮询',
}

const taskKindLabels: Record<TaskSnapshot['kind'], string> = {
  project_annotate: '批量标注',
  finetune: '微调',
  evaluation: '评估',
}

const sourceLabels: Record<AnnotationSource, string> = {
  auto: '自动',
  manual: '手工',
  corrected: '修正',
}

const reviewStateLabels: Record<'review' | 'ok' | 'unscored', string> = {
  review: '待复核',
  ok: '通过',
  unscored: '未评分',
}

const serviceHealthLabels: Record<ServiceHealth['status'], string> = {
  healthy: '正常',
  degraded: '降级',
  failed: '失败',
}

const selftestStatusLabels: Record<SelftestCheck['status'], string> = {
  PASS: '通过',
  FAIL: '失败',
  TIMEOUT: '超时',
  SKIPPED: '跳过',
}

const imageStatusLabels: Record<ImageStatus, string> = {
  pending: '待处理',
  annotating: '标注中',
  done: '完成',
  error: '失败',
}

const taskFamilyLabels: Record<TaskFamily, string> = {
  bbox: '检测框',
  instance_mask: '实例分割',
}

const tabLabels: Record<ProjectTabKey, string> = {
  overview: '概览',
  data: '数据',
  annotate: '标注',
  train: '微调',
  evaluate: '评估',
  settings: '设置',
}

const taskTypeLabels: Record<'detection' | 'segmentation', string> = {
  detection: '检测',
  segmentation: '分割',
}

const splitLabels: Record<'train' | 'val' | 'test', string> = {
  train: '训练集',
  val: '验证集',
  test: '测试集',
}

const sortModeLabels: Record<'review_queue' | 'latest_quality' | 'newest', string> = {
  review_queue: '待复核优先',
  latest_quality: '质量排序',
  newest: '最新导入',
}

const annotationBackendLabels: Record<string, string> = {
  stub: '模拟',
  'openai-compatible': 'OpenAI 兼容',
  openai_compatible: 'OpenAI 兼容',
}

const serviceNameLabels: Record<string, string> = {
  frontend: '前端',
  api: '接口服务',
  worker: '任务进程',
  vllm: 'VLLM',
  redis: 'Redis',
}

const selftestNameLabels: Record<string, string> = {
  api_health: '接口健康',
  redis_connectivity: 'Redis 连接',
  vllm_minimal_inference: 'VLLM 最小推理',
  task_chain_validation: '任务链校验',
}

const cacheStatusLabels: Record<string, string> = {
  ready: '就绪',
}

export function taskStatusText(status: TaskStatus | string): string {
  return taskStatusLabels[status as TaskStatus] ?? String(status)
}

export function taskTransportText(transport: TaskTransport | string): string {
  return taskTransportLabels[transport as TaskTransport] ?? String(transport)
}

export function taskKindText(kind: TaskSnapshot['kind'] | string): string {
  return taskKindLabels[kind as TaskSnapshot['kind']] ?? String(kind)
}

export function sourceText(source: AnnotationSource | string): string {
  return sourceLabels[source as AnnotationSource] ?? String(source)
}

export function reviewStateText(state: 'review' | 'ok' | 'unscored' | string): string {
  return reviewStateLabels[state as 'review' | 'ok' | 'unscored'] ?? String(state)
}

export function serviceHealthText(status: ServiceHealth['status'] | string): string {
  return serviceHealthLabels[status as ServiceHealth['status']] ?? String(status)
}

export function selftestStatusText(status: SelftestCheck['status'] | string): string {
  return selftestStatusLabels[status as SelftestCheck['status']] ?? String(status)
}

export function imageStatusText(status: ImageStatus | string): string {
  return imageStatusLabels[status as ImageStatus] ?? String(status)
}

export function taskFamilyText(taskFamily: TaskFamily | string): string {
  return taskFamilyLabels[taskFamily as TaskFamily] ?? String(taskFamily)
}

export function projectTabText(tab: ProjectTabKey): string {
  return tabLabels[tab]
}

export function splitText(split: 'train' | 'val' | 'test' | string): string {
  return splitLabels[split as 'train' | 'val' | 'test'] ?? String(split)
}

export function sortModeText(mode: 'review_queue' | 'latest_quality' | 'newest' | string): string {
  return sortModeLabels[mode as 'review_queue' | 'latest_quality' | 'newest'] ?? String(mode)
}

export function annotationBackendText(value: string): string {
  return annotationBackendLabels[value] ?? value
}

export function serviceNameText(name: string): string {
  return serviceNameLabels[name] ?? name
}

export function selftestNameText(name: string): string {
  return selftestNameLabels[name] ?? name
}

export function cacheStatusText(status: string): string {
  return cacheStatusLabels[status] ?? status
}

export function taskTypeText(taskType: 'detection' | 'segmentation' | string): string {
  return taskTypeLabels[taskType as 'detection' | 'segmentation'] ?? String(taskType)
}
