# 真实后端联调测试指南

> 目标：为当前仓库提供一份可直接执行的“真实后端联调测试”文档，用于验证 FastAPI + Redis worker + vLLM/OpenAI-compatible + SAM2 + LLaMA-Factory 相关能力在不同环境档位下的真实可用性。
>
> 适用日期：2026-04-15。
>
> 审核基线：`backend/`、`tests/`、`scripts/verify_*.py`、`README.md`、`docs/frontend_api_inventory.md`。

---

## 1. 文档定位

这份文档不是设计稿，也不是接口文档，而是面向联调执行者的操作手册，回答以下问题：

- 当前后端“真实联调”到底要验证哪些能力
- 哪些能力可以在 `dev_low_resource` 做低资源联调
- 哪些能力必须在 `test_real_stack` 或 `demo_prod` 上验证
- 每一项联调的启动方式、执行步骤、通过标准和产物记录方式是什么
- 出问题时优先看哪里、怎么判断是配置问题还是代码问题

补充边界：

- 当前仓库还没有 `M19` 里的 `doctor/selftest` HTTP API 或最终 OCI 分发入口。
- 当前真实联调仍以脚本、启动命令、浏览器回归、API 验证和日志分析为主。
- 前端不属于本文重点，但部分后端联调需要借助浏览器验证真实任务状态、配置展示和业务闭环。

---

## 2. 当前真实后端能力范围

根据 `docs/frontend_api_inventory.md`、路由实现和测试代码，当前后端真实能力中心包括：

- 项目创建、删除、workflow 元信息与项目设置读取
- 图片上传、列表、文件访问、数据集 split 修改
- 标注读取、手工创建、删除、确认、bbox 纠正、点纠正
- 项目级自动标注异步任务与任务状态轮询
- Redis 持久化任务状态与独立 worker 消费
- WebSocket 任务进度推送
- 系统级运行时设置与 profile 切换
- 项目级模型激活、LoRA 激活与推理路由
- 数据集导入导出
- 微调任务、日志、训练指标摘要
- 评估运行、评估报告、run 对比、失败样本摘要

当前明确不在真实后端联调范围内的能力：

- `doctor/selftest` HTTP 接口
- 项目工作台聚合接口
- 标注工作台聚合接口
- 任务取消 / 重试 / 清理
- 微调超参数自由提交界面

---

## 3. 联调档位与建议用途

### 3.1 `dev_low_resource`

用途：

- 本地低资源联调
- 页面与 API 基线联调
- Redis / worker / WebSocket 行为验证
- stub LLM / stub SAM / mock 微调 runner 的完整业务闭环验证

建议验证内容：

- 项目 / 图片 / 标注 / 导入导出
- 设置分层与配置回显
- Redis worker + WebSocket / 轮询回退
- 评估与报告接口
- 微调流程控制、日志解析、LoRA tag 激活语义

不建议在该档位强行验证的内容：

- 真实 vLLM 大模型推理效果
- 真实 SAM2 GPU 推理效果
- 真实 LLaMA-Factory 长时间训练效果

### 3.2 `test_real_stack`

用途：

- 当前主推荐的真实后端联调档
- 连接真实 Redis、真实 vLLM / OpenAI-compatible、真实 SAM2、真实训练环境
- 验证模型路由、真实耗时、真实 mask、真实训练与评估链路

建议验证内容：

- `M11` 真实 vLLM 接入
- `M12 / M17` 真实 SAM2 分割和点修正
- `M13` Redis 独立 worker、多进程任务消费
- `M14` 真实 LLaMA-Factory subprocess 与 LoRA 激活
- `M15` 真实模型前后评估对比

### 3.3 `demo_prod`

用途：

- 答辩 / 演示环境回归
- 大模型档位、较激进超时配置、固定演示链路

建议验证内容：

- 演示流程完整性
- 模型选择和配置是否与答辩机器一致
- 页面回显和后端产物是否与预期一致

---

## 4. 联调前置条件

## 4.1 基础环境

至少需要：

- Python 虚拟环境可用
- `requirements.txt` 安装完成
- `frontend/` 依赖可安装
- 仓库根目录可读写 `data/`、`logs/`、`models/`

Linux 主路径建议直接使用：

```bash
bash scripts/start-linux.sh --profile dev_low_resource --run-tests
```

真实栈建议：

```bash
bash scripts/start-linux.sh --profile test_real_stack --with-vllm --with-sam --with-llamafactory
```

## 4.2 关键外部依赖

按联调目标不同，可能需要：

