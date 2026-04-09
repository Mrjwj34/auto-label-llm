# 自动标注系统（开发中）

本仓库是一个**单机单用户**的自动标注闭环系统：图片上传 → 自动标注（检测/可选分割）→ 人工纠错 →（可选）微调/评估。

- 技术路线与目标见 `design_doc.md`
- 可执行的开发计划与进度见 `dev_plan.md`

## 快速开始（Linux 主路径）

现在统一只保留一个 Linux 启动脚本：

```bash
bash scripts/start-linux.sh --profile dev_low_resource --run-tests
```

这条命令会在一处完成：

- 自动检查并补齐 Linux 基础依赖（Ubuntu / Debian 主路径）
- 创建或复用 `.venv`
- 按依赖指纹缓存安装 `requirements.txt` 与可选 Python 包，避免每次启动都重复 `pip install`
- 按 `package-lock.json` / `package.json` 指纹缓存前端依赖，避免每次都重复 `npm ci`
- 根据 profile 生成 `.env.active` 与 `frontend/.env.local`
- 可选运行 `compileall + pytest + frontend build`
- 拉起 Redis、worker、FastAPI、前端开发服务器
- 在 `test_real_stack` / `demo_prod` 下按需补齐 `torch`、`sam3`、`vllm`、`LLaMA-Factory`
- 启动本地 `vllm` 时默认使用更保守的显存参数，并在启动阶段持续输出最近日志，避免“卡住但没日志”

常用用法：

```bash
# 低算力稳妥联调，顺带跑全量测试
bash scripts/start-linux.sh --profile dev_low_resource --run-tests

# 只补环境，不启动服务；适合先预热昂贵算力机器
bash scripts/start-linux.sh --profile test_real_stack --setup-only --with-sam3 --with-llamafactory

# 真正的本地真实栈联调：本机起 vLLM + SAM3 + LLaMA-Factory
VLLM_MODEL_SOURCE=Qwen/Qwen3-VL-8B-Instruct-FP8 \
bash scripts/start-linux.sh --profile test_real_stack --with-vllm --with-sam3 --with-llamafactory

# 如果显存比较紧，可以继续压低 vLLM 参数，或透传额外参数
VLLM_MODEL_SOURCE=Qwen/Qwen3-VL-8B-Instruct-FP8 \
bash scripts/start-linux.sh --profile test_real_stack --with-vllm \
  --vllm-max-model-len 2048 \
  --vllm-gpu-memory-utilization 0.72 \
  --vllm-arg --limit-mm-per-prompt --vllm-arg image=2

# 如果真实 vLLM 已经在别处运行，只让脚本接管其余服务
VLLM_BASE_URL=http://127.0.0.1:8001 \
bash scripts/start-linux.sh --profile test_real_stack --skip-vllm
```

补充说明：

- `dev_low_resource`：低算力开发档，默认 `stub/mock/CPU` 友好
- `test_real_stack`：统一联调档，面向真实 vLLM / SAM / 训练环境
- `demo_prod`：答辩演示档，使用更激进的模型与超时配置
- 脚本默认把日志写到 `logs/start-linux-时间戳/`
- 依赖安装缓存默认写到 `.cache/start-linux/install-state/`
- 需要强制重装时可使用 `--refresh-python-deps`、`--refresh-frontend-deps`、`--refresh-optional-deps` 或 `--refresh-all-deps`
- 这是单机开发 / 单机演示脚本，不包含 Nginx、反向代理、生产部署编排
- 后端仍优先读取仓库根目录 `.env.active`，前端仍读取 `frontend/.env.local`，但现在都由 `scripts/start-linux.sh` 自动生成，不需要再单独切 profile

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

### 运行时设置入口（M10）

项目图片列表页现在承载的是“系统级运行时设置入口”，可直接查看和保存：

- `model_profile`、`llm.*`、`sam.*`
- `postprocess.*`
- `quality.*`
- `evaluation.*`

项目级仍保留：

- `labels`
- `active_model_tag`

其中：

- `postprocess.*`、`quality.*`、`evaluation.*` 为热更新字段，保存后会影响后续任务与页面展示
- `model_profile`、`llm.base_model`、`sam.*` 等字段会在保存后提示“需要显式重载/重启”
- 系统 profile 切换按钮会同时更新 `.env.active` 和 `frontend/.env.local`
- 系统级运行时设置会持久化到 `data/system/runtime_settings.json`

### 任务推送（M13 第一阶段）

- 批量自动标注页面会优先连接 `WS /ws/tasks/{task_id}` 接收任务进度更新
- 浏览器或服务端不支持 WebSocket 时，前端会自动回退到轮询 `/api/tasks/{task_id}/status`
- 当前实现已经切到基于 Redis 的任务状态与队列骨架：`RedisTaskManager` 负责状态持久化，`RedisTaskWorker` 负责消费 annotation / evaluation / finetune 队列
- 开发测试可以继续使用 `fakeredis` + 嵌入式 worker；真实联调时可以把 `TASK_EMBEDDED_WORKER=false`，单独启动 `python -m backend.task_worker_main`
- 若本机已有可用 Redis，可直接跑真实链路验证：
```powershell
.\.venv\Scripts\python.exe scripts\verify_m13_real_redis.py --redis-url redis://127.0.0.1:6379/15 --flush-redis-db
```

### 微调与 LoRA（M14 进行中）

