import type {
  AnnotationRecord,
  ApiErrorPayload,
  ApiResponse,
  EvaluationComparePayload,
  EvaluationReport,
  EvaluationRunRecord,
  FinetuneJobRecord,
  ImageRecord,
  ProjectListItem,
  ProjectMetaPayload,
  ProjectSettingsPayload,
  SystemConfigPayload,
  SystemSettingsPayload,
  TaskStatusPayload,
} from './types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000'

export { API_BASE_URL }

export class ApiError extends Error {
  code: number
  detail?: unknown[] | null

  constructor(payload: ApiErrorPayload) {
    super(payload.message)
    this.name = 'ApiError'
    this.code = payload.code
    this.detail = payload.data?.detail ?? null
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  })

  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    if (!response.ok) {
      throw new Error(`request failed: ${response.status}`)
    }
    return (await response.blob()) as T
  }

  const payload = (await response.json()) as ApiResponse<T> | ApiErrorPayload
  if (!response.ok) {
    throw new ApiError(payload as ApiErrorPayload)
  }
  return (payload as ApiResponse<T>).data
}

export const api = {
  listProjects: () => request<ProjectListItem[]>('/api/projects'),
  getProjectMeta: () => request<ProjectMetaPayload>('/api/projects/meta'),
  createProject: (payload: { name: string; task_type: 'detection' | 'segmentation'; workflow_key?: string }) =>
    request<{ id: number }>('/api/projects', { method: 'POST', body: JSON.stringify(payload) }),
  deleteProject: (projectId: number) => request<null>(`/api/projects/${projectId}`, { method: 'DELETE' }),
  getProjectSettings: (projectId: number) => request<ProjectSettingsPayload>(`/api/projects/${projectId}/settings`),
  patchProjectSettings: (projectId: number, payload: { labels?: string[]; workflow_key?: string }) =>
    request<{ settings: ProjectSettingsPayload; change: { message: string } }>(`/api/projects/${projectId}/settings`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  activateProjectModel: (projectId: number, model_tag: string) =>
    request<{ settings: ProjectSettingsPayload; activation: { message: string } }>(
      `/api/projects/${projectId}/models/activate`,
      {
        method: 'POST',
        body: JSON.stringify({ model_tag }),
      },
    ),
  listImages: (projectId: number) => request<ImageRecord[]>(`/api/projects/${projectId}/images`),
  patchImage: (imageId: number, split: 'train' | 'val' | 'test') =>
    request<null>(`/api/images/${imageId}`, {
      method: 'PATCH',
      body: JSON.stringify({ split }),
    }),
  deleteImage: (imageId: number) => request<null>(`/api/images/${imageId}`, { method: 'DELETE' }),
  uploadImages: (projectId: number, files: File[]) => {
    const form = new FormData()
    files.forEach((file) => form.append('files[]', file))
    return request<{ uploaded: number; image_ids: number[] }>(`/api/projects/${projectId}/images/upload`, {
      method: 'POST',
      body: form,
    })
  },
  exportDataset: (projectId: number, format: 'yolo' | 'coco') =>
    request<Blob>(`/api/projects/${projectId}/export?format=${format}`),
  importDataset: (projectId: number, format: 'yolo' | 'coco', file: File) => {
    const form = new FormData()
    form.append('format', format)
    form.append('file', file)
    return request<{ imported_count: number }>(`/api/projects/${projectId}/import`, {
      method: 'POST',
      body: form,
    })
  },
  listAnnotations: (imageId: number) => request<AnnotationRecord[]>(`/api/images/${imageId}/annotations`),
  confirmAnnotation: (annotationId: number) =>
    request<null>(`/api/annotations/${annotationId}/confirm`, { method: 'PATCH' }),
  deleteAnnotation: (annotationId: number) => request<null>(`/api/annotations/${annotationId}`, { method: 'DELETE' }),
  predictAnnotation: (
    imageId: number,
    payload: {
      annotation_id: number | null
      label?: string | null
      bbox?: [number, number, number, number] | null
      points?: Array<{ x: number; y: number; label: 0 | 1 }> | null
    },
  ) =>
    request<{ annotation_id: number; bbox?: [number, number, number, number] | null; polygon?: number[][] | null }>(
      `/api/images/${imageId}/predict`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  createAnnotation: (
    imageId: number,
    payload: { label: string; bbox: [number, number, number, number]; confidence?: number; source?: string },
  ) =>
    request<{ id: number }>(`/api/images/${imageId}/annotations`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  startAnnotationTask: (projectId: number, payload: { image_ids?: number[]; only_pending?: boolean }) =>
    request<{ task_id: string; total: number }>(`/api/projects/${projectId}/annotate`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getTaskStatus: (taskId: string) => request<TaskStatusPayload>(`/api/tasks/${taskId}/status`),
  getSystemConfig: () => request<SystemConfigPayload>('/api/system/config'),
  getSystemSettings: () => request<SystemSettingsPayload>('/api/system/settings'),
  patchSystemSettings: (payload: Partial<SystemSettingsPayload>) =>
    request<{ settings: SystemSettingsPayload; change: { message: string } }>('/api/system/settings', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  activateSystemProfile: (profile: string) =>
    request<{ message: string }>('/api/system/profiles/activate', {
      method: 'POST',
      body: JSON.stringify({ profile }),
    }),
  activateModelProfile: (profile: string) =>
    request<{ message: string }>('/api/system/model/activate', {
      method: 'POST',
      body: JSON.stringify({ profile }),
    }),
  listFinetuneJobs: (projectId: number) => request<FinetuneJobRecord[]>(`/api/projects/${projectId}/finetune-jobs`),
  startFinetune: (projectId: number) =>
    request<{ job_id: number; task_id: string }>('/api/finetune/start', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId }),
    }),
  activateFinetune: (jobId: number) => request<{ message: string }>(`/api/finetune/${jobId}/activate`, { method: 'POST' }),
  getFinetuneLog: (jobId: number) => request<{ log: string }>(`/api/finetune/${jobId}/log`),
  listEvaluations: (projectId: number) => request<EvaluationRunRecord[]>(`/api/projects/${projectId}/evaluations`),
  startEvaluation: (
    projectId: number,
    payload: { split?: string; image_ids?: number[]; model_tag?: string; iou_threshold?: number; max_samples?: number | null },
  ) =>
    request<{ run_id: number; task_id: string }>(`/api/projects/${projectId}/evaluate`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getEvaluationReport: (runId: number) => request<EvaluationReport>(`/api/evaluations/${runId}/report`),
  compareEvaluation: (runId: number, baseline_run_id?: number) =>
    request<EvaluationComparePayload>(
      `/api/evaluations/${runId}/compare${baseline_run_id ? `?baseline_run_id=${baseline_run_id}` : ''}`,
    ),
}