- Redis
- vLLM / OpenAI-compatible 服务
- `sam2` 运行环境与 checkpoint
- `llamafactory-cli`
- GPU / CUDA / 驱动 / 显存

## 4.3 当前推荐检查项

在正式联调前，至少确认：

- `GET /healthz` 返回 `200`
- `GET /api/health` 返回 `200`
- `.env.active` 与 `frontend/.env.local` 来自目标 profile
- `data/system/runtime_settings.json` 不包含意外的历史污染配置
- Redis DB 使用独立库号，避免污染日常开发数据

---

## 5. 联调执行方式

建议把真实后端联调拆成四层，而不是一次跑完所有场景。

### 5.1 第 1 层：启动与健康检查

目标：

- 服务能启动
- 路由能访问
- Redis 可连通
- 任务基础设施可初始化

最低检查：

- `GET /healthz`
- `GET /api/health`
- `GET /api/projects/meta`
- `GET /api/system/config`

### 5.2 第 2 层：低资源业务闭环

目标：

- 在 `dev_low_resource` 下验证接口契约和任务闭环
- 不依赖真实大模型，也能跑通项目主流程

最低检查：

- 项目创建
- 图片上传
- 自动标注任务
- 标注查看 / 删除 / 确认 / 纠正
- 导入导出
- 评估
- 微调入口和日志读取

### 5.3 第 3 层：真实依赖逐项验证

目标：

- 按模块分别验证真实 Redis、真实 vLLM、真实 SAM2、真实训练 runner

原则：

- 一次只引入一个新增真实外部依赖，避免问题定位困难
- 每项通过后记录日志路径、环境变量和结果摘要

### 5.4 第 4 层：完整真实栈闭环

目标：

- 在 `test_real_stack` 上跑一次真实“上传 → 自动标注 → 修正 → 微调 / 评估”闭环
- 留存报告、日志、截图和关键产物路径

---

## 6. 已有验证脚本与推荐用途

仓库里已经有几类可复用脚本：

### 6.1 `scripts/verify_m13_real_redis.py`

用途：

- 验证真实 Redis + 独立 worker + 前后端 + 浏览器回归

适合验证：

- `M13` 任务基础设施
- Redis 状态持久化
- 独立 worker 消费
- WebSocket / 轮询路径

示例：

```bash
python scripts/verify_m13_real_redis.py \
  --redis-url redis://127.0.0.1:6379/15 \
  --flush-redis-db
```

### 6.2 `scripts/verify_m14_browser.py`

用途：

- 在真实 Redis 基础上验证微调闭环的浏览器回归
- 默认使用 mock `llamafactory-cli`，更适合低资源稳定回归

适合验证：

- 微调任务启动
- 日志解析与状态更新
- 激活 LoRA tag
- 前端微调页回显

示例：

```bash
python scripts/verify_m14_browser.py \
  --redis-url redis://127.0.0.1:6379/14 \
  --flush-redis-db
```

### 6.3 `scripts/verify_real_model_api.py`

用途：

- 验证真实 vLLM 服务可达
- 验证后端通过真实模型完成自动标注

适合验证：

- `M11` 真实模型路由
- `openai_compatible` 模式
- 真实模型名是否被后端正确使用

示例：

```bash
python scripts/verify_real_model_api.py \
  --backend-base-url http://127.0.0.1:8000 \
  --vllm-base-url http://127.0.0.1:8001 \
  --served-model-name qwen3-vl-8b
```

### 6.4 `scripts/verify_design_doc_real_stack.py`

用途：

- 用接近设计文档闭环的方式做真实端到端验证
- 覆盖项目、图片、自动标注、纠正、导出、评估、微调激活等主路径

适合验证：

- “设计文档最小闭环”在真实后端上是否成立

示例：

```bash
python scripts/verify_design_doc_real_stack.py \
  --backend-base-url http://127.0.0.1:8000 \
  --image-path /abs/path/sample.jpg \
  --phase phase1
```

---

## 7. 推荐联调矩阵