- 微调任务现在支持 `FINETUNE_BACKEND=auto|mock|llamafactory`
- 默认 `auto` 会在检测到 `LLAMAFACTORY_CLI` 可用时走真实 `llamafactory-cli train <config>` 子进程；否则回退到可测试的 mock runner
- 每个微调 job 会额外落盘：
  - 训练数据：`data/projects/{project_id}/exports/finetune/job_{job_id}/project_{project_id}_train.jsonl`
  - `dataset_info.json`
  - `llamafactory-train.yaml`（当前实现使用 JSON 兼容 YAML 的内容，便于测试与真实 CLI 共用）
- `GET /api/finetune/{id}/status` 现在会返回解析后的 `metrics`，前端会展示 runner 类型和 loss 点位摘要
- 如果启用 `VLLM_ENABLE_RUNTIME_LORA_UPDATE=true`，激活 LoRA 时会调用 vLLM 运行时接口 `/v1/load_lora_adapter` / `/v1/unload_lora_adapter`
- 如果未启用上述开关，激活操作仍然会更新项目的 `active_model_tag`，但不会主动改动外部 vLLM 进程
- 可直接运行浏览器回归脚本验证完整链路：
```powershell
.\.venv\Scripts\python.exe scripts\verify_m14_browser.py --redis-url redis://127.0.0.1:6379/14 --flush-redis-db
```

### 模型路由与切换（M11）

项目图片列表页现在额外支持：

- 项目级 `active_model_tag` 显式切换，支持 `base` 和已完成的 `lora:{job_id}`
- 自动标注和评估真正按照当前 `active_model_tag` 路由，而不是只把它当展示字段
- 当 `ANNOTATION_BACKEND=openai_compatible` 时，优先走 vLLM / OpenAI-compatible 请求；失败后会清晰回退到 `stub`
- 图片详情页会展示自动标注实例的运行时来源，例如 `stub · base -> qwen3-vl-8b · fallback`
- 评估卡片会展示本次 run 的实际路由摘要，例如 `route=lora:6 -> lora:6`

当前实现的真实状态：

- M11 不是直连 OpenAI 云 API，而是请求 `VLLM_BASE_URL/v1/chat/completions` 这类 OpenAI-compatible 接口；默认目标是本地/私有 vLLM 服务
- `lora:{job_id}` 已经真实参与项目配置、评估记录和请求路由
- M14 当前新增了真实 LLaMA-Factory 子进程训练入口，以及可选的 vLLM 运行时 LoRA 加载/卸载接口联动
- 低算力 / 测试环境仍然默认保留 mock finetune runner，确保 `pytest`、浏览器回归和本地联调稳定可跑

如果你要在 Linux 上把真实模型暴露成当前项目配置里的逻辑名称，直接让统一启动脚本接管本地 vLLM：

```bash
VLLM_MODEL_SOURCE=Qwen/Qwen3-VL-8B-Instruct-FP8 \
bash scripts/start-linux.sh --profile test_real_stack --with-vllm
```

这样后端仍然请求 profile 里的 `VLLM_MODEL_NAME`，但本地 vLLM 实际加载的是你指定的 Hugging Face 模型或本地模型目录。

常用接口：

```powershell
POST /api/projects/{id}/models/activate
POST /api/finetune/{id}/activate
POST /api/projects/{id}/evaluate
```

其中：

- `POST /api/projects/{id}/models/activate` 用于在 `base` 和 `lora:{job_id}` 之间切换当前项目的活动模型
- `POST /api/finetune/{id}/activate` 仍然保留，用于从最近完成的 LoRA 任务快速激活对应 tag；启用 `VLLM_ENABLE_RUNTIME_LORA_UPDATE=true` 时也会同步触发 vLLM 运行时 LoRA 更新

### 分割与 SAM3（M12）

- 分割项目现在会真实生成二值 `mask PNG` 并同步产出 polygon，`mask_path` 会落盘到 `data/projects/{project_id}/masks/`
- 默认开发档仍然优先走低算力友好的 `stub`，但 stub 已升级为“先生成真实 mask，再统一后处理/落盘”，因此本地联调、接口测试、浏览器纠错测试都能覆盖真实数据流
- 项目默认 `sam.checkpoint` 已切到 `sam3` / `sam3.1` symbolic alias；`test_real_stack` / `demo_prod` 默认使用 `sam3.1`
- `bash scripts/start-linux.sh --profile test_real_stack --with-sam3 ...` 或 `demo_prod` 路径下，如果 `models/sam3/` 里还没有可用 checkpoint，脚本现在会自动补齐对应的 `sam3.1` 权重，避免真实联调时静默回退到 stub
- 其他启动方式下，真实 SAM3 仍然按“显式开启”处理：
  - 提供本地 `.pt` checkpoint 路径给 `sam.checkpoint`
  - 或在明确接受下载模型时设置 `SAM3_ALLOW_HF_DOWNLOAD=1`
- 现在额外支持两条更直接的真实路径：
  - 设置 `SAM3_CHECKPOINT_PATH=/abs/path/to/xxx.pt`
  - 直接把权重放进 `models/sam3/`，后端会自动按 `sam3` / `sam3.1` alias 优先匹配
- 如果本机没有安装官方 `sam3` / `torch`，或者你使用的是非真实 profile 且没有可用 checkpoint，后端会自动回退到 stub，不会在开发过程中偷偷拉起大模型下载

示例：

```powershell
$env:SAM3_ALLOW_HF_DOWNLOAD="1"
python -m backend.main
```

或在项目设置里把 `sam.checkpoint` 改成本地权重路径，例如：

```json
{
  "sam": {
    "checkpoint": "models/sam3/sam3.1_multiplex.pt",
    "device": "cuda",
    "multimask_output": false
  }
}
```

---

## 约定

- 本地数据默认写入 `data/`（不会提交到 git）
- 里程碑采用“提交 + 自动验证 + 人工验收”节奏推进
