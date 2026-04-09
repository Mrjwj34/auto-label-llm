# OCI 分发方案（实施基线）

> 状态：方案已确认，待当前仓库问题收敛后实施  
> 目标：在 **Ubuntu 干净系统 + 已安装 NVIDIA 驱动** 的前提下，实现尽量接近“一键启动”的交付体验

## 1. 目标与边界

本方案用于替代当前“启动脚本现场安装大量 AI 依赖”的做法，收敛为：

- 固定版本 OCI 镜像负责应用运行时
- `docker compose` 负责服务编排
- 启动脚本负责环境检查、模型准备、健康检查与用户入口
- 模型与数据走宿主机挂载目录，不放入主应用镜像

本方案的目标不是“任意 Linux 发行版完全零前置”，而是在正式支持矩阵内把复杂度压到最低。

### 1.1 首发支持矩阵

- 宿主机系统：`Ubuntu 22.04 x86_64`
- GPU：NVIDIA，显存档位为 `16G / 24G / 32G+`
- 宿主机必须具备：
  - 可用 NVIDIA 驱动
  - Docker Engine
  - Docker Compose Plugin
  - NVIDIA Container Toolkit

超出以上矩阵时，启动脚本应直接提示“不在正式支持范围”，而不是继续猜环境。

### 1.2 不做的事

- 不把模型权重打进 OCI 主镜像
- 不把前端退化成“后端顺手托管静态文件”
- 不把启动脚本继续做成万能安装器
- 不默认要求用户手动安装 `vllm`、`torch`、`sam3`、`llamafactory`

## 2. 交付物

首版交付物固定为以下几项：

1. 固定版本 Docker Hub 镜像
2. `docker-compose.yml`
3. 启动脚本 / CLI 包装层
4. 模型下载脚本
5. 健康检查与自检命令

### 2.1 镜像发布策略

镜像仓库：`Docker Hub`

镜像要求：

- 使用明确版本号，不使用 `latest` 作为正式发布入口
- 发布文档同时给出 tag 和 digest
- GPU 相关镜像基于稳定的 `nvidia/cuda` Ubuntu 22.04 runtime 系列构建
- 不追“最新 CUDA”，优先选择已经被项目验证通过的固定 tag

### 2.2 建议镜像拆分

为兼顾稳定性和后续演进，首版采用“两类自维护镜像 + 一个官方依赖镜像”的结构：

- `autolabel-runtime:<version>`
  - 复用于 `api`、`worker`、`vllm`
  - 内含固定版本 Python 运行时、后端代码、`torch`、`vllm`、`llamafactory`、`sam3` 等依赖
- `autolabel-frontend:<version>`
  - 独立前端服务
  - 提供生产构建后的前端资源
  - 不使用 Vite dev server 作为生产形态
- `redis:7-alpine`
  - 直接使用官方镜像

说明：

- 前端仍然保留为正式服务，这一点是架构要求，不因当前界面较简陋而取消。
- `api`、`worker`、`vllm` 首版优先复用同一运行时镜像，通过不同 entrypoint 区分职责，减少镜像维护面。

## 3. 服务拓扑

`docker compose` 作为真实编排源，首版服务拓扑如下：

- `frontend`
- `api`
- `worker`
- `vllm`
- `redis`

职责说明：

- `frontend`：独立前端服务，对外提供 UI
- `api`：FastAPI 主进程，提供 REST / WebSocket / 配置接口
- `worker`：异步任务消费，处理自动标注、评估、微调
- `vllm`：本地模型推理服务，提供 OpenAI-compatible 接口
- `redis`：任务队列与状态存储

## 4. 模型与缓存策略

### 4.1 总原则

- OCI 主镜像不携带模型权重
- 模型下载与缓存走宿主机挂载目录
- 默认优先使用**不要求 token 的源**
- 默认源失败后，再要求用户提供 `HF_TOKEN` 并回退到官方仓库

### 4.2 默认模型来源

- Qwen / 其他公开模型：
  - 默认直接使用公开官方源
  - 无 token 时先尝试公开下载
  - 若官方源限流、需要鉴权或镜像源失败，再要求用户设置 `HF_TOKEN`
- SAM3：
  - 默认权重源：`1038lab/sam3`
  - 若默认源不可用或下载失败，再要求用户提供 `HF_TOKEN` 并切换到官方仓库

说明：

- `1038lab/sam3` 在本方案中定义为“默认权重来源”，不是完整运行时镜像。
- 运行时所需的 `sam3` Python 依赖、推理环境和附加资产由应用 OCI 镜像负责。

### 4.3 宿主机目录约定

宿主机统一挂载以下目录：

- `data/`
- `logs/`
- `models/`
- `hf_cache/`
- `lora/`

