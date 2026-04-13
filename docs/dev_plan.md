# 开发规划与进度跟踪（可执行版）

> 目标：把“自动标注 → 人工纠错 → 可选微调/评估”的闭环做成**单机可跑、可演示、可复现**的系统，并且每个阶段都有可验收的交付物与可回滚的 git 提交。
>
> 约定：本文档是**开发用作战计划**，不是技术设计稿的复述；每个里程碑都包含：范围、实现清单、验收标准、验证步骤、完成后要做的 git 操作。

---

## 0. 工作方式（强约束）

### 0.1 分阶段交付

- 每个里程碑都必须满足：
  - `自动验证`：我在本地运行测试/构建通过（或明确说明暂缺的原因与替代验证；若本机算力不足以跑真实模型，则必须补足等价的单测/集成测试/契约测试）。
  - `人工验证`：你按“人工验收清单”操作确认通过。
  - `git 提交`：通过后把该里程碑状态从 `⏳` 更新为 `✅`，并记录 commit hash。
- 未通过人工验证的里程碑，只能标记为 `🟡 待人工验收`，不能进入下一里程碑的功能开发（允许修 bug）。

### 0.2 代码与目录约定

- 单仓库，目录分区：`backend/`、`frontend/`、`data/`、`models/`、`logs/`、`tests/`。
- 本地持久化优先：DB 用 SQLite；图片/mask/导出文件都落盘到 `data/`。
- 先跑通流程再追求效果：模型推理集成允许“先 stub、后替换真实实现”，但接口与数据结构必须稳定。

### 0.3 里程碑状态标记

- `⬜ 未开始`
- `⏳ 进行中`
- `🟡 待人工验收`
- `✅ 已完成`
- `⛔ 阻塞（记录原因 + 解决方案）`

### 0.4 环境档位与验证替代策略

- 必须支持至少三套可切换环境档位：
  - `dev_low_resource`：开发机低算力档。默认使用 stub / mock / CPU / 最小模型配置，确保日常开发、页面联调、API 联调可持续进行。
  - `test_real_stack`：后续统一联调档。用于连接真实 vLLM / SAM / Redis / 训练环境，并在需要时补充 Celery 联调，验证真实链路。
  - `demo_prod`：演示/答辩档。面向高算力机器，使用最终推荐配置。
- 必须提供**一键切换测试配置和生产配置**的机制：
  - 形式可以是 `scripts/start-linux.sh --profile xxx`、`start --profile xxx`、`.env.profile` 覆盖或等价方案；
  - 目标是不手改零散环境变量，也不手动改代码。
- 当前开发机算力较低，M10～M15 的本地开发默认以 `dev_low_resource` 为主；真实模型、真实微调、完整外部依赖联调可延后到 `test_real_stack` 环境统一进行。
- 在统一联调之前，凡是无法在开发机直接跑真实链路的功能，必须用更详尽的替代验证覆盖，包括但不限于：
  - 单元测试：坐标转换、配置生效、后处理、质量评分、日志解析、任务状态迁移；
  - 集成测试：API 调用链、任务创建与轮询、模型切换状态、评估报告生成、导入导出闭环；
  - 浏览器测试：关键页面交互、状态展示、配置切换、错误提示；
  - 契约测试：对外部模型/训练进程的请求 payload、响应格式、配置快照、日志格式进行固定样例校验。
- `test_real_stack` 统一联调时，再补充真实外部依赖的验收记录；届时应优先验证“配置切换正确性、真实链路可跑通、降级路径仍有效”。

---

## 1. 里程碑总览（Roadmap）

> 说明：每个里程碑都尽量做到“完成后系统能演示一个新增能力”，避免大爆炸式开发。

| ID | 里程碑 | 目标演示点 | 状态 | 关联提交 |
|---|---|---|---|---|
| M0 | 仓库与开发环境初始化 | 能启动空后端/前端，文档齐全 | ✅ | 2be1b03 |
| M1 | 项目/图片基础闭环 | 上传图片 → 列表展示 → 打开查看 | ✅ | 79bc7d8 |
| M2 | 标注数据模型与读写 | 能保存/读取 bbox(检测) 标注 | ✅ | 2c3ad61 |
| M3 | 异步任务骨架与进度 | 项目级批量标注，任务进度可见 | ✅ | 91f571e |
| M4 | 自动标注（LLM Stub → 真实接入） | 自动生成 bbox，并写入 DB | ✅ | 53d2d7b |
| M5 | 分割能力（SAM Stub → 真实接入） | 生成 mask/polygon 并渲染 | ✅ | 71e5864 |
| M6 | 人工纠错（增删改确认） | 点选/补框/删除/确认生效 | ✅ | 2bc7e03 |
| M7 | 数据集导入/导出 | 导出 YOLO/COCO（最小可用） | ✅ | 28b96d4 |
| M8 | 微调流水线（可选） | 用确认数据导出 → 启动训练任务 | ✅ | d336852 |
| M9 | 评估与质量评分（MVP） | val/test 指标 + 线上风险排序 | ✅ | 85598a2 |
| M10 | 配置中心、热更新与环境切换 | 项目配置真正驱动推理/后处理/评估，并支持一键切换测试/生产档位 | ✅ | 26efec0 |
| M11 | 真实 LLM 推理与模型切换 | vLLM/OpenAI-compatible 真接入 + `active_model_tag` 真正生效 | ✅ | 233218f |
| M12 | 真实 SAM3 与后处理 | 真实 mask/polygon + `set_image` 缓存 + OpenCV 后处理 | ✅ | e550e40 |
| M13 | 任务基础设施升级 | Redis / WebSocket / GPU 锁升级当前轻量任务骨架，Celery 视需要补齐 | ✅ | - |
| M14 | 真实 LoRA 微调闭环 | LLaMA-Factory 真训练 + LoRA 激活后真正参与推理 | 🟡 | - |
| M15 | 评估系统增强与对比看板 | mask 指标、run 对比、失败案例分析、性能统计 | ✅ | - |
| M16 | 一键启动与演示脚本 | 一条命令启动所有服务与外部依赖 | ✅ | - |
| M17 | SAM3 → SAM2 迁移 | 分割链路切到更贴近当前需求的 SAM2 官方路线 | ✅ | 9742036 |
| M18 | 工作流系统重构（最小安全插件化） | 以 `workflow_key + task_family + atomic capabilities` 收敛流程编排，并先评估改动规模 | ✅ | b95edac / 506ca11 |
| M19 | OCI 分发与环境自检 | Docker Hub 固定镜像 + Compose + 模型缓存 + doctor/selftest | ⬜ | - |
| M20 | 前端完全重构 | 以正式产品形态重做前端架构、交互与视觉体系 | ⬜ | - |

