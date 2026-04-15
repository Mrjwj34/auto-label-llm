# 后端真实能力差异与前端 API 清单

> 目标：给前端开发提供一份以**当前后端真实实现**为准的接口文档，同时明确 `docs/design_doc.md`、`docs/dev_plan.md` 与真实实现之间的关键差异。
>
> 审核基线：`backend/routers/*.py`、`backend/services/*.py`、`backend/models/*.py`、`tests/test_api_m*.py`、`tests/test_workflow_registry_m18.py`。
>
> 审核日期：2026-04-15。
>
> 说明：当前环境未安装 FastAPI 运行依赖，无法直接生成运行时 OpenAPI；本文内容以源码和测试断言为准。

## 1. 审核结论

- 当前后端的真实能力中心是：
  - 项目 + workflow 元信息
  - 图片上传/列表/文件访问
  - 标注创建、删除、确认、bbox 纠正、点纠正
  - 项目级/单图级自动标注异步任务
  - 数据集导入导出
  - 微调任务、日志、LoRA 激活
  - 评估运行、完整报告、run 对比
  - 系统级运行时设置、profile 切换
  - 任务轮询 + WebSocket 进度推送
- 当前后端**没有**项目工作台聚合接口，也没有诊断/selftest 的 HTTP API。前端不能继续按 mock 里的聚合 shape 假设接口存在。
- 当前后端已经完成 workflow 收敛，前端创建项目和展示项目时，必须同时理解：
  - `task_type`
  - `workflow_key`
  - `task_family`
- 当前后端已经把运行时配置拆成：
  - 项目级：`labels`、`workflow_key`
  - 系统级：`model_profile`、`llm.*`、`sam.*`、`postprocess.*`、`quality.*`、`evaluation.*`
- 项目模型切换不通过 `PATCH /api/projects/{project_id}/settings` 修改，而是通过：
  - `POST /api/projects/{project_id}/models/activate`
  - `POST /api/finetune/{job_id}/activate`

## 2. 与现有文档的关键差异

### 2.1 相比 `docs/design_doc.md`

| 主题 | 文档描述 | 真实后端 | 对前端的影响 |
|---|---|---|---|
| 任务基础设施 | 设计文档仍大量以 Celery 为主叙述 | 当前落地是 `RedisTaskManager + RedisTaskWorker`，任务状态存 Redis，WebSocket 已接入 | 前端只需要对接现有 REST/WS 契约，不要等待 Celery 才开始联调 |
| 项目设置可编辑范围 | 文档把 `model_profile` / `sam` / `postprocess` 等放在项目设置里更新 | `PATCH /api/projects/{project_id}/settings` 只允许 `labels`、`workflow_key` | 前端项目设置页不能直接提交系统运行时字段 |
| 系统设置接口 | 设计文档接口章节没有完整覆盖 | 实际已有 `/api/system/config`、`/api/system/settings`、`/api/system/profiles/activate`、`/api/system/model/activate` | 前端全局设置应以这些接口为准 |
| Workflow 元信息 | 设计文档接口章节仍以 `task_type` 为主 | 实际已有 `workflow_key`、`task_family`、`workflow`、`/api/projects/meta` | 项目创建页必须读取 `/api/projects/meta` |
| 项目模型激活 | 接口章节未完整体现项目级模型切换入口 | 实际已有 `POST /api/projects/{project_id}/models/activate` | 前端切换 base / LoRA / 直接模型名时要用此接口 |
| 任务状态返回体 | 文档仅给了 `status/progress` | 实际轮询接口还返回 `task_id`、`kind`、`queue`、`message`、`version` | 前端任务条可展示更细粒度文案 |
| WebSocket 行为 | 文档写“每秒推送” | 实际是“状态更新时推送，超时轮询补发”，直到终态 | 前端不要写死 1 秒节奏假设 |
| 微调返回体 | 文档示例偏简 | 实际有 `task_id`、`model_tag`、`is_active`、`config`、`metrics` | 微调页可以直接做状态卡、日志区、loss 曲线 |
| 评估接口 | 文档主要覆盖 start/status/list | 实际还有 `/report`、`/compare`，报告里包含逐图明细、失败样本、性能统计 | 评估页第一版就能做完整看板 |
| 二进制响应 | 文档没有特别强调 | `/api/images/{id}/file` 和 `/api/projects/{id}/export` 返回原始文件流，不走统一 JSON 包裹 | 前端下载逻辑要单独处理 |