| 编号 | 目标 | 档位 | 外部依赖 | 推荐入口 | 通过标准 |
|---|---|---|---|---|---|
| R1 | API 启动与健康检查 | `dev_low_resource` | 无或最小 Redis | `start-linux.sh` / 手动 `uvicorn` | `healthz`、`api/health`、`projects/meta` 正常 |
| R2 | 项目/图片/标注基础闭环 | `dev_low_resource` | stub | API + 浏览器手测 | 创建、上传、查看、删除、确认成功 |
| R3 | Redis 独立 worker 联调 | `dev_low_resource` | 真实 Redis | `verify_m13_real_redis.py` | worker 正常消费，浏览器回归通过 |
| R4 | 设置与模型路由语义 | `dev_low_resource` / `test_real_stack` | 可选真实 vLLM | API 手工验证 | 系统级 / 项目级设置分层正确，`active_model_tag` 生效 |
| R5 | 真实 vLLM 自动标注 | `test_real_stack` | Redis + vLLM | `verify_real_model_api.py` | 真实模型可调用，标注成功写库 |
| R6 | 真实 SAM2 分割与点修正 | `test_real_stack` | Redis + SAM2 | 手工接口 + 浏览器 | 真实 `mask_path`、polygon、点修正有效 |
| R7 | 微调流程控制与回显 | `dev_low_resource` | Redis + mock CLI | `verify_m14_browser.py` | job 状态、日志、激活回显正常 |
| R8 | 真实 LLaMA-Factory 训练 | `test_real_stack` | Redis + CLI + GPU | 手动 / API | 真实训练目录、日志、LoRA 产物出现 |
| R9 | 评估报告与 run 对比 | `dev_low_resource` / `test_real_stack` | 可选真实模型 | API + 浏览器 | 报告、对比、失败样本、性能统计可读 |
| R10 | 完整真实闭环 | `test_real_stack` | Redis + vLLM + SAM2 + CLI | `verify_design_doc_real_stack.py` + 手测 | 主闭环全通，产物可留档 |

---

## 8. 分模块真实联调步骤

## 8.1 启动与健康检查

### 目标

- 确认 API、Redis、worker、前端开发服务器、vLLM、SAM 所在进程都能按预期拉起

### 操作

1. 使用目标 profile 启动服务
2. 访问：
   - `GET /healthz`
   - `GET /api/health`
   - `GET /api/projects/meta`
   - `GET /api/system/config`
3. 检查后端启动日志中是否有：
   - DB 初始化成功
   - Redis ping 成功
   - worker 正常启动

### 通过标准

- 健康检查接口全部正常
- 没有持续刷新的启动异常
- profile 与运行时配置回显正确

## 8.2 项目、图片与基础标注

### 目标

- 验证最基础的 CRUD 与文件落盘

### 操作

1. `POST /api/projects`
2. `PATCH /api/projects/{id}/settings` 设置 `labels`
3. `POST /api/projects/{id}/images/upload`
4. `GET /api/projects/{id}/images`
5. `POST /api/images/{id}/annotations`
6. `GET /api/images/{id}/annotations`
7. `PATCH /api/annotations/{id}/confirm`
8. `DELETE /api/annotations/{id}`

### 需要观察

- `data/projects/{project_id}/images/` 是否生成文件
- 图片尺寸、split、status 是否回显正确
- `is_confirmed` 是否变化

### 通过标准

- 所有操作返回符合统一 JSON 包裹格式
- 标注增删改确认刷新后仍然一致

## 8.3 自动标注任务与任务状态

### 目标

- 验证项目级自动标注任务、Redis 状态写入、轮询与 WebSocket

### 操作

1. 保证项目已设置 `labels`
2. `POST /api/projects/{id}/annotate`
3. 轮询 `GET /api/tasks/{task_id}/status`
4. 订阅 `WS /ws/tasks/{task_id}`
5. 完成后读取标注结果

### 建议脚本

```bash
python scripts/verify_m13_real_redis.py --redis-url redis://127.0.0.1:6379/15 --flush-redis-db
```

### 通过标准

- 任务状态至少经历 `PENDING -> STARTED -> SUCCESS`
- worker 独立消费时结果仍能正确写回
- 浏览器断开 WebSocket 后轮询仍可兜底

## 8.4 设置分层与 profile 切换

### 目标

- 验证系统级设置与项目级设置的职责边界

### 操作

1. `GET /api/system/settings`
2. `PATCH /api/system/settings`
3. `POST /api/system/profiles/activate`
4. `POST /api/system/model/activate`
5. `GET /api/projects/{id}/settings`
6. `PATCH /api/projects/{id}/settings`

### 重点检查

- 项目设置接口只允许 `labels`、`workflow_key`
- 系统设置接口负责 `model_profile`、`llm`、`sam`、`postprocess`、`quality`、`evaluation`
- `_meta.hot_reload_paths` / `_meta.reload_required_paths` 是否合理

### 通过标准

- 接口边界与 `docs/frontend_api_inventory.md` 一致
- 非法字段提交时返回合理错误信息

## 8.5 模型路由与真实 vLLM

### 目标

- 验证 `openai_compatible` 模式和 `active_model_tag` 的真实效果

### 前置条件