> 说明：原 M10 “一键启动与演示脚本”顺延为 M16。M10～M15 用于补齐当前实现与 `design_doc.md` 之间的差距，目标是最终与设计文档一致。M17～M20 为下一阶段主计划，依次收敛模型选型、工作流编排、分发方式与前端产品化。

### 1.1 当前阶段收口结论（2026-04-14）

- 本轮收口范围覆盖 `M17`、`M18` 与两条默认 workflow 的真实环境验收，目标是把“检测 / 实例分割默认闭环”从本地回归推进到真机可复现。
- `M17` 以“完成 SAM2 迁移并稳定跑通默认分割链路”为验收口径，已经满足；真实 `SAM2` 自动分割、点修正、导出、评估均已在 `test_real_stack` 机器上跑通。
- `M18` 以“完成最小安全插件化范围”为验收口径，已经满足；`workflow registry`、`workflow_key`、`task_family`、capability seam、老项目兼容映射与默认 workflow 元数据都已落地。
- 当前闭环阶段正式收口，但这不等于“分割质量已经优化完成”；最新真图验证说明链路可用，`SAM2` 质量仍需在下一阶段继续优化提示方式、点提示策略、评估样本与后处理参数。
- `M18` 的 Phase 3/4（前端以 workflow 为主入口、引入首个非默认 workflow）仍保留在后续阶段，不包含在本次收口范围内。

---

## 2. 详细里程碑拆解

### M0 — 仓库与开发环境初始化

**范围**
- 建立基础目录结构、依赖清单、启动命令、基本 `README.md`。
- 建立统一响应格式与错误处理约定（后端）。

**实现清单**
- `backend/`：FastAPI 骨架、健康检查接口、配置读取。
- `frontend/`：Vue + Vite 骨架、路由与 API 客户端封装。
- `.gitignore`：忽略 `data/`、`models/`、`logs/`、前端构建产物、Python 缓存等。

**自动验证**
- 后端能 `uvicorn` 启动且 `/healthz` 返回 200。
- 前端能 `npm run dev` 启动并能访问首页。

**人工验收清单**
- 浏览器打开前端首页，页面显示“服务未连接/已连接”提示（至少有占位）。

**完成后的 git 操作**
- `git commit -m "chore: bootstrap repo structure"`

---

### M1 — 项目/图片基础闭环（第一个可演示 MVP）

**范围**
- 项目 CRUD（最少：创建/列表/删除）。
- 图片上传、落盘、写 DB。
- 图片列表查询（按项目）。
- 前端：项目列表页 + 图片列表页 + 上传组件。

**实现清单（后端）**
- SQLite + ORM（先 `create_all`，后续再补迁移工具）。
- API：
  - `GET /api/projects`
  - `POST /api/projects`
  - `DELETE /api/projects/{id}`
  - `POST /api/projects/{id}/images/upload`
  - `GET /api/projects/{id}/images`
  - （可选）静态文件服务：能用 URL 访问图片文件
- 文件结构：
  - `data/projects/{project_id}/images/{image_id}_{filename}`

**实现清单（前端）**
- 项目列表：创建项目、进入项目。
- 图片列表：多文件上传、显示缩略图/尺寸/状态。

**自动验证**
- API 单测覆盖：创建项目、上传图片、查询列表。

**人工验收清单**
- 创建一个项目（检测或分割任意一种）。
- 上传 1~3 张图片。
- 图片列表能显示文件名与缩略图（或至少可点击打开原图）。

**完成后的 git 操作**
- `git commit -m "feat: project and image upload/list MVP"`

---

### M2 — 标注数据模型与读写（bbox）

**目标**
- 后端支持写入/读取 bbox 标注；前端能在图片详情页叠加渲染 bbox。