### 2.2 相比 `docs/dev_plan.md`

| 主题 | 开发计划中的表述 | 真实后端现状 | 结论 |
|---|---|---|---|
| M3 任务骨架 | 历史描述里先是轻量内存 `TaskManager`，后续再上 Celery | 当前已经是 Redis 持久化任务状态 + 独立 worker + WebSocket | 前端应直接按 Redis 任务契约联调 |
| M10 设置分层 | 计划目标是把系统级运行时设置从项目设置中拆出去 | 已完成，代码和测试都按新分层运行 | 前端应严格遵守新分层 |
| M11 `active_model_tag` | 计划要求参与自动标注与评估 | 已完成，自动标注、评估、LoRA 激活都走真实路由解析 | 前端可以把模型切换作为真实功能而非展示字段 |
| M12 SAM3 | 历史里程碑标题仍保留 `SAM3` | 当前默认真实分割基线已经迁移到 `SAM2 / SAM2.1` | 前端和文档都不应再以 `SAM3` 作为默认假设 |
| M13 WebSocket | 计划要求首阶段落地 | 已完成，`WS /ws/tasks/{task_id}` 可用 | 前端任务订阅可优先走 WebSocket，轮询兜底 |
| M18 Workflow 重构 | 计划要求引入 workflow registry | 已完成后端落地，且已暴露到项目列表、项目设置、项目元信息接口 | 前端项目建模必须使用 workflow 元信息 |
| 诊断 / selftest | M19 是 OCI/启动层计划，不是当前后端 REST 能力 | 后端当前没有 `/api/diagnostics` 或 `/api/selftest` | 前端不要继续按 mock 假设这些 HTTP 接口存在 |

## 3. 前端必须遵守的全局约定

### 3.1 通用响应包裹

除文件下载接口外，后端统一返回：

```ts
type ApiResponse<T> = {
  code: number
  message: string
  data: T
}
```

业务错误统一返回：

```ts
type ApiError = {
  code: number
  message: string
  data: null | {
    detail?: unknown[]
  }
}
```

补充说明：

- `AppError` 会返回对应 HTTP 状态码，JSON 结构仍是 `{ code, message, data }`。
- FastAPI 请求校验错误被统一改写成 `HTTP 400`，不是默认的 `422`。
- 请求校验失败时，返回格式是：

```json
{
  "code": 400,
  "message": "invalid request",
  "data": {
    "detail": [...]
  }
}
```

### 3.2 命名与字段风格

- JSON 字段全部使用 `snake_case`。
- 当前后端没有面向前端的 camelCase 适配层。
- 前端若使用 TypeScript camelCase 类型，需要单独做映射，不要直接假设后端已经返回 camelCase。

### 3.3 时间字段

- 数据库模型字段如 `created_at`、`started_at`、`finished_at` 来自 SQLite/SQLAlchemy，序列化后通常是 ISO 风格字符串。
- 任务状态里的 `created_at` / `started_at` / `finished_at` 目前不经 `/api/tasks/{task_id}/status` 暴露给前端。
- 不同来源的时间字符串可能带或不带时区信息。前端应按“普通时间字符串”做容错解析，不要假设时区格式完全统一。

### 3.4 状态枚举

```ts
type TaskStatus = 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE'
type ImageStatus = 'pending' | 'annotating' | 'done' | 'error'
type JobStatus = 'pending' | 'running' | 'done' | 'failed'
type AnnotationSource = 'auto' | 'manual' | 'corrected'
type ProjectTaskType = 'detection' | 'segmentation'
type ImageSplit = 'train' | 'val' | 'test'
```

### 3.5 文件下载接口不走 JSON 包裹

