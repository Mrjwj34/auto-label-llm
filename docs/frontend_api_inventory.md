# 前端联调用 API 清单

> 用途：给 M20 前端重写提供**后端真实能力边界**，避免继续按 mock 想象接口。
>
> 来源：本清单按后端源码整理，当前以 `backend/routers/*.py`、`backend/services/*`、旧前端里已验证过的类型定义为准。

## 1. 基础约定

### 1.1 响应包裹格式

后端统一使用：

```json
{
  "code": 200,
  "message": "ok",
  "data": {}
}
```

- 成功和失败都使用这个结构。
- 业务错误由 `code/message/data` 返回。
- 前端不要假设接口直接返回裸对象。

### 1.2 任务状态

任务查询来自：

- `GET /api/tasks/{task_id}/status`
- `WS /ws/tasks/{task_id}`

WebSocket 推送字段只有：

- `task_id`
- `status`
- `progress`
- `message`

不要假设还有更多进度字段。

### 1.3 当前最重要的真实边界

- 项目设置接口只允许改 `labels`、`workflow_key`。
- 系统级运行时配置必须走 `/api/system/settings`。
- 系统级配置档切换必须走 `/api/system/profiles/activate` 或 `/api/system/model/activate`。
- 微调没有单独“loss 曲线图片”接口，但有 `metrics` 点列和原始日志。
- 评估有列表、报告、对比三层接口，足够做可视化。
- 真实后端目前**没有**“项目工作台聚合接口”；前端不能继续依赖 mock 里的聚合 shape。

## 2. 前端必须遵守的结构结论

### 2.1 设置分层

- 项目级设置：
  - `workflow_key`
  - `labels`
- 全局设置：
  - `model_profile`
  - `llm.*`
  - `sam.*`
  - `postprocess.*`
  - `quality.*`
  - `evaluation.*`

这意味着：

- 首页不该有单独的“运行”产品页。
- 项目内“设置”页应拆成：
  - 全局设置
  - 项目设置

### 2.2 微调与评估可视化

后端支持情况：

- 微调：
  - `GET /api/projects/{project_id}/finetune-jobs`
  - 返回 `metrics` 数组，可直接画 loss 曲线。
  - `GET /api/finetune/{job_id}/log`
  - 可展示原始日志。
- 评估：
  - `GET /api/projects/{project_id}/evaluations`
  - `GET /api/evaluations/{run_id}/report`
  - `GET /api/evaluations/{run_id}/compare`
  - 已有总指标、失败样本、逐图结果、性能统计、对比差值。

这意味着：

- 微调页可以做 loss 曲线、学习率点列、日志面板。
- 评估页可以做指标卡、失败样本表、基线对比、逐图回归列表。
- 不需要等待后端新增“可视化专用接口”才能做第一版。

### 2.3 当前新前端里不该继续保留的假设

- 不要继续假设存在 `/runtime` 这样的独立业务页。
- 不要继续假设创建项目只传 `workflow_key + labels` 就够了。
  - 真实后端 `POST /api/projects` 还要求 `task_type`。
- 不要继续假设存在“项目聚合工作台”接口。
  - 真实数据要从多个端点拼。

## 3. API 分组清单

## 3.1 健康检查

### `GET /healthz`