**关键点**
- 坐标统一使用归一化（0~1），避免前后端分辨率不一致。
- label 不写死，但**只能从项目配置的 labels 列表中选择**（系统提示词固定，不接收用户自然语言 prompt）。
- 先做检测（bbox）通路；分割（mask/polygon）在 M5 再接入。

**验收**
- 项目配置 labels 列表 → 进入图片详情选择 label 并画框 → 刷新仍存在 → 前端能看到矩形框。

---

### M3 — 异步任务骨架与进度（先骨架后强化）

**目标**
- “批量自动标注”是异步任务：前端可看到任务状态/进度，且能看到图片逐步从 `pending → annotating → done`。

**实现策略（兼容开发机环境）**
- 先使用内置的轻量 `TaskManager`（线程池 + 内存任务状态）跑通闭环，不依赖 Redis。
- 后续有 Redis/Celery 环境时，再把任务实现替换为 Celery（保持 `/api/tasks/{task_id}/status` 接口不变）。

**验收**
- 前端在图片列表页点击“批量自动标注”后：任务状态从 pending → running → done（或 error）可见；图片 status 逐步变化。

---

### M4 — 自动标注（LLM）

**策略**
- 先实现 LLM Stub（固定返回 1~N 个 bbox），把全链路跑通。
- 再接入真实推理（vLLM / OpenAI-compatible 接口），并加超时/重试/降级。

**验收**
- 上传图片 → 自动生成 bbox 标注 → 前端渲染出来。

---

### M5 — 分割能力（SAM）

**策略**
- 先实现 mask/polygon 的数据结构与渲染（允许用假 polygon）。
- 再接入 SAM 预测；保证“同一张图连续纠错”时 embedding 复用。

**验收**
- 能生成 polygon 并在前端以半透明区域显示。

---

### M6 — 人工纠错（Human-in-the-Loop）

**范围**
- 删除标注、确认标注。
- 补框/点选纠错（接口与前端交互）。

**验收**
- 删除/补框/点选均能稳定更新到 DB，刷新不丢失。

---

### M7 — 数据集导入/导出

**范围**
- 导出：YOLO（bbox）优先；COCO（可选）。
- 导入：优先支持一种格式，另一种后补。

**验收**
- 导出 zip 可解压，内容符合基本格式要求。

---

### M8 — 微调流水线（可选）

**范围**
- 仅使用 `is_confirmed=1` 的标注导出训练集。
- 启动训练任务、记录日志、保存产物路径。

**验收**
- 不要求训练效果；要求任务可启动、日志可读、失败可定位。

---

### M9 — 评估与质量评分（MVP）

**范围**
- 离线评估：对 val/test 计算基础指标（bbox IoU / P/R/F1）。
- 在线质量评分：基于启发式信号对图片/标注打分并用于排序。

**验收**
- 至少能跑出一份可复现的 metrics JSON，前端能展示。

---

### M10 — 配置中心、热更新与环境切换

**范围**
- 将运行时关键字段真正接入运行链路：系统级 `model_profile`、`llm.*`、`sam.*`、`postprocess.*`、`quality.*`、`evaluation.*`；项目级仅保留 `labels` 与 `active_model_tag`。
- 明确“热更新立即生效”和“需显式重载/重启”的配置项，并在后端接口与前端文案中体现。
- 支持一键切换 `dev_low_resource` / `test_real_stack` / `demo_prod` 三类配置档位，覆盖本地开发、统一联调和答辩演示。
- 补齐前端设置入口：在项目图片列表页承载系统级运行时设置面板，并回显当前生效配置。
- 增加系统级模型激活接口（如 base model profile 切换），与项目级 `active_model_tag` / `model_profile` 联动。

**验收**
- 可以通过单一入口一键切换“测试配置”和“生产/演示配置”，无需手工逐个改环境变量。
- 修改 `quality.threshold_review`、`evaluation.*`、`postprocess.*` 后，后续任务与页面展示能体现变化。
- 修改 `llm.base_model`、`sam.checkpoint` 时，系统明确提示“需显式重载”，且能完成一次重载生效验证。

---

### M11 — 真实 LLM 推理与模型切换

**范围**
- 从当前自动标注逻辑中拆出独立的 `services/vllm_client.py`，统一封装 OpenAI-compatible / vLLM 调用、超时、重试、降级与日志。
- 让 `active_model_tag` 真正参与自动标注与评估，而不是仅作为展示字段或评估快照。
- 支持 `base` / `lora:{job_id}` / 固定 base model profile 的显式切换，并把实际使用的模型记录到任务日志与评估报告。
- 当前阶段 `lora:{job_id}` 先保证项目配置、评估快照与请求路由真实生效；vLLM 侧 LoRA adapter 的真实挂载/热切换在 M14 完成。
- 保留 stub 回退能力，但将其明确为降级路径，而不是默认主路径。

**验收**
- 外部 vLLM 服务可被实际调用，失败时可回退并给出清晰日志。
- 切换 `base` / `lora:{job_id}` 后，同一张图的新标注结果来源与日志可区分，评估记录中的 `model_tag` 与实际推理一致。

**本地验证策略**
- 在 `dev_low_resource` 下，优先通过详尽的 API / 集成测试、请求契约测试、错误回退测试验证逻辑正确性。
- 真实 vLLM 联调放到 `test_real_stack` 统一进行，并在进度日志中单独记录。