以下接口返回原始文件流：

- `GET /api/images/{image_id}/file`
- `GET /api/projects/{project_id}/export?format=yolo|coco`

前端应按 `blob` / 下载流处理。

### 3.6 当前明确不存在的能力

- 没有项目工作台聚合接口，例如：
  - `GET /api/projects/{project_id}/workspace`
  - `GET /api/projects/{project_id}/overview`
- 没有标注工作台聚合接口，例如：
  - `GET /api/projects/{project_id}/annotation-studio`
- 没有诊断或自检 HTTP API，例如：
  - `GET /api/diagnostics`
  - `POST /api/selftest`
- 没有任务取消 / 重试 / 清理接口。
- 没有微调超参数自定义提交接口；`POST /api/finetune/start` 只接收 `project_id`。
- 没有项目列表聚合 KPI 字段，例如图片数、待复核数、最近任务状态、当前 active model。

## 4. 真实数据结构

### 4.1 Workflow

```ts
type WorkflowDefinition = {
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
```

### 4.2 项目列表项

```ts
type ProjectListItem = {
  id: number
  name: string
  task_type: 'detection' | 'segmentation'
  workflow_key: string
  task_family: string
  created_at: string
}
```

注意：

- 当前**没有** `image_count`、`review_count`、`active_model_tag`、`last_task_status` 之类聚合字段。

### 4.3 项目元信息

```ts
type ProjectMetaPayload = {
  task_types: Array<'detection' | 'segmentation'>
  default_workflows: {
    detection: string
    segmentation: string
  }
  workflows: WorkflowDefinition[]
}
```

### 4.4 项目设置

```ts
type ProjectSettingsPayload = {
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
```

重要说明：

- `GET /api/projects/{project_id}/settings` 返回的是“项目私有字段 + 系统运行时默认值”的**合并结果**。
- `PATCH /api/projects/{project_id}/settings` 真实可修改字段只有：
  - `labels`
  - `workflow_key`
- `active_model_tag` 虽然会在 GET 结果里返回，但不是通过此接口直接修改。

### 4.5 设置变更摘要

```ts
type SettingsChange = {
  changed_paths: string[]
  hot_reload_paths: string[]
  reload_required_paths: string[]
  other_paths: string[]
  reload_required: boolean
  message: string
}
```

### 4.6 项目模型路由与激活结果

```ts
type InferenceRoute = {
  requested_model_tag: string
  effective_model_tag: string
  request_model_name: string
  base_model_name: string
  resolved_project_profile: string
  route_kind: 'base' | 'lora' | 'direct'
  adapter_path: string | null
  finetune_job_id: number | null
}

type RuntimeSyncResult = {
  status: 'skipped' | 'synced'
  mode: string
  actions: Array<Record<string, unknown>>
  message: string
}

type ProjectModelActivationPayload = {
  settings: ProjectSettingsPayload
  activation: {
    active_model_tag: string
    route: InferenceRoute
    runtime_sync: RuntimeSyncResult
    message: string
  }
}
```

### 4.7 图片

```ts
type ImageRecord = {
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
```

注意：

- 当前图片接口不返回 `thumbnail_url`、`annotation_count`、`review_state`。
- 单图详情 `GET /api/images/{image_id}` 返回结构与列表项一致，没有额外聚合字段。

### 4.8 标注

```ts
type AnnotationInference = {
  requested_model_tag?: string
  effective_model_tag?: string
  request_model_name?: string
  base_model_name?: string
  resolved_project_profile?: string
  route_kind?: string
  adapter_path?: string | null
  finetune_job_id?: number | null
  provider?: string
  requested_backend?: string
  fallback_used?: boolean
  warning?: string | null
  annotation_count?: number
  llm_ms?: number | null
  total_ms?: number | null
  sam_calls?: number
  sam_ms?: number | null
  postprocess_ms?: number | null
  segmentation_ms?: number | null
}

type AnnotationRecord = {
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
```

重要说明：

- `inference` 主要出现在自动标注产出的 annotation 上。
- 手工创建或纠正产生的 annotation，`inference` 通常为 `null`。