- vLLM 服务已启动
- 后端配置使用 `ANNOTATION_BACKEND=openai_compatible`
- `VLLM_BASE_URL` 和 `VLLM_MODEL_NAME` 正确

### 操作

1. 先直接请求 vLLM `/v1/models`
2. 再直接请求 `/v1/chat/completions`
3. `PATCH /api/system/settings` 设置基础模型名
4. 创建项目并触发自动标注
5. 查看 annotation 的 `inference` 字段
6. 如有 LoRA，切换 `POST /api/projects/{id}/models/activate`

### 建议脚本

```bash
python scripts/verify_real_model_api.py \
  --backend-base-url http://127.0.0.1:8000 \
  --vllm-base-url http://127.0.0.1:8001 \
  --served-model-name qwen3-vl-8b
```

### 通过标准

- vLLM 可达且模型名匹配
- 后端自动标注成功
- `inference.requested_model_tag` / `effective_model_tag` / `route_kind` 合理

## 8.6 真实 SAM2 分割与点修正

### 目标

- 验证真实 `SAM2` 推理、mask 落盘、polygon 生成和点修正闭环

### 前置条件

- 分割项目
- `sam.checkpoint` 可用
- 真实 `sam2` 环境已就绪

### 操作

1. 创建分割项目并上传图片
2. 触发自动标注或手工创建 bbox 标注
3. 确认返回 `polygon`、`mask_path`
4. 使用 `POST /api/images/{id}/predict` 发送正负点
5. 再次读取标注并确认 polygon/mask 已更新

### 需要检查

- `data/projects/{project_id}/masks/` 下生成 mask 文件
- provider 标识反映真实 SAM2 路径
- 点修正后结果与原 mask 有变化

### 通过标准

- 真实 `mask PNG` 存在
- polygon 非空
- 点修正接口成功且结果更新

## 8.7 微调闭环

### 目标

- 验证微调任务启动、日志生成、训练指标解析、LoRA 激活

### 两种验证模式

#### 低资源回归模式

- 使用 `verify_m14_browser.py`
- 真实 Redis + mock `llamafactory-cli`
- 适合验证流程控制与前端回显

#### 真实训练模式

- 使用 `FINETUNE_BACKEND=llamafactory`
- 配置真实 `LLAMAFACTORY_CLI`
- 在 `test_real_stack` 上验证真实训练输出

### 操作

1. 准备至少一个已确认标注的数据项目
2. `POST /api/finetune/start`
3. 轮询 `GET /api/finetune/{id}/status`
4. 读取 `GET /api/finetune/{id}/log`
5. 完成后 `POST /api/finetune/{id}/activate`
6. 重新发起自动标注或评估，确认路由已切换

### 通过标准

- job 状态从 `pending/running` 进入 `done`
- 训练日志存在
- `metrics` 非空或至少能解析出关键日志片段
- 激活后项目 `active_model_tag` 更新

## 8.8 评估报告与对比

### 目标

- 验证评估运行、报告读取、run 对比、失败样本和性能统计

### 操作

1. `POST /api/projects/{id}/evaluate`
2. 轮询任务完成
3. `GET /api/evaluations/{run_id}`
4. `GET /api/evaluations/{run_id}/report`
5. 再跑一次不同模型或不同时间点的评估
6. `GET /api/evaluations/{run_id}/compare`

### 通过标准

- `metrics` 可读
- `report.images`、`summary.failure_samples`、`performance` 有内容
- compare 结果能给出 `delta`

## 8.9 数据集导入导出

### 目标

- 验证 YOLO / COCO 导入导出不会破坏真实数据闭环

### 操作

1. `GET /api/projects/{id}/export?format=yolo`
2. 校验 zip 内容结构
3. `POST /api/projects/{id}/import`
4. 重新拉取图片和标注，确认导入数量

### 通过标准

- 导出 zip 可解压
- 导入数量符合预期
- 导入后的标注可继续参与评估或训练

---

## 9. 推荐执行顺序

建议按以下顺序推进，问题定位最省时：

1. `R1` 启动与健康检查
2. `R2` 基础闭环
3. `R3` Redis 独立 worker
4. `R4` 设置分层与模型路由语义
5. `R5` 真实 vLLM
6. `R6` 真实 SAM2
7. `R7` 微调流程控制
8. `R8` 真实训练
9. `R9` 评估与对比
10. `R10` 完整真实闭环

不要一开始就直接做完整真实闭环，否则很难判断问题来自：

- Redis
- worker
- vLLM
- SAM2
- 训练环境
- 前端回显
- 还是 profile 配置

---