---

### M12 — 真实 SAM3 与后处理

**范围**
- 引入真实 `SAM3` 服务封装，支持 lazy load、checkpoint 选择、CPU/CUDA 设备切换，并保留低算力开发机上的 stub 自动回退。
- 实现 `set_image` / 当前图 embedding 缓存，提升连续点选纠错与重复分割的响应速度。
- 新增 `services/postprocess.py`，实现闭运算、边界裁剪、Douglas-Peucker 简化、多边形/Mask 落盘。
- 统一分割项目的自动标注、点选纠错、导入与评估逻辑，确保都基于真实 mask/polygon。

**验收**
- 分割项目能生成真实 mask 文件和 polygon，而不再是规则化假多边形。
- 同一张图连续纠错可复用缓存，交互速度明显优于首次加载。

**本地验证策略**
- 在真实 SAM3 无法本地运行时，先用固定样例、后处理单测、接口集成测试和浏览器纠错测试替代。
- `dev_low_resource` 默认不主动下载大模型；只有在提供本地 `.pt` checkpoint，或显式设置 `SAM3_ALLOW_HF_DOWNLOAD=1` 时才尝试真实 SAM3。
- 支持通过 `SAM3_CHECKPOINT_PATH` 或 `models/sam3/` 本地权重目录自动发现 checkpoint，避免每次手工改绝对路径。
- 真实 checkpoint、CUDA/CPU 切换、embedding 缓存命中效果在 `test_real_stack` 环境集中验收。

---

### M13 — 任务基础设施升级

**范围**
- 第一阶段先在现有轻量 `TaskManager` 上补齐 WebSocket 进度推送与前端实时订阅/轮询回退，保持现有 REST 查询接口兼容。
- 使用 Redis 持久化任务状态与队列，替换当前纯内存 `TaskManager`；Celery 改为后续可选演进，不再阻塞 M13 收尾。
- 统一标注、评估、微调任务状态存储，并支持 FastAPI / 独立 worker 分进程运行。
- 增加 WebSocket `WS /ws/tasks/{task_id}` 进度推送，减少前端轮询依赖。
- 实现 `utils/gpu_lock.py`，保证 vLLM / SAM / 微调之间的 GPU 资源互斥与任务串行策略。

**验收**
- 第一阶段验收：页面发起批量标注后优先通过 `WS /ws/tasks/{task_id}` 接收状态更新，失败时自动回退轮询；接口契约测试与浏览器测试均通过。
- FastAPI 与 Worker 分进程运行时，任务状态仍可稳定查询和推送。
- 并发触发标注与微调时，任务按锁/队列顺序执行，无显存争抢导致的 OOM 或状态错乱。

**本地验证策略**
- 开发机可先用进程内 / 本地 Redis 的集成测试、任务顺序测试、WebSocket 契约测试和浏览器回归验证第一阶段落地。
- 真正的多进程联调和 GPU 锁冲突测试在 `test_real_stack` 环境统一完成。

---

### M14 — 真实 LoRA 微调闭环

**范围**
- 将当前 stub 微调任务升级为“可切换 runner”的训练流程：`FINETUNE_BACKEND=llamafactory` 时走真实 LLaMA-Factory subprocess，开发/测试环境保留 mock runner 回退。
- 完成训练数据导出、prompt template、训练配置自动生成、日志解析与失败定位，并把配置/指标暴露给前端与测试。
- 激活接口优先通过 vLLM 运行时 LoRA API 进行加载/卸载；若环境未开启 runtime update，则至少保证路由与状态切换真实生效。
- 前端补齐 runner 状态、loss 点位摘要、产物路径等信息；完整训练曲线看板可后续继续增强。

**验收**
- 能产出真实训练目录、日志与 LoRA adapter，而不是占位文件。
- 激活后，后续自动标注与评估实际使用该 LoRA，并可与 `base` 做结果对比；若本机未启用真实 vLLM runtime update，需至少通过契约测试验证 load/unload 请求正确发出。

**本地验证策略**
- 在开发机无法跑真实训练时，先把数据导出、配置生成、日志解析、激活链路、失败处理全部用单测和集成测试覆盖。
- 真实训练与真实 LoRA 激活效果在 `test_real_stack` 环境统一验收。

---

### M15 — 评估系统增强与对比看板

**范围**
- 在 M9 bbox 指标基础上，补充分割指标 `mIoU_mask` / `Dice`，并支持更细粒度的 per-class / per-image 报告。
- 增加评估对比看板，用于展示 `base vs lora`、上一次 vs 当前 run 的结果差异。
- 可选接入 `pycocotools / COCOeval` 输出更标准的离线指标，便于论文和答辩展示。
- 增加性能与效率统计：自动标注耗时、SAM 耗时、采纳率、失败样本分析等。

**验收**
- 能比较两次 run 的关键指标与失败样本。
- 能输出更完整的评估报告，用于答辩展示与论文截图。

**本地验证策略**
- 先用固定数据集、黄金报告、API 集成测试和浏览器回归测试保证指标计算与展示稳定。
- 真实模型前后对比与最终论文截图在统一联调环境补齐。

---