### 4.9 任务状态

轮询接口：

```ts
type TaskStatusPayload = {
  task_id: string
  kind: string
  queue: string
  status: 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE'
  progress: number
  message: string | null
  version: number
}
```

WebSocket 消息：

```ts
type TaskStatusMessage = {
  task_id: string
  status: 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE'
  progress: number
  message: string | null
}
```

### 4.10 系统设置与系统配置

```ts
type SystemSettingsPayload = {
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

type SystemConfigPayload = {
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
  }
  metadata: {
    hot_reload_fields: string[]
    restart_required_fields: string[]
    note: string
  }
}
```

### 4.11 微调任务

```ts
type FinetuneMetricPoint = {
  epoch?: number
  epoch_total?: number
  step?: number
  loss?: number
  learning_rate?: number
  raw: string
}

type FinetuneJobRecord = {
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
```

补充说明：

- `model_tag` 固定是 `lora:{job_id}`。
- `metrics` 来自日志解析，不保证每个点都同时拥有 `epoch`、`step`、`loss`、`learning_rate`。
- `config` 是后端生成的训练快照，字段较多，常见字段包括：
  - `runner_backend`
  - `model_name_or_path`
  - `requested_base_model`
  - `serving_base_model`
  - `dataset`
  - `dataset_dir`
  - `dataset_info_path`
  - `train_config_path`
  - `output_dir`
  - `learning_rate`
  - `num_train_epochs`
  - `precision`
  - `task_id`
  - `runner_command`

### 4.12 评估运行与评估报告

```ts
type EvaluationMetrics = {
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
  per_label: Record<string, {
    tp: number
    fp: number
    fn: number
    precision: number
    recall: number
    f1: number
    miou_bbox: number
    miou_mask: number | null
    dice: number | null
  }>
}

type EvaluationRunRecord = {
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
```

评估报告：

```ts
type EvaluationReport = {
  run_id: number
  project_id: number
  split: string
  model_tag: string
  generated_at: string
  inference: AnnotationInference | Record<string, unknown>
  metrics: EvaluationMetrics
  performance: {
    images_profiled: number
    generated_annotations: number
    fallback_images: number
    providers: Record<string, number>
    route_kinds: Record<string, number>
    total_elapsed_ms: number | null
    avg_total_ms: number | null
    p95_total_ms: number | null
    max_total_ms: number | null
    avg_llm_ms: number | null
    avg_sam_ms: number | null
    avg_postprocess_ms: number | null
    avg_segmentation_ms: number | null
  }
  summary: {
    perfect_images: number
    images_with_failures: number
    failure_samples: Array<{
      image_id: number
      filename: string
      split: string
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
      unmatched_prediction_labels: string[]
      unmatched_ground_truth_labels: string[]
      inference_total_ms: number | null
    }>
  }
  images: Array<{
    image_id: number
    filename: string
    split: string
    width: number | null
    height: number | null
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
    mask_pairs: number
    matches: Array<{
      prediction_index: number
      ground_truth_index: number
      label: string
      iou: number
      mask_iou: number | null
      dice: number | null
    }>
    labels_seen: string[]
    unmatched_prediction_labels: string[]
    unmatched_ground_truth_labels: string[]
    inference: Record<string, unknown>
  }>
}
```

评估对比：

```ts
type EvaluationComparePayload = {
  current_run: EvaluationRunRecord
  baseline_run: EvaluationRunRecord
  delta: {
    metrics: Record<string, {
      current: number | null
      baseline: number | null
      delta: number | null
    }>
    performance: Record<string, {
      current: number | null
      baseline: number | null
      delta: number | null
    }>
  }
  per_label: Record<string, Record<string, {
    current: number | null
    baseline: number | null
    delta: number | null
  }>>
  current_failure_samples: EvaluationReport['summary']['failure_samples']
  baseline_failure_samples: EvaluationReport['summary']['failure_samples']
  top_regressions: Array<Record<string, unknown>>
  top_improvements: Array<Record<string, unknown>>
}
```

## 5. API 清单

