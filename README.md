# 自动标注系统（开发中）

本仓库是一个**单机单用户**的自动标注闭环系统：图片上传 → 自动标注（检测/可选分割）→ 人工纠错 →（可选）微调/评估。

- 技术路线与目标见 `design_doc.md`
- 可执行的开发计划与进度见 `dev_plan.md`

## 快速开始（开发）

### 后端（FastAPI）

1) 安装依赖（建议使用虚拟环境）

```powershell
python -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

2) 启动

```powershell
python -m backend.main
```

健康检查：`GET http://127.0.0.1:8000/healthz`

### 配置档位与一键切换（M10）

- 后端会优先读取仓库根目录下的 `.env.active`
- 前端 Vite 会读取 `frontend/.env.local`
- 推荐直接用脚本切换：

```powershell
.\scripts\use-profile.ps1 -Profile dev_low_resource
.\scripts\use-profile.ps1 -Profile test_real_stack
.\scripts\use-profile.ps1 -Profile demo_prod
```

- 也可以在启动时一起切换：

```powershell
.\start-dev.ps1 -Profile dev_low_resource
.\start-dev.ps1 -Profile demo_prod
```

- `dev_low_resource`：低算力开发档，默认 `stub/mock/CPU` 友好
- `test_real_stack`：后续统一联调档，面向真实 vLLM / SAM / 训练环境
- `demo_prod`：答辩/演示档，使用更激进的模型与超时配置

### 自动标注（M4）

- 默认使用 `stub` 后端，配置项目 `labels` 后即可直接跑通 bbox 自动标注。
- 如需接入 OpenAI-compatible / vLLM 服务，可在启动前设置环境变量：

```powershell
$env:ANNOTATION_BACKEND="openai_compatible"
$env:VLLM_BASE_URL="http://127.0.0.1:8001"
$env:VLLM_MODEL_NAME="qwen3-vl-2b"
python -m backend.main
```

### 前端（Vue + Vite）

```powershell
cd frontend
npm install
npm run dev
```

默认前端地址：`http://localhost:5173`

### 项目设置面板（M10）

在项目图片列表页已经接入项目级配置中心，可直接查看和保存：

- `model_profile`、`llm.*`、`sam.*`
- `postprocess.*`
- `quality.*`
- `evaluation.*`

其中：

- `postprocess.*`、`quality.*`、`evaluation.*` 为热更新字段，保存后会影响后续任务与页面展示
- `model_profile`、`llm.base_model`、`sam.*` 等字段会在保存后提示“需要显式重载/重启”
- 系统 profile 切换按钮会同时更新 `.env.active` 和 `frontend/.env.local`

### 模型路由与切换（M11）

项目图片列表页现在额外支持：

- 项目级 `active_model_tag` 显式切换，支持 `base` 和已完成的 `lora:{job_id}`
- 自动标注和评估真正按照当前 `active_model_tag` 路由，而不是只把它当展示字段
- 当 `ANNOTATION_BACKEND=openai_compatible` 时，优先走 vLLM / OpenAI-compatible 请求；失败后会清晰回退到 `stub`
- 图片详情页会展示自动标注实例的运行时来源，例如 `stub · base -> qwen3-vl-4b · fallback`
- 评估卡片会展示本次 run 的实际路由摘要，例如 `route=lora:6 -> lora:6`

常用接口：

```powershell
POST /api/projects/{id}/models/activate
POST /api/finetune/{id}/activate
POST /api/projects/{id}/evaluate
```

其中：

- `POST /api/projects/{id}/models/activate` 用于在 `base` 和 `lora:{job_id}` 之间切换当前项目的活动模型
- `POST /api/finetune/{id}/activate` 仍然保留，用于从最近完成的 LoRA 任务快速激活对应 tag

---

## 约定

- 本地数据默认写入 `data/`（不会提交到 git）
- 里程碑采用“提交 + 自动验证 + 人工验收”节奏推进