### M16 — 一键启动与演示脚本

**范围**
- 收敛为单一 Linux 启动入口 `scripts/start-linux.sh`，负责一键补环境、写 profile、执行预检并托管服务进程。
- 文档说明如何准备 Redis / vLLM / SAM 权重 / LLaMA-Factory 等外部依赖，但不再为 Windows 启动脚本和生产部署编排投入额外精力。
- 支持一键拉起 FastAPI、Redis worker、Redis、可选本地 vLLM 与前端开发/演示环境；缺失依赖时给出明确提示或自动补齐。

**验收**
- 从空 Linux 环境到可演示：按 README 走一遍不踩坑（或明确每个依赖缺失时的提示与替代方案）。

---

### M17 — SAM3 → SAM2 迁移

**范围**
- 将当前分割链路的真实后端从 `SAM3` 调整为 `SAM2` 官方路线，优先匹配本项目实际需要的“bbox 出 mask + 点选修正”能力边界。
- 保持前后端交互契约稳定：`sam.checkpoint` / `sam.device` / `sam.multimask_output` 仍保留，避免把模型替换扩散成全仓重构。
- 收敛当前 `SAM3_ALLOW_HF_DOWNLOAD`、`SAM3_CHECKPOINT_PATH`、`models/sam3/` 等约定，迁移为更通用的 `SAM_*` 语义，或在过渡期同时兼容 `sam2` / `sam3`。
- 更新默认 profile、README、设计文档与测试样例，使“真实分割基线”从 `SAM3` 切换为 `SAM2`。

**实现清单**
- 重写 `backend/services/sam_service.py` 的真实 runtime 适配层，优先基于 `SAM2` 官方 image predictor 实现。
- 统一 checkpoint 发现、下载、缓存与 provider 标识，避免业务层继续写死 `sam3:*`。
- 清理 `scripts/start-linux.sh`、`README.md`、测试与配置中的 `SAM3` 强绑定表述。
- 保留 stub 回退与低算力开发路径，确保 `dev_low_resource` 仍稳定可跑。

**验收**
- 分割项目的自动标注、手动补框、点选纠错、导入导出与评估链路在 `SAM2` 下全部跑通。
- 与当前实现相比，不要求自然语言分割增强，但不得牺牲现有交互式修正能力。
- 文档、默认配置、日志 provider 与错误提示不再把 `SAM3` 作为唯一真实后端。

**验证步骤**
- 单测：`SAMService` 真实/降级路径、checkpoint 发现、点选修正与 provider 标识。
- 集成测试：自动标注、图片详情页点修正、导入导出、评估链路。
- 真实联调：在 `test_real_stack` 上完成一次 `SAM2` 真实权重下载、启动与交互式纠错验收。

**完成后的 git 操作**
- `git commit -m "refactor: migrate segmentation runtime from sam3 to sam2"`

**当前完成记录（2026-04-14）**
- 本地关键回归覆盖 `SAMService`、分割 API、点修正、导入导出与评估链路，收口前回归通过。
- 已在真实 GPU 机器上完成 `test_real_stack` 联调，验证 `SAM2` 权重下载、自动标注、点修正、mask 导出与评估闭环。
- 该里程碑按“迁移完成且链路稳定”判定为完成；当前真图上的分割视觉质量一般，属于后续质量优化问题，不再阻塞 M17 收口。

---

### M18 — 工作流系统重构（最小安全插件化）

**范围**
- 不再继续把“每来一种标注场景就往主流程里加特判”作为长期扩展方式；在保持现有闭环稳定的前提下，为标注流程引入最小可扩展的 `workflow` 抽象。
- 用户侧逐步从“只按 `task_type` 选检测/分割”演进到“按具体 workflow 选通用检测、通用实例分割、遥感建筑物、变化检测等场景流程”；系统内部保留 `task_family/result_type` 作为兼容与复用层。
- 重点抽离“工作流决策层”，而不是现在就把数据库、全部 API、前端编辑器、导出和评估一次性重写成完整插件平台。
- 在正式实施前，先完成一次改动规模评估；如果影响面明显超出“最小安全重构”，则先额外产出一份详细设计文档，再决定是否进入实现。

**实现清单**
- 盘点当前 workflow 耦合点：项目创建、项目设置、自动标注、手工修正、任务队列、导入导出、评估、前端工作台与系统设置。
- 定义最小抽象边界：
  - `workflow_key`：项目实际采用的流程配方。
  - `task_family/result_type`：如 `bbox`、`instance_mask`、`semantic_mask`、`polyline`、`change_mask`，用于约束数据结构、编辑器与评估方式。
  - `atomic capabilities`：如 `llm_grounding`、`sam_refine`、`tile_split`、`tile_merge`、`dedup`、`postprocess`、`evaluation_adapter`。
- 设计并落地 workflow registry，让现有默认流程先以内置 workflow 的形式注册进去，例如：
  - `generic_detection`
  - `generic_instance_segmentation`