### 5.1 健康检查

#### `GET /healthz`

- 用途：服务存活检查。
- 返回：`ApiResponse<{ status: 'ok' }>`

#### `GET /api/health`

- 用途：API 健康检查。
- 返回：`ApiResponse<{ status: 'ok' }>`

### 5.2 项目

#### `GET /api/projects`

- 用途：项目列表。
- 返回：`ApiResponse<ProjectListItem[]>`

#### `GET /api/projects/meta`

- 用途：项目创建表单元信息。
- 返回：`ApiResponse<ProjectMetaPayload>`

#### `POST /api/projects`

- 用途：创建项目。
- 请求体：

```json
{
  "name": "demo",
  "task_type": "detection",
  "workflow_key": "generic_detection"
}
```

- 说明：
  - `name` 必填，长度 `1..100`
  - `task_type` 必填，只能是 `detection` 或 `segmentation`
  - `workflow_key` 可选，但如果传了，必须和 `task_type` 兼容
- 返回：`ApiResponse<{ id: number }>`

#### `DELETE /api/projects/{project_id}`

- 用途：删除项目和项目目录。
- 返回：`ApiResponse<null>`

### 5.3 项目设置

#### `GET /api/projects/{project_id}/settings`

- 用途：读取项目设置与合并后的运行时快照。
- 返回：`ApiResponse<ProjectSettingsPayload>`

#### `PATCH /api/projects/{project_id}/settings`

- 用途：更新项目设置。
- 允许字段：
  - `labels`
  - `workflow_key`
- 不允许字段：
  - `model_profile`
  - `active_model_tag`
  - `llm`
  - `sam`
  - `postprocess`
  - `quality`
  - `evaluation`
- 返回：

```ts
ApiResponse<{
  settings: ProjectSettingsPayload
  change: SettingsChange
}>
```

- 补充说明：
  - 如果把系统级字段误传到这个接口，后端会直接返回 `400`，并提示改用 `/api/system/settings`。

#### `POST /api/projects/{project_id}/models/activate`

- 用途：激活项目当前使用的模型标签。
- 请求体：

```json
{
  "model_tag": "base"
}
```

- `model_tag` 真实支持的几类值：
  - `base`
  - `lora:{job_id}`
  - 直接模型名，例如某个直接路由到基础模型名的值
- 返回：`ApiResponse<ProjectModelActivationPayload>`

### 5.4 图片

#### `POST /api/projects/{project_id}/images/upload`

- 用途：上传图片。
- 表单字段：
  - `files`
  - 或 `files[]`
- 返回：

```ts
ApiResponse<{
  uploaded: number
  image_ids: number[]
}>
```

- 错误情况：
  - 项目不存在：`404`
  - 未上传文件：`400`
  - 非合法图片：`400`

#### `GET /api/projects/{project_id}/images`

- 用途：读取项目图片列表。
- 返回：`ApiResponse<ImageRecord[]>`

#### `GET /api/images/{image_id}`

- 用途：读取单图信息。
- 返回：`ApiResponse<ImageRecord>`

#### `PATCH /api/images/{image_id}`

- 用途：修改图片数据集划分。
- 当前只支持：

```json
{
  "split": "train"
}
```

- 返回：`ApiResponse<null>`

#### `DELETE /api/images/{image_id}`

- 用途：删除图片。
- 返回：`ApiResponse<null>`

#### `GET /api/images/{image_id}/file`

- 用途：读取原图文件。
- 返回：二进制文件流。

### 5.5 标注

#### `GET /api/images/{image_id}/annotations`

- 用途：读取图片标注列表。
- 返回：`ApiResponse<AnnotationRecord[]>`

#### `POST /api/images/{image_id}/annotations`

- 用途：手工新增标注。
- 请求体：

```json
{
  "label": "crack",
  "bbox": [0.1, 0.2, 0.5, 0.6],
  "confidence": 0.9,
  "source": "manual"
}
```