建议默认映射为：

```text
~/.auto-label-llm/data
~/.auto-label-llm/logs
~/.auto-label-llm/models
~/.auto-label-llm/hf-cache
~/.auto-label-llm/lora
```

其中：

- `models/`：基础模型、SAM 权重、本地导入模型
- `hf_cache/`：Hugging Face 缓存目录
- `lora/`：训练产出的 LoRA 与导出工件
- `data/`：SQLite、项目文件、任务输出
- `logs/`：容器日志、启动日志、自检日志

## 5. 显存档位策略

正式支持以下三档：

- `16G`
- `24G`
- `32G+`

运行策略：

- 启动脚本先自动识别 GPU 显存并给出推荐档位
- 用户可以手动覆盖档位选择
- 若用户强制选择明显超出硬件能力的档位，脚本需要明确警告，必要时拒绝启动

档位的主要区别体现在：

- 默认模型规格
- `vllm` 上下文长度
- `gpu_memory_utilization`
- batch / seq 相关参数
- 是否默认启用更重的功能组合

正式实现时，档位差异优先通过 profile 配置表达，而不是通过拆更多镜像表达。

## 6. 启动脚本职责

启动脚本不再负责大规模现场安装 AI 依赖，职责收敛为：

- 宿主环境检查
- 可控范围内的基础依赖补齐
- 模型下载与缓存检查
- `docker compose` 生命周期管理
- 健康检查与自检
- 输出访问地址、日志路径和失败提示

### 6.1 `doctor`

`doctor` 只检查，不启动服务。至少检查：

- Ubuntu 版本是否受支持
- Docker 是否安装
- Docker Compose Plugin 是否可用
- NVIDIA Container Toolkit 是否安装
- Docker 是否能看到 GPU
- `nvidia-smi` 是否可用
- 端口是否冲突
- 挂载目录是否存在且可写
- 磁盘剩余空间是否足够

### 6.2 `doctor --fix`

`doctor --fix` 只做低风险自动补齐，当前仅针对 Ubuntu 主路径：

- 安装 Docker
- 安装 Docker Compose Plugin
- 安装 NVIDIA Container Toolkit
- 创建默认缓存目录

无法自动补齐时，脚本必须输出明确的手工命令和后续验证命令。

### 6.3 `start`

`start` 的标准流程：

1. 运行 `doctor`
2. 确认或选择 `16G / 24G / 32G+` 档位
3. 检查镜像版本与本地缓存
4. 检查模型是否已缓存
5. 缺模型时执行模型下载
6. 调用 `docker compose up -d`
7. 执行健康检查
8. 输出访问地址、日志路径、当前档位与模型来源

### 6.4 其他命令

建议同时提供：

- `stop`
- `restart`
- `status`
- `logs`
- `selftest`
- `models pull`
- `models status`

## 7. 健康检查与自检

### 7.1 健康检查

`docker compose` 层要配置基础 healthcheck，至少覆盖：

- `frontend`
- `api`
- `vllm`
- `redis`

### 7.2 自检

`selftest` 作为启动后的功能验证命令，至少覆盖：

- API 健康接口
- Redis 连通性
- vLLM 模型接口
- 一次最小真实推理
- 一次最小任务链路验证

`selftest` 失败时应给出明确失败组件，而不是只返回“启动失败”。

## 8. 配置与版本管理

### 8.1 配置来源

配置优先级建议为：

1. 用户显式传入的 CLI 参数
2. profile 配置
3. `.env`
4. 镜像内默认值

### 8.2 版本约束

正式发布时需要固定：

- 应用版本
- OCI 镜像 tag / digest
- CUDA 基础镜像 tag
- `torch`
- `vllm`
- `llamafactory`
- `sam3`
- 前端构建产物版本

## 9. 实施顺序

本方案不会立即落地，实施顺序固定为：

1. 先继续修完当前仓库中的已知问题
2. 收敛现有启动脚本职责
3. 整理镜像边界与 Compose 拓扑
4. 落地模型缓存与下载脚本
5. 落地 `doctor` / `selftest`
6. 完成第一版 Docker Hub 发布与验收

## 10. 当前结论

当前仓库后续的正式分发基线为：

- 首发宿主系统：`Ubuntu 22.04 x86_64`
- 镜像托管：`Docker Hub`
- 前端保留为正式独立服务
- 默认 SAM3 权重来源：`1038lab/sam3`
- 默认优先使用无 token 来源，失败后再要求 `HF_TOKEN` 并切回官方仓库
- 启动脚本必须承担 `doctor` / `doctor --fix` / `selftest` 入口职责
- 正式支持显存档位：`16G / 24G / 32G+`