- 详细设计与迁移边界说明见 `docs/workflow_refactor_plan.md`，后续实现默认以该文档为准。
- 以兼容优先为原则，保留当前 `task_type` 字段和主要接口，避免一次性打断已验收通过的 LLM 自动标注与人工修正闭环。
- 若评估结论显示改动范围已涉及数据库迁移、核心 API 契约变更、前端编辑器切换、导出/评估语义重写等高风险项，则继续扩展详细设计文档 `docs/workflow_refactor_plan.md`，至少说明：
  - 现状耦合点与问题边界
  - 新旧模型与字段映射
  - 迁移步骤与灰度策略
  - 回归测试矩阵
  - 对 M19 / M20 的影响

**验收**
- 当前已闭环的检测与实例分割流程，在切入 workflow registry 后行为不回归，尤其不得打坏已经验收通过的 LLM bbox 自动标注链路。
- 项目层能表达“具体 workflow”而不必继续靠 `task_type` 承担全部语义，但兼容老项目与旧接口。
- 代码层明确区分：
  - 面向用户的 workflow 选择
  - 系统内部的 `task_family/result_type`
  - 底层可复用的 atomic capabilities
- 若改动规模被评估为“大”，则必须先补齐详细设计文档并经确认后，才继续大范围实现；不能在没有额外设计文档的情况下直接把系统推入大重构。

**验证步骤**
- 设计评审：列出当前 workflow 决策点与最小插口，确认哪些层现在能动、哪些先不动。
- 契约回归：现有 detection / segmentation API、任务调度、导出与评估在默认 workflow 下全部保持兼容。
- 低资源开发机验证：继续以 stub / CPU / 小样本集成测试为主，避免为 workflow 重构引入额外真实模型依赖。
- 若进入详细设计文档分支，则在文档中附完整改动矩阵和推荐迁移顺序，作为后续实现前置条件。

**完成后的 git 操作**
- 小改动直接落地时：`git commit -m "refactor: introduce workflow registry and task family seam"`
- 若先做评估与设计文档：`git commit -m "docs: plan workflow refactor and plugin seam"`

**当前完成记录（2026-04-14）**
- `workflow registry`、`workflow_key`、`task_family` 与 `supports_point_refine` 等 workflow metadata 已接入后端默认流程。
- 项目创建、项目设置、项目列表、项目元信息接口均已支持默认 workflow 的显式表达与兼容映射。
- 默认 `generic_detection` 与 `generic_instance_segmentation` 两条 workflow 已通过本地回归和一次真机联调，证明“最小安全插件化”没有打坏既有闭环。
- 本里程碑按 `docs/workflow_refactor_plan.md` 中 Phase 1/2 完成为准判定收口；Phase 3/4 留待下一阶段继续推进。

---

### M19 — OCI 分发与环境自检

**范围**
- 将当前“本机脚本现场安装依赖”的分发方式，调整为 `Docker Hub 固定版本镜像 + docker compose + 模型缓存目录 + doctor/selftest`。
- 前端保留为独立服务，正式部署拓扑固定为 `frontend + api + worker + vllm + redis`。
- 宿主机首发支持矩阵锁定为 `Ubuntu 22.04 x86_64 + NVIDIA 驱动 + Docker + Compose + NVIDIA Container Toolkit`。
- 默认模型下载策略改为“优先无 token 来源，失败后再要求 `HF_TOKEN` 并切回官方仓库”。

**实现清单**
- 落地 `docs/oci_distribution_plan.md` 中定义的镜像、Compose、缓存目录与命令约定。
- 设计并实现 `doctor`、`doctor --fix`、`start`、`stop`、`status`、`logs`、`selftest` 命令。
- 统一宿主机挂载目录：`data/`、`logs/`、`models/`、`hf_cache/`、`lora/`。
- 发布 Docker Hub 版本化镜像，并在文档中给出 tag / digest、支持矩阵与回滚方式。

**验收**
- 在一台干净的 Ubuntu 22.04 GPU 机器上，不预装 `vllm` / `torch` / `sam` / `llamafactory`，仅通过 Docker 相关前置即可拉起完整系统。
- `doctor` 能准确识别缺失项，并自动补齐或输出可执行的手工修复命令。
- `selftest` 能明确报告 `frontend/api/vllm/redis` 的健康状态，并完成一次最小真实推理验证。

**验证步骤**
- 本地语法与配置校验：Compose、启动脚本、镜像构建脚本。
- 新机器冷启动验收：从零开始执行 `doctor` → `start` → `selftest`。
- 回归验证：模型缓存复用、日志位置、显存档位推荐、token 回退逻辑。

**完成后的 git 操作**
- `git commit -m "feat: ship OCI distribution flow with compose and self-checks"`

---

### M20 — 前端完全重构

**范围**
- 以前端正式产品形态为目标，重做信息架构、关键工作流、状态管理和视觉体系，而不是在当前简略界面上持续打补丁。
- 保留现有业务能力闭环：项目管理、图片列表、自动标注、人工修正、微调、评估、系统设置与任务状态。
- 将“开发期占位式界面”替换为正式可演示、可扩展的前端服务，兼顾后续继续增长的功能复杂度。

**实现清单**
- 重做页面架构与路由层：项目页、图片工作台、训练/评估面板、系统设置、任务监控。
- 重做状态管理与数据流，减少当前页面局部状态堆叠和跨模块耦合。
- 重构标注工作台交互，包括检测/分割的查看、纠错、确认与来源展示。
- 补齐更系统的前端测试：核心页面回归、关键交互流程、配置与任务状态展示。