- 规则：
  - `label` 必填
  - `bbox` 必填，长度必须为 4，值必须在 `0..1`
  - 服务端会自动规范化 bbox 顺序，保证 `xmin <= xmax`、`ymin <= ymax`
  - 如果项目设置了 `labels`，则 `label` 必须属于该列表
  - 对于具备 `sam_refine` 能力的 workflow，后端会在创建时自动生成 `polygon` / `mask`
- 返回：

```ts
ApiResponse<{
  id: number
}>
```

#### `POST /api/images/{image_id}/predict`

- 用途：基于 bbox 或点做纠正预测。
- 真实规则：
  - `bbox` 和 `points` 必须二选一
  - `points` 模式必须传 `annotation_id`
  - `points[*].x` / `points[*].y` 必须在 `0..1`
  - `points[*].label` 只能是 `0` 或 `1`
  - `bbox + annotation_id = null` 表示创建新纠正标注
  - `bbox + annotation_id != null` 表示更新已有标注
  - `points` 模式只允许分割项目
  - 如果项目配置了 `labels`，则 `label` 仍需属于该列表
- 请求体一：bbox 创建或重算

```json
{
  "annotation_id": null,
  "label": "crack",
  "bbox": [0.15, 0.2, 0.55, 0.75]
}
```

- 请求体二：点纠正

```json
{
  "annotation_id": 123,
  "points": [
    { "x": 0.75, "y": 0.75, "label": 1 },
    { "x": 0.22, "y": 0.28, "label": 0 }
  ]
}
```

- 返回：

```ts
ApiResponse<{
  annotation_id: number
  bbox: [number, number, number, number] | null
  polygon: Array<[number, number]> | null
  mask_path: string | null
}>
```

#### `PATCH /api/annotations/{annotation_id}/confirm`

- 用途：确认标注。
- 返回：`ApiResponse<null>`

#### `DELETE /api/annotations/{annotation_id}`

- 用途：删除标注。
- 返回：`ApiResponse<null>`

### 5.6 自动标注与任务

#### `POST /api/projects/{project_id}/annotate`

- 用途：项目级批量自动标注。
- 请求体：

```json
{
  "image_ids": [1, 2, 3],
  "only_pending": true
}
```

- 规则：
  - `image_ids` 可选
  - 未传 `image_ids` 时，后端会按 `only_pending` 决定是否仅取 `status = pending` 的图片
  - 项目必须先配置至少一个 label
- 返回：

```ts
ApiResponse<{
  task_id: string
  total: number
}>
```

#### `POST /api/images/{image_id}/annotate`

- 用途：单图自动标注。
- 约束：
  - 图片所属项目必须已配置至少一个 label
- 返回：

```ts
ApiResponse<{
  task_id: string
}>
```

#### `GET /api/tasks/{task_id}/status`

- 用途：轮询任务状态。
- 返回：`ApiResponse<TaskStatusPayload>`

#### `WS /ws/tasks/{task_id}`

- 用途：实时订阅任务状态。
- 服务端消息：`TaskStatusMessage`
- 特殊行为：
  - 任务不存在时，服务端直接关闭连接，close code 为 `4404`
  - 到达终态 `SUCCESS` 或 `FAILURE` 后停止推送

### 5.7 数据集导入导出

#### `GET /api/projects/{project_id}/export?format=yolo|coco`

- 用途：导出确认标注数据集。
- 请求参数：
  - `format=yolo`
  - 或 `format=coco`
- 返回：zip 文件流。
- 约束：
  - 只导出 `is_confirmed = true` 的标注
  - 没有可导出的确认标注时返回 `400`

#### `POST /api/projects/{project_id}/import`

- 用途：导入数据集。
- 表单字段：
  - `format`
  - `file`
- 返回：

```ts
ApiResponse<{
  imported_count: number
  annotation_count: number
  labels: string[]
}>
```

- 真实行为：
  - 导入后会把项目 `labels` 更新为导入数据集推导出的标签列表
  - 导入进来的 annotation 会标记为：
    - `source = manual`
    - `is_confirmed = true`

### 5.8 微调

#### `POST /api/finetune/start`

- 用途：启动微调任务。
- 请求体：

