export type ApiResponse<T> = {
  code: number
  message: string
  data: T
}

export type ApiErrorPayload = {
  code: number
  message: string
  data: { detail?: unknown[] } | null
}

export type WorkflowDefinition = {
  key: string
  display_name: string
  description: string
  task_type: 'detection' | 'segmentation'
  task_family: 'bbox' | 'instance_mask' | 'semantic_mask' | 'polyline' | 'change_mask'
  supports_auto_annotation: boolean
  supports_manual_bbox: boolean
  supports_point_refine: boolean
  capabilities: string[]
}

export type ProjectListItem = {
  id: number
  name: string
  task_type: 'detection' | 'segmentation'
  workflow_key: string
  task_family: string
  created_at: string
}

export type ProjectMetaPayload = {
  task_types: Array<'detection' | 'segmentation'>
  default_workflows: Record<'detection' | 'segmentation', string>
  workflows: WorkflowDefinition[]
}

export type ProjectSettingsPayload = {
  labels: string[]
  model_profile: string
  active_model_tag: string
  workflow_key: string
  task_family: string
  workflow: WorkflowDefinition
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
    split: 'train' | 'val' | 'test'
    iou_threshold: number
    max_samples: number | null
  }
  _meta: {
    project_editable_paths: string[]
    available_workflows: WorkflowDefinition[]
    note: string
    active_system_profile: string
    resolved_project_profile: string
  }
}

export type ImageRecord = {
  id: number
  project_id: number
  filename: string
  width: number | null
  height: number | null
  split: 'train' | 'val' | 'test'
  status: 'pending' | 'annotating' | 'done' | 'error'
  quality_score: number | null
  file_url: string
}

export type AnnotationInference = {
  provider?: string
  route_kind?: string
  effective_model_tag?: string
  fallback_used?: boolean
  llm_ms?: number | null
  total_ms?: number | null
  sam_ms?: number | null
  postprocess_ms?: number | null
  warning?: string | null
}

export type AnnotationRecord = {
  id: number
  image_id: number
  label: string
  bbox: [number, number, number, number] | null
  polygon: Array<[number, number]> | null
  mask_path: string | null
  confidence: number | null
  quality_score: number | null
  source: 'auto' | 'manual' | 'corrected'
  is_confirmed: boolean
  created_at: string
  inference: AnnotationInference | null
}

export type TaskStatusPayload = {
  task_id: string
  kind: string
  queue: string
  status: 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE'
  progress: number
  message: string | null
  version: number
}

export type TaskStatusMessage = Pick<TaskStatusPayload, 'task_id' | 'status' | 'progress' | 'message'>

export type SystemSettingsPayload = {
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
    split: 'train' | 'val' | 'test'
    iou_threshold: number
    max_samples: number | null
  }
  _meta: {
    hot_reload_paths: string[]
    reload_required_paths: string[]
    available_model_profiles: string[]
    note: string
    active_system_profile: string
    resolved_runtime_profile: string
    storage_path: string
  }
}

export type SystemConfigPayload = {
  active_profile: string
  profiles: Array<{
    name: string
    description: string
    backend: Record<string, unknown>
    frontend: Record<string, unknown>
    project_defaults: Record<string, unknown>
  }>
  settings: SystemSettingsPayload
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
    finetune: {
      requested_backend: string
      effective_backend: string
      requires_real_backend: boolean
      llamafactory_cli: string
      llamafactory_cli_available: boolean
      ready: boolean
      note: string
    }
  }
  metadata: {
    hot_reload_fields: string[]
    restart_required_fields: string[]
    note: string
  }
}

export type FinetuneMetricPoint = {
  epoch?: number
  epoch_total?: number
  step?: number
  loss?: number
  learning_rate?: number
  raw: string
}

export type FinetuneJobRecord = {
  id: number
  project_id: number
  status: 'pending' | 'running' | 'done' | 'failed'
  dataset_path: string | null
  lora_path: string | null
  log_path: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  model_tag: string
  is_active: boolean | null
  task_id: string | null
  config: Record<string, unknown> | null
  metrics: FinetuneMetricPoint[]
}

export type EvaluationMetrics = {
  precision: number
  recall: number
  f1: number
  miou_bbox: number
  miou_mask: number | null
  dice: number | null
  iou_threshold: number
  images_evaluated: number
  perfect_images: number
  images_with_failures: number
  predictions: number
  ground_truth: number
  tp: number
  fp: number
  fn: number
  mask_pairs: number
  per_label: Record<string, Record<string, number | null>>
}

export type EvaluationRunRecord = {
  id: number
  project_id: number
  status: 'pending' | 'running' | 'done' | 'failed'
  split: string
  model_tag: string
  metrics: EvaluationMetrics | null
  report_path: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  task_id: string | null
  config: Record<string, unknown> | null
}

export type EvaluationReport = {
  run_id: number
  project_id: number
  split: string
  model_tag: string
  generated_at: string
  metrics: EvaluationMetrics
  performance: Record<string, number | null | Record<string, number>>
  summary: {
    perfect_images: number
    images_with_failures: number
    failure_samples: Array<{
      image_id: number
      filename: string
      split: string
      error_count: number
      precision: number
      recall: number
      f1: number
      miou_bbox: number
      miou_mask: number | null
      dice: number | null
      unmatched_prediction_labels: string[]
      unmatched_ground_truth_labels: string[]
      inference_total_ms: number | null
    }>
  }
  images: Array<{
    image_id: number
    filename: string
    split: string
    pred_count: number
    gt_count: number
    tp: number
    fp: number
    fn: number
    error_count: number
    precision: number
    recall: number
    f1: number
    miou_bbox: number
    miou_mask: number | null
    dice: number | null
    labels_seen: string[]
    unmatched_prediction_labels: string[]
    unmatched_ground_truth_labels: string[]
  }>
}

export type EvaluationComparePayload = {
  current_run: EvaluationRunRecord
  baseline_run: EvaluationRunRecord
  delta: {
    metrics: Record<string, { current: number | null; baseline: number | null; delta: number | null }>
    performance: Record<string, { current: number | null; baseline: number | null; delta: number | null }>
  }
  per_label: Record<string, Record<string, { current: number | null; baseline: number | null; delta: number | null }>>
  current_failure_samples: EvaluationReport['summary']['failure_samples']
  baseline_failure_samples: EvaluationReport['summary']['failure_samples']
  top_regressions: Array<Record<string, unknown>>
  top_improvements: Array<Record<string, unknown>>
}