## 10. 联调产物与记录要求

每次真实联调建议至少保留以下产物：

- 启动命令
- profile 名称
- `.env.active` 关键项摘要
- Redis URL / DB 编号
- 后端日志路径
- worker 日志路径
- vLLM / SAM / 训练日志路径
- 浏览器截图或回归脚本结果 JSON
- 评估报告路径
- 导出数据集路径
- 如失败，记录失败步骤、接口响应、日志片段和复现命令

建议在每次联调后记录一份结果摘要，格式可参考：

```md
### 2026-04-15 / test_real_stack / R5 + R6

- 目标：验证真实 vLLM + SAM2 自动标注与点修正
- 环境：Ubuntu 22.04 / 单卡 GPU / APP_PROFILE=test_real_stack
- 结果：通过
- 命令：
  - `bash scripts/start-linux.sh --profile test_real_stack --with-vllm --with-sam`
  - `python scripts/verify_real_model_api.py ...`
- 关键产物：
  - `logs/start-linux-.../backend.log`
  - `data/projects/12/masks/...`
  - `output/.../browser-result.json`
- 备注：点修正有效，SAM2 推理耗时约 xx ms
```

---

## 11. 常见失败点与排障建议

## 11.1 启动失败

优先检查：

- `.env.active`
- profile 是否正确
- `VLLM_BASE_URL`
- `REDIS_URL`
- `TASK_EMBEDDED_WORKER`
- `CORS_ALLOW_ORIGINS`

## 11.2 Redis 相关问题

现象：

- 任务创建成功但不消费
- `/api/tasks/{id}/status` 长时间停留在 `PENDING`

优先检查：

- worker 是否独立启动
- Redis DB 是否一致
- 是否误用了被其他流程污染的 DB 号
- worker 日志是否有消费异常

## 11.3 vLLM 相关问题

现象：

- `/v1/models` 无目标模型
- 自动标注回退到 stub
- 请求超时

优先检查：

- `VLLM_MODEL_NAME`
- `served-model-name`
- `llm.base_model`
- `ANNOTATION_BACKEND=openai_compatible`
- vLLM 启动日志与显存参数

## 11.4 SAM2 相关问题

现象：

- 分割项目没有 `mask_path`
- polygon 为空
- 点修正无效

优先检查：

- `sam.checkpoint`
- `SAM_CHECKPOINT_PATH` / `SAM2_CHECKPOINT_PATH`
- `sam.device`
- 真实 `sam2` 是否安装成功
- 是否实际回退到了 stub

## 11.5 微调相关问题

现象：

- job 长时间不结束
- 日志为空
- 激活失败

优先检查：

- `FINETUNE_BACKEND`
- `LLAMAFACTORY_CLI`
- 训练输出目录权限
- job 日志路径
- `VLLM_ENABLE_RUNTIME_LORA_UPDATE`

## 11.6 浏览器联调相关问题

现象：

- 页面能开，但 API 请求失败
- WebSocket 提示异常
- 任务条状态不同步

优先检查：

- `VITE_API_BASE_URL`
- `CORS_ALLOW_ORIGINS`
- 前端使用的端口与后端白名单是否一致
- 是否命中了轮询回退而非 WebSocket 主路径

---

## 12. 通过标准总表

一次“真实后端联调通过”至少应满足以下层级中的对应要求：

### 最低通过

- `dev_low_resource` 下主流程可跑
- API 契约稳定
- Redis worker / 轮询 / WebSocket 正常
- 浏览器能完成基础业务回归

### 模块通过

- `R5` 真实 vLLM 通过
- `R6` 真实 SAM2 通过
- `R8` 真实 LLaMA-Factory 通过
- `R9` 评估报告和对比通过

### 完整真实栈通过

- `test_real_stack` 上完整闭环通过
- 有日志、截图、评估报告、训练产物作为证据
- 降级路径仍可工作，不会因为真实依赖缺失导致整个系统不可用

---

## 13. 当前建议

如果只想做一次“全面但可控”的真实后端联调，当前推荐顺序是：

1. 先在 `dev_low_resource` 跑 `verify_m13_real_redis.py`
2. 再在 `dev_low_resource` 跑 `verify_m14_browser.py`
3. 接着在 `test_real_stack` 跑 `verify_real_model_api.py`
4. 最后在 `test_real_stack` 跑 `verify_design_doc_real_stack.py`

这样能分别覆盖：

- 任务基础设施
- 微调流程控制
- 真实模型推理
- 设计文档最小闭环

如果这四步都通过，当前仓库的“真实后端联调”就已经具备较高可信度。