```json
{
  "project_id": 12
}
```

- 返回：

```ts
ApiResponse<{
  job_id: number
  task_id: string
}>
```

- 真实限制：
  - 当前是**全局只允许一个** `pending/running` 微调任务，不是“每个项目一个”
  - 如果已有微调任务在运行，会返回 `409`
  - 即使项目没有可用于训练的确认 `train` 标注，这个接口也可能先返回 `200` 创建任务，然后任务在异步执行阶段变成 `failed`

#### `GET /api/projects/{project_id}/finetune-jobs`

- 用途：项目微调任务列表。
- 返回：`ApiResponse<FinetuneJobRecord[]>`

#### `GET /api/finetune/{job_id}/status`

- 用途：单个微调任务详情。
- 返回：`ApiResponse<FinetuneJobRecord>`

#### `GET /api/finetune/{job_id}/log`

- 用途：读取微调原始日志。
- 返回：

```ts
ApiResponse<{
  log: string
}>
```

#### `POST /api/finetune/{job_id}/activate`

- 用途：激活某个已完成的 LoRA。
- 返回：

```ts
ApiResponse<{
  active_model_tag: string
  route: InferenceRoute
  runtime_sync: RuntimeSyncResult
  message: string
}>
```

- 说明：
  - 这不是返回 `null`
  - 它内部会复用项目模型激活逻辑
  - 激活成功后，项目 `active_model_tag` 会切到对应 `lora:{job_id}`

### 5.9 评估

#### `POST /api/projects/{project_id}/evaluate`

- 用途：启动评估任务。
- 请求体支持字段：

```json
{
  "split": "val",
  "image_ids": [1, 2],
  "model_tag": "base",
  "iou_threshold": 0.5,
  "max_samples": 100
}
```

- 规则：
  - `split` 和 `image_ids` 不能同时传
  - `split` 只允许 `train | val | test`
  - 参与评估的 ground truth 必须是：
    - `is_confirmed = true`
    - `bbox != null`
  - 若未传 `model_tag`，会走当前项目的 `active_model_tag`
- 返回：

```ts
ApiResponse<{
  run_id: number
  task_id: string
}>
```

#### `GET /api/projects/{project_id}/evaluations`

- 用途：评估运行列表。
- 返回：`ApiResponse<EvaluationRunRecord[]>`

#### `GET /api/evaluations/{run_id}`

- 用途：单个评估运行详情。
- 返回：`ApiResponse<EvaluationRunRecord>`

#### `GET /api/evaluations/{run_id}/report`

- 用途：读取完整评估报告。
- 返回：`ApiResponse<EvaluationReport>`

#### `GET /api/evaluations/{run_id}/compare`

- 用途：读取当前 run 与基线 run 的对比结果。
- 查询参数：
  - `baseline_run_id` 可选
- 若未传 `baseline_run_id`：
  - 后端会自动选择同项目下最近一个已完成且不等于当前 run 的评估结果作为 baseline
- 额外约束：
  - 当前 run 必须已完成
  - baseline run 也必须已完成
- 返回：`ApiResponse<EvaluationComparePayload>`

### 5.10 系统设置与 profile

#### `GET /api/system/config`

- 用途：系统配置总览。
- 返回：`ApiResponse<SystemConfigPayload>`

#### `GET /api/system/settings`

- 用途：系统运行时设置。
- 返回：`ApiResponse<SystemSettingsPayload>`

#### `PATCH /api/system/settings`

- 用途：更新系统运行时设置。
- 允许根字段：
  - `model_profile`
  - `llm`
  - `sam`
  - `postprocess`
  - `quality`
  - `evaluation`
- 返回：

```ts
ApiResponse<{
  settings: SystemSettingsPayload
  change: SettingsChange
}>
```

#### `POST /api/system/profiles/activate`

- 用途：切换系统 profile。
- 请求体：

```json
{
  "profile": "dev_low_resource"
}
```

- 返回：