- 用途：服务存活检查。
- 返回：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "status": "ok"
  }
}
```

### `GET /api/health`

- 用途：API 健康检查。
- 返回同上。

## 3.2 项目

### `GET /api/projects`

- 用途：项目列表。
- 当前字段：
  - `id`
  - `name`
  - `task_type`
  - `workflow_key`
  - `task_family`
  - `created_at`

注意：

- 真实接口目前**不直接返回**图片数、待复核数、最近任务、active model。
- 这些如果首页要展示，需要额外请求或后端补接口。

### `GET /api/projects/meta`

- 用途：项目创建表单元信息。
- 返回：
  - `task_types`
  - `default_workflows`
  - `workflows`

前端创建项目时应优先依赖这个接口。

### `POST /api/projects`

- 用途：创建项目。
- 请求体：

```json
{
  "name": "demo",
  "task_type": "detection",
  "workflow_key": "generic_detection"
}
```

注意：

- `task_type` 是必填。
- `workflow_key` 可选，但如果传了必须和 `task_type` 兼容。

### `DELETE /api/projects/{project_id}`

- 用途：删除项目。

## 3.3 项目设置

### `GET /api/projects/{project_id}/settings`

- 用途：读取项目设置 + 合并后的运行时配置快照。
- 返回里包含：
  - `workflow_key`
  - `task_family`
  - `workflow`
  - `labels`
  - `active_model_tag`
  - `llm`
  - `sam`
  - `postprocess`
  - `quality`
  - `evaluation`
  - `_meta`

重点：

- 返回是“合并后的设置”，不是“仅项目私有字段”。
- `_meta.project_editable_paths` 才告诉前端哪些字段真的能改。

### `PATCH /api/projects/{project_id}/settings`

- 用途：更新项目设置。
- 允许字段：
  - `labels`
  - `workflow_key`

不允许字段：

- `model_profile`
- `llm`
- `sam`
- `postprocess`
- `quality`
- `evaluation`

这些会被后端拒绝，并提示去 `/api/system/settings`。

返回：

- `settings`
- `change`

其中 `change` 包含：

- `changed_paths`
- `hot_reload_paths`
- `reload_required_paths`
- `reload_required`
- `message`

## 3.4 系统设置 / 配置档

### `GET /api/system/config`

- 用途：读取系统配置总览。
- 返回：
  - `active_profile`
  - `profiles`
  - `settings`
  - `env_files`
  - `runtime`
  - `metadata`

这个接口适合“全局设置”页的顶部总览。

### `GET /api/system/settings`

- 用途：读取系统运行时设置。
- 核心字段：
  - `model_profile`
  - `llm`
  - `sam`
  - `postprocess`
  - `quality`
  - `evaluation`
  - `_meta`

`_meta` 里有：

- `hot_reload_paths`
- `reload_required_paths`
- `available_model_profiles`
- `active_system_profile`
- `resolved_runtime_profile`
- `storage_path`
- `note`

### `PATCH /api/system/settings`

- 用途：更新全局运行时设置。
- 允许字段：
  - `model_profile`
  - `llm`
  - `sam`
  - `postprocess`
  - `quality`
  - `evaluation`

返回：

- `settings`
- `change`

### `POST /api/system/profiles/activate`

- 用途：切换系统配置档。
- 请求体：

```json
{
  "profile": "dev_low_resource"
}
```

返回重点：

- `active_profile`
- `backend_env_path`
- `frontend_env_path`
- `backend_hot_reloaded_fields`
- `restart_required_targets`
- `runtime`
- `message`

这才是“启动项目时预设设置”的真实入口。

### `POST /api/system/model/activate`

- 用途：切换基础模型配置档。
- 请求体同上。
- 语义比 `/profiles/activate` 更偏“基础模型配置切换”。

## 3.5 图片 / 数据集

### `POST /api/projects/{project_id}/images/upload`

- 用途：上传图片。
- 表单字段：
  - `files`
  - 或 `files[]`

### `GET /api/projects/{project_id}/images`

- 用途：图片列表。
- 当前字段：
  - `id`
  - `project_id`
  - `filename`
  - `width`
  - `height`
  - `split`
  - `status`
  - `quality_score`
  - `file_url`

### `GET /api/images/{image_id}`

- 用途：读取单图信息。

### `PATCH /api/images/{image_id}`

- 用途：改数据划分。
- 当前仅支持：

```json
{
  "split": "train"
}
```

### `DELETE /api/images/{image_id}`

- 用途：删除图片。

### `GET /api/images/{image_id}/file`

- 用途：返回原图文件。

### `GET /api/projects/{project_id}/export?format=yolo|coco`

- 用途：导出数据集 zip。

### `POST /api/projects/{project_id}/import`

- 用途：导入数据集 zip。
- 表单字段：
  - `format`
  - `file`

## 3.6 自动标注 / 任务

### `POST /api/projects/{project_id}/annotate`

- 用途：项目级批量自动标注。
- 请求体：

```json
{
  "image_ids": [1, 2, 3],
  "only_pending": true
}
```

返回：

- `task_id`
- `total`

### `POST /api/images/{image_id}/annotate`

- 用途：单图自动标注。
- 返回：
  - `task_id`

### `GET /api/tasks/{task_id}/status`

- 用途：轮询任务状态。

### `WS /ws/tasks/{task_id}`

- 用途：实时订阅任务状态。

## 3.7 标注

### `GET /api/images/{image_id}/annotations`

- 用途：读取图片标注列表。
- 关键字段：
  - `id`
  - `image_id`
  - `label`
  - `bbox`
  - `polygon`
  - `mask_path`
  - `confidence`
  - `quality_score`
  - `source`
  - `is_confirmed`
  - `created_at`
  - `inference`

`inference` 是前端展示运行路由的关键来源。

### `POST /api/images/{image_id}/annotations`

- 用途：手工新增标注。
- 请求体：

```json
{
  "label": "建筑",
  "bbox": [0.1, 0.2, 0.6, 0.8],
  "confidence": 0.9,
  "source": "manual"
}
```

如果 workflow 带 `sam_refine`，后端会自动补 polygon/mask。

### `POST /api/images/{image_id}/predict`

- 用途：基于 bbox 或点修正预测。
- 规则：
  - `bbox` 和 `points` 二选一
  - 点修正必须带 `annotation_id`

两类用法：

1. 基于 bbox 创建或重算标注
2. 基于 points 做交互式分割修正

### `PATCH /api/annotations/{annotation_id}/confirm`

- 用途：确认标注。

### `DELETE /api/annotations/{annotation_id}`

- 用途：删除标注。

## 3.8 项目模型激活

### `POST /api/projects/{project_id}/models/activate`

- 用途：激活项目当前模型标签。
- 请求体：

```json
{
  "model_tag": "base"
}
```

返回：

- `settings`
- `activation`

## 3.9 微调

### `POST /api/finetune/start`

- 用途：启动微调任务。
- 请求体：

```json
{
  "project_id": 12
}
```

返回：

- `job_id`
- `task_id`

### `GET /api/projects/{project_id}/finetune-jobs`

- 用途：项目微调任务列表。
- 关键字段：
  - `id`
  - `status`
  - `dataset_path`
  - `lora_path`
  - `log_path`
  - `started_at`
  - `finished_at`
  - `created_at`
  - `model_tag`
  - `is_active`
  - `task_id`
  - `config`
  - `metrics`

`metrics` 是 `parse_finetune_metrics(log_text)` 解析出来的点列，前端可以直接画 loss 曲线。

### `GET /api/finetune/{job_id}/status`

- 用途：读取单个微调任务详情。
- 返回字段与列表项一致。

### `GET /api/finetune/{job_id}/log`

- 用途：读取微调原始日志。
- 返回：

```json
{
  "log": "..."
}
```

### `POST /api/finetune/{job_id}/activate`

- 用途：激活某个已完成的 LoRA。

## 3.10 评估

### `POST /api/projects/{project_id}/evaluate`

- 用途：启动评估。
- 请求体：

```json
{
  "split": "val",
  "image_ids": [1, 2],
  "model_tag": "base",
  "iou_threshold": 0.5,
  "max_samples": 100
}
```

### `GET /api/projects/{project_id}/evaluations`

- 用途：评估运行列表。
- 关键字段：
  - `id`
  - `status`
  - `split`
  - `model_tag`
  - `metrics`
  - `report_path`
  - `started_at`
  - `finished_at`
  - `created_at`
  - `task_id`
  - `config`

### `GET /api/evaluations/{run_id}`

- 用途：单个评估任务详情。

### `GET /api/evaluations/{run_id}/report`

- 用途：完整评估报告。
- 报告结构：
  - `run_id`
  - `project_id`
  - `split`
  - `model_tag`
  - `generated_at`
  - `inference`
  - `metrics`
  - `performance`
  - `summary`
  - `images`

其中：

- `metrics`：总指标 + per_label
- `performance`：总耗时、P95、LLM/SAM/postprocess 平均耗时、fallback 数
- `summary.failure_samples`：失败样本
- `images`：逐图指标和误差详情

### `GET /api/evaluations/{run_id}/compare?baseline_run_id=...`

- 用途：与基线评估对比。
- 返回重点：
  - `current_run`
  - `baseline_run`
  - `delta.metrics`
  - `delta.performance`
  - `per_label`
  - `current_failure_samples`
  - `baseline_failure_samples`
  - `top_regressions`
  - `top_improvements`

## 4. 直接影响 M20 前端重写的结论

## 4.1 现在应该删掉的错误结构

- 顶层“运行”页
- 顶层“开发”页
- 依赖 mock 聚合工作台 shape 的页面数据层

## 4.2 现在应该收拢成的结构

- 顶层：
  - 项目
  - 诊断
- 项目内标签：
  - 概览
  - 数据
  - 标注
  - 微调
  - 评估
  - 设置

其中“设置”拆成：

- 全局设置
  - `/api/system/config`
  - `/api/system/settings`
  - `/api/system/profiles/activate`
  - `/api/system/model/activate`
- 项目设置
  - `/api/projects/{project_id}/settings`
  - `/api/projects/{project_id}/models/activate`

## 4.3 可视化应该怎么做

- 微调页：
  - 用 `metrics[].loss` 画折线
  - 用 `metrics[].learning_rate` 画辅助线或 tooltip
  - 用 `/log` 展示原始日志
- 评估页：
  - 用 `metrics` 做总览
  - 用 `report.performance` 做时延图
  - 用 `report.summary.failure_samples` 做失败样本表
  - 用 `compare` 做回归/提升对比

## 4.4 还需要后端补接口的地方

当前如果首页项目列表要稳定展示这些字段，还需要额外设计或补接口：

- 图片数
- 待复核数
- 最近任务状态
- 当前 active model

因为 `GET /api/projects` 目前并不直接给这些聚合字段。

## 5. 临时结论

当前前端重写应该优先按这三条收口：

1. 先做一层真实后端 adapter，别再直接围着 mock shape 写页面。
2. 先把“设置分层”和“训练/评估可视化”改到真实接口口径上。
3. 项目列表如果继续要放聚合 KPI，要么前端拼装，要么后端补聚合接口，不能假设现成存在。