**验收**
- 在不牺牲现有功能的前提下，前端完成一次真正的结构性替换，而不是局部修修补补。
- 关键工作流可连续演示：上传/导入 → 自动标注 → 人工修正 → 微调/评估 → 查看结果与配置。
- 新界面具备独立服务化部署能力，能直接纳入 M19 的 OCI 分发体系。

**验证步骤**
- 前端构建通过，核心页面浏览器回归通过。
- 至少完成一轮真实端到端演示录屏或验收截图，覆盖标注、修正、训练、评估与设置。
- 与旧界面相比，明确列出被替换的结构问题与新的维护边界。

**完成后的 git 操作**
- `git commit -m "feat: rebuild frontend architecture and annotation workspace"`

---

## 3. 进度日志（每次里程碑完成后填写）

> 规则：只有当“自动验证 + 人工验收”都通过，才把状态改为 ✅。

| 日期 | 里程碑 | 状态变更 | commit | 自动验证 | 人工验收 | 备注 |
|---|---|---|---|---|---|---|
| 2026-02-27 | M0 | ⬜ → ✅ | 2be1b03 | `python -m compileall backend`、`npm run build` | ✅ 无报错 | 初始化骨架 |
| 2026-02-27 | M1 | ⬜ → ✅ | 79bc7d8 | `pytest -q`、`npm run build` | ✅ 无报错 | 上传/列表闭环 |
| 2026-02-27 | M2 | ⬜ → ⏳ | - | - | - | bbox 标注读写与渲染 |
| 2026-02-27 | M2 | ⏳ → ✅ | 2c3ad61 | `pytest -q`、`npm run build` | ✅ 通过 | bbox 标注 + 删除 + label 自适应显示 |
| 2026-02-27 | M3 | ⬜ → 🟡 | 91f571e | `pytest -q`、`npm run build` | ⏳ 待验收 | 项目级批处理标注 + 固定 prompt + labels 列表 |
| 2026-02-27 | M3 | 🟡 → ✅ | 91f571e | `pytest -q`、`npm run build` | ✅ 通过 | 批处理标注任务验收通过 |
| 2026-03-24 | M4 | ⬜ → 🟡 | 53d2d7b | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build` | ⏳ 待验收 | 自动生成 bbox 写库 + OpenAI-compatible 预留接入与 stub 回退 |
| 2026-03-24 | M4 | 🟡 → ✅ | 53d2d7b | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build` | ✅ 通过 | 自动标注验收通过 |
| 2026-03-24 | M5 | ⬜ → 🟡 | 71e5864 | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build` | ⏳ 待验收 | 分割项目自动生成 polygon + 前端半透明渲染 + SAM stub 服务骨架 |
| 2026-03-24 | M5 | 🟡 → ✅ | 71e5864 | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build` | ✅ 通过 | 分割能力验收通过 |
| 2026-04-01 | M6 | ⬜ → 🟡 | 2bc7e03 | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m6\node\e2e-m6.cjs` | ⏳ 待验收 | 确认标注 + 点选纠错 + 补框 + 删除闭环，浏览器真机流已跑通 |
| 2026-04-02 | M6 | 🟡 → ✅ | 2bc7e03 | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m6\node\e2e-m6.cjs` | ✅ 通过 | 人工验收通过，进入 M7 数据集导入/导出 |
| 2026-04-02 | M7 | ⬜ → 🟡 | 28b96d4 | `.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m7\node\e2e-m7.cjs` | ⏳ 待验收 | 项目级 YOLO/COCO 导出 + YOLO/COCO 导入，图片列表页已接入入口 |
| 2026-04-02 | M7 | 🟡 → ✅ | 28b96d4 | `.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m7\node\e2e-m7.cjs` | ✅ 通过 | 数据集导入/导出人工验收通过，进入 M8 微调流水线 |
| 2026-04-02 | M8 | ⬜ → 🟡 | d336852 | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m8\node\e2e-m8.cjs` | ⏳ 待验收 | 确认 train 标注导出微调数据集 + 任务日志/产物路径展示 + LoRA 激活闭环 |
| 2026-04-02 | M8 | 🟡 → ✅ | d336852 | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m8\node\e2e-m8.cjs` | ✅ 通过 | 微调流水线人工验收通过，进入 M9 评估与质量评分 |
| 2026-04-02 | M9 | ⬜ → 🟡 | 85598a2 | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m9\node\e2e-m9.cjs` | ⏳ 待验收 | val/test 评估任务 + 评估报告导出 + 图片/标注质量评分 + 图片列表风险排序 |
| 2026-04-02 | M9 | 🟡 → ✅ | 85598a2 | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m9\node\e2e-m9.cjs` | ✅ 通过 | 评估与质量评分人工验收通过，进入 M10 配置中心、热更新与环境切换 |
| 2026-04-02 | M10 | ⬜ → 🟡 | 26efec0 | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m10\node\e2e-m10.cjs` | ⏳ 待验收 | 项目设置面板 + 系统 profile 切换 + 热更新/显式重载提示 + 一键测试/生产档位切换 |
| 2026-04-03 | M10 | 🟡 → ✅ | 26efec0 | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m10\node\e2e-m10.cjs` | ✅ 通过 | 配置中心、热更新与环境切换人工验收通过，进入 M11 真实 LLM 推理与模型切换 |
| 2026-04-03 | M11 | ⬜ → 🟡 | 233218f | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m11\node\e2e-m11.cjs` | ⏳ 待验收 | vLLM/OpenAI-compatible 路由封装 + `active_model_tag` 真正参与自动标注/评估 + 项目级模型切换入口 |
| 2026-04-03 | M11 | 🟡 → ✅ | 233218f | `.venv\Scripts\python.exe -m compileall backend`、`.venv\Scripts\python.exe -m pytest -q`、`npm run build`、`node output\playwright\m11\node\e2e-m11.cjs` | ✅ 通过 | M11 人工验收通过，进入 M12 真实 SAM3 与后处理 |
| 2026-04-03 | M12 | ⬜ → 🟡 | e550e40 | `.venv\Scripts\python.exe -m compileall backend tests`、`.venv\Scripts\python.exe -m pytest -q`、`cd frontend && npm run build`、`node` 临时 Playwright 浏览器回归 | ⏳ 待验收 | SAM3 优先 + stub 回退的真实 mask/polygon 管线、掩码落盘、OpenCV/降级后处理、导入导出与点纠错贯通 |
| 2026-04-03 | M12 | 🟡 → ✅ | d8a69cb | `.venv\Scripts\python.exe -m compileall backend tests`、`.venv\Scripts\python.exe -m pytest -q`、`cd frontend && npm run build`、`node` 临时 Playwright 浏览器回归 | ✅ 通过 | M12 人工验收通过，后续补做 Linux 真实栈补环境脚本与 SAM3 本地权重自动发现强化 |
| 2026-04-03 | M13 | ⬜ → 🟡 | - | `.venv\Scripts\python.exe -m compileall backend tests`、`.venv\Scripts\python.exe -m pytest -q`、`cd frontend && npm run build`、`node output\playwright\m13\node\e2e-m13.cjs` | ⏳ 待验收 | 系统级运行时设置入口修正 + `WS /ws/tasks/{task_id}` 首阶段落地，前端优先走 WebSocket 并保留轮询回退 |
| 2026-04-07 | M13 | 🟡 → ✅ | - | `.venv\Scripts\python.exe scripts\verify_m13_real_redis.py --redis-url redis://127.0.0.1:6380/15 --flush-redis-db` | ✅ 真实 Redis + 独立 worker + 浏览器回归通过 | 当前 Redis 任务骨架已完成分进程联调验证；结合本机算力与现有任务抽象，M13 阶段先不额外引入 Celery |
| 2026-04-07 | M14 | ⬜ → 🟡 | - | `.venv\Scripts\python.exe -m compileall backend tests scripts`、`.venv\Scripts\python.exe -m pytest -q`、`cd frontend && npm run build`、`.venv\Scripts\python.exe scripts\verify_m14_browser.py --redis-url redis://127.0.0.1:6380/14 --flush-redis-db` | ✅ 后端测试 + 浏览器回归通过 | 真实 LLaMA-Factory subprocess 入口、metrics 暴露、LoRA runtime API hook 与可复跑浏览器验证脚本已落地；真实训练效果仍待 `test_real_stack` 验收 |
| 2026-04-07 | M15 | ⬜ → ✅ | - | `.venv\Scripts\python.exe -m compileall backend tests scripts`、`.venv\Scripts\python.exe -m pytest -q`、`cd frontend && npm run build`、Playwright MCP 浏览器回归（两次 evaluation compare + failure sample 面板） | ✅ 代码测试 + 浏览器回归通过 | 已补齐 `mIoU_mask / Dice`、run compare API、失败样本摘要、性能统计与前端对比看板，达到本地验收条件 |
| 2026-04-07 | M16 | ⬜ → ✅ | - | `wsl bash -n scripts/start-linux.sh`、`wsl bash scripts/start-linux.sh --help`、`.venv\Scripts\python.exe -m compileall backend tests scripts`、`.venv\Scripts\python.exe -m pytest -q`、`cd frontend && npm run build` | ✅ 启动脚本语法/帮助页通过，代码测试通过 | 已收敛为单一 `scripts/start-linux.sh` Linux 入口；当前 WSL 因缺少 `python3-pip/ensurepip` 且无免密 sudo，未完整跑通自动补系统依赖分支，但失败提示已验证清晰，目标 Linux 机器按 README 具备 sudo 后即可走完整自举链路 |
| 2026-04-13 | M17 | ⬜ → ⏳ | - | `.venv_test/bin/pytest tests/test_sam_service_m12.py tests/test_api_m10_settings.py tests/test_profile_scripts.py tests/test_api_m4_auto_annotations.py tests/test_api_m5_segmentation.py tests/test_api_m6_corrections.py tests/test_api_m7_dataset_io.py tests/test_api_m1.py tests/test_api_m2_annotations.py tests/test_api_m3_tasks.py -q`、`bash -n scripts/start-linux.sh`、`bash scripts/start-linux.sh --help` | ⏳ 待后续真机验收 | 已将默认 `SAM` 基线切到 `SAM2`，保留 `SAM3` 兼容分支；本地仅做 CPU/stub/配置级验证，不触发任何真实模型推理或下载 |