```ts
ApiResponse<{
  active_profile: string
  backend_env_path: string
  frontend_env_path: string
  backend_hot_reloaded_fields: string[]
  restart_required_targets: string[]
  runtime: {
    app_profile: string
    annotation_backend: string
    vllm_base_url: string
    vllm_model_name: string
    llm_request_timeout_seconds: number
    llm_max_retries: number
    llm_max_tokens: number
  }
  message: string
}>
```

#### `POST /api/system/model/activate`

- 用途：切换基础模型 profile。
- 请求体与 `/api/system/profiles/activate` 相同。
- 返回结构相同，但 `message` 语义更偏“基础模型切换”。

## 6. 前端页面与真实接口的建议对应关系

### 6.1 项目列表页

- 基础列表：`GET /api/projects`
- 创建项目前置数据：`GET /api/projects/meta`
- 如果首页要展示聚合 KPI，当前只能：
  - 前端自己二次请求拼装
  - 或后端后续补聚合接口

### 6.2 项目设置页

- 项目私有配置：
  - `GET /api/projects/{project_id}/settings`
  - `PATCH /api/projects/{project_id}/settings`
- 系统运行时配置：
  - `GET /api/system/config`
  - `GET /api/system/settings`
  - `PATCH /api/system/settings`
  - `POST /api/system/profiles/activate`
  - `POST /api/system/model/activate`
- 项目当前模型切换：
  - `POST /api/projects/{project_id}/models/activate`

### 6.3 数据页

- 图片上传：`POST /api/projects/{project_id}/images/upload`
- 图片列表：`GET /api/projects/{project_id}/images`
- 单图原图：`GET /api/images/{image_id}/file`
- 数据集导入/导出：
  - `POST /api/projects/{project_id}/import`
  - `GET /api/projects/{project_id}/export`

### 6.4 标注页

- 图像基础信息：
  - `GET /api/images/{image_id}`
  - `GET /api/images/{image_id}/file`
- 标注列表：
  - `GET /api/images/{image_id}/annotations`
- 手工增删改：
  - `POST /api/images/{image_id}/annotations`
  - `POST /api/images/{image_id}/predict`
  - `PATCH /api/annotations/{annotation_id}/confirm`
  - `DELETE /api/annotations/{annotation_id}`
- 自动标注：
  - `POST /api/images/{image_id}/annotate`
  - `POST /api/projects/{project_id}/annotate`
- 进度：
  - `WS /ws/tasks/{task_id}`
  - `GET /api/tasks/{task_id}/status`

### 6.5 微调页

- 列表：`GET /api/projects/{project_id}/finetune-jobs`
- 启动：`POST /api/finetune/start`
- 详情：`GET /api/finetune/{job_id}/status`
- 日志：`GET /api/finetune/{job_id}/log`
- 激活：`POST /api/finetune/{job_id}/activate`

### 6.6 评估页

- 列表：`GET /api/projects/{project_id}/evaluations`
- 启动：`POST /api/projects/{project_id}/evaluate`
- 详情：`GET /api/evaluations/{run_id}`
- 完整报告：`GET /api/evaluations/{run_id}/report`
- 对比：`GET /api/evaluations/{run_id}/compare`

## 7. 前端当前不该继续保留的假设

- 不要再假设存在“项目工作台聚合接口”。
- 不要再假设项目设置接口可以直接更新 `model_profile` 或 `sam.*`。
- 不要再假设 `POST /api/finetune/start` 支持提交训练超参数。
- 不要再假设微调或评估有单独“前端专用图表接口”。
- 不要再假设项目列表自带聚合 KPI。
- 不要再假设存在诊断/selftest HTTP API。
- 不要再假设后端返回 camelCase。

## 8. 建议的前端落地顺序

1. 先封一层真实后端 adapter，所有 mock shape 统一在 adapter 层转换或废弃。
2. 先把“系统设置”和“项目设置”分层建模，再开始搭页面。
3. 标注页优先按单图真实接口串起来，不要先造聚合工作台接口依赖。
4. 微调页直接消费 `metrics` 和 `/log`，不用等后端新增图表接口。
5. 评估页直接消费 `/report` 和 `/compare`，不要只停留在 run 列表。
