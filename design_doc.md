# 基于多模态大模型的自动标注系统 — 技术设计文档

> v1.0 | 面向开发阶段

---

## 目录

0. [目标与范围](#0-目标与范围)
1. [技术选型](#1-技术选型)
2. [系统架构](#2-系统架构)
3. [数据库与存储](#3-数据库与存储)
4. [开发阶段划分](#4-开发阶段划分)
5. [模块详细设计](#5-模块详细设计)
6. [目录结构](#6-目录结构)
7. [接口文档](#7-接口文档)
8. [单元测试](#8-单元测试)
9. [配置中心与运行时配置](#9-配置中心与运行时配置)
10. [评估系统](#10-评估系统)

---

## 0. 目标与范围

### 0.1 项目目标

- 面向**单机单用户**的“自动标注 + 人机协作纠错 + 以纠错数据微调”的闭环演示系统。
- 支持目标检测（bbox）与可选的实例分割（mask/polygon）两种任务模式。
- 以“**可跑通、可演示、可复现**”为优先级：功能完整 > 训练效果极致 > 高并发/多租户。

### 0.2 典型流程（最小闭环）

1) 创建项目 → 上传图片  
2) 触发自动标注（LLM bbox → SAM mask → 后处理）  
3) 人工纠错（补框 / 点选修正 / 删除 / 确认）  
4) （可选，手动触发）仅用 `is_confirmed=1` 的标注导出训练集 → LoRA 微调  
5) （可选）加载新 LoRA → 后续标注可在 base/LoRA 间切换

### 0.3 约束与不做（避免过度设计）

- 默认**单机单卡（1×GPU）**，并发量以“毕设演示规模”为目标（例如几百～几千张图）。
- 不做账号体系、权限管理、多项目协作、分布式训练/推理、多机部署等。
- 不追求在线大规模标注平台形态：数据、模型、日志均以本地目录组织即可。
- 微调不会自动开始：默认只做标注与纠错；是否微调由用户手动决定（且可长期不启用）。

---

## 1. 技术选型

| 层次 | 选型 |
|---|---|
| 多模态大模型 | Qwen3-VL（2B/4B/8B 按显存动态选择） |
| 像素级分割 | SAM 3 / SAM 3.1（facebookresearch/sam3） |
| 推理引擎 | vLLM |
| 微调框架 | LLaMA-Factory |
| 后端框架 | FastAPI |
| 任务队列 | Celery + Redis |
| 持久化存储 | SQLite（via SQLAlchemy） |
| 文件存储 | 本地文件系统 |
| SAM set_image 缓存 | 同一张图连续纠错复用 embedding（`current_image_id`）；可选扩展 LRU |
| 传统视觉 | OpenCV 4.x |
| 前端框架 | Vue 3 + Vite |
| 标注画布 | Fabric.js（自行封装） |
| 状态管理 | Pinia |
| 前后端通信 | REST（HTTP）+ WebSocket（任务进度推送） |

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端 (Vue 3)                          │
│  图片上传 │ 标注画布 │ 纠错交互 │ 微调控制台 │ 任务状态轮询  │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP / WebSocket
┌────────────────────▼────────────────────────────────────────┐
│                   FastAPI 主进程                              │
│  路由层  │  业务逻辑层  │  SQLAlchemy ORM  │  WS 推送服务   │
└──────┬────────────────────────────┬───────────────────────┘
       │ 提交任务                    │ 查询/写入
┌──────▼──────────┐        ┌────────▼──────────┐
│  Redis Broker   │        │  SQLite + 文件系统 │
└──────┬──────────┘        └───────────────────┘
       │ 分发
┌──────▼──────────────────────────────────────────┐
│              Celery Worker 进程                   │
│                                                   │
│  ┌─────────────┐   ┌──────────────────────────┐  │
│  │  标注任务队列 │   │     微调任务队列（独占）   │  │
│  └──────┬──────┘   └─────────────┬────────────┘  │
│         │                        │                │
│  ┌──────▼──────────────────────────────────────┐  │
│  │      GPU 资源互斥（Redis Lock / 单队列串行）  │  │
│  └──────────────────────────────────────────────┘  │
│         │                        │                │
│  ┌──────▼──────┐         ┌───────▼──────┐         │
│  │ vLLM 子进程  │         │LLaMA-Factory │         │
│  │ (port 8001) │         │ subprocess   │         │
│  └──────┬──────┘         └──────────────┘         │
│         │                                          │
│  ┌──────▼──────┐                                  │
│  │  SAM 3 单例  │                                  │
│  │ +当前图缓存  │                                  │
│  └──────┬──────┘                                  │
│         │                                          │
│  ┌──────▼──────┐                                  │
│  │   OpenCV    │                                  │
│  └─────────────┘                                  │
└─────────────────────────────────────────────────────┘
```

### 2.1 运行端口与关键配置（最小集）

- FastAPI：`http://localhost:8000`（REST + WebSocket）
- vLLM（OpenAI-compatible）：`http://localhost:8001`
- Redis：`redis://localhost:6379/0`（broker）+ `redis://localhost:6379/1`（result backend）

建议集中在 `backend/config.py` 管理（避免散落在代码里硬编码）：

- `APP_PORT`：FastAPI 端口
- `VLLM_BASE_URL`：vLLM 服务地址（含端口）
- `REDIS_BROKER_URL` / `REDIS_RESULT_BACKEND`：Celery broker/backend
- `DATA_DIR` / `MODELS_DIR` / `LOG_DIR`：目录根路径

---

## 3. 数据库与存储

### 3.1 SQLite 表结构

```sql
CREATE TABLE projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    task_type   TEXT NOT NULL,  -- 'detection' | 'segmentation'
    config      TEXT,           -- JSON：项目级运行时配置（模型选择/后处理/评估参数等）
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    width       INTEGER,
    height      INTEGER,
    split       TEXT DEFAULT 'train',  -- 'train'|'val'|'test'（评估/微调用）
    quality_score REAL,               -- 0~1：在线质量估计（无 GT），用于排序/筛选/抽检
    status      TEXT DEFAULT 'pending',  -- 'pending'|'annotating'|'done'|'error'
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE annotations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id     INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    label        TEXT NOT NULL,
    bbox         TEXT,     -- JSON: [xmin, ymin, xmax, ymax]，归一化 0~1
    mask_path    TEXT,     -- 二值 Mask PNG 的文件路径
    polygon      TEXT,     -- JSON: [[x,y], ...]，归一化 0~1
    confidence   REAL,
    quality_score REAL,    -- 0~1：实例级质量估计（无 GT），用于提示“可能需要复查”
    source       TEXT DEFAULT 'auto',  -- 'auto'|'manual'|'corrected'
    is_confirmed BOOLEAN DEFAULT 0,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE finetune_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    status       TEXT DEFAULT 'pending',  -- 'pending'|'running'|'done'|'failed'
    lora_path    TEXT,
    log_path     TEXT,
    started_at   DATETIME,
    finished_at  DATETIME,
    config       TEXT  -- JSON：训练超参数快照
);

CREATE TABLE evaluation_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status       TEXT DEFAULT 'pending',  -- 'pending'|'running'|'done'|'failed'
    split        TEXT DEFAULT 'val',      -- 'val'|'test'（或自定义 image_id 列表）
    model_tag    TEXT,                   -- 'base' | 'lora:{job_id}' | 'qwen3-vl-2b' 等
    metrics      TEXT,                   -- JSON：汇总指标
    report_path  TEXT,                   -- 可选：详细报告（JSON/CSV/zip）路径
    started_at   DATETIME,
    finished_at  DATETIME,
    config       TEXT                    -- JSON：本次评估采用的配置快照
);

CREATE INDEX idx_images_project_id ON images(project_id);
CREATE INDEX idx_images_project_split ON images(project_id, split);
CREATE INDEX idx_annotations_image_id ON annotations(image_id);
CREATE INDEX idx_finetune_jobs_project_id ON finetune_jobs(project_id);
CREATE INDEX idx_evaluation_runs_project_id ON evaluation_runs(project_id);
```

**实现备注（不增加复杂度但能少踩坑）：**

- SQLite 默认不强制外键约束，建议应用启动时执行 `PRAGMA foreign_keys=ON;`，保证级联删除生效。
- Celery 多进程并发写 SQLite 时可能出现 `database is locked`：
  - 演示规模下优先用“GPU 互斥 + 队列串行 + 短事务”来规避；
  - 可选开启 `PRAGMA journal_mode=WAL;` 提高并发读写容忍度（仍不建议高并发写入）。

### 3.2 坐标系约定

| 阶段 | 坐标类型 |
|---|---|
| Qwen3-VL 输出 | 归一化 0~1，`[xmin, ymin, xmax, ymax]` |
| 数据库存储 | 归一化 0~1 |
| SAM 3 输入 | 像素坐标（后端调用前乘以图片实际宽高转换） |
| 前端 Fabric.js | 画布坐标（前端渲染时乘以画布宽高转换） |
| 导出 YOLO 格式 | 归一化 0~1，`[cx, cy, w, h]` |
| 导出 COCO 格式 | 像素坐标，`[xmin, ymin, w, h]` |

### 3.3 文件系统结构

```
data/
├── projects/
│   └── {project_id}/
│       ├── images/
│       ├── masks/
│       └── exports/
models/
├── qwen3-vl-{2B|4B|8B}/
├── sam3/
└── lora/
    └── {job_id}/
logs/
└── finetune/
    └── {job_id}.log
```

---

## 4. 开发阶段划分

### Phase 1 — 基础框架（约 1 周）

| 任务 |
|---|
| FastAPI 项目初始化，SQLAlchemy + SQLite，Alembic 迁移 |
| Celery + Redis 本地联调，验证任务收发 |
| Vue 3 + Vite 前端初始化，配置 axios、vue-router、Pinia |
| 配置中心（最小）：`backend/config.py`（环境变量/可选 YAML）+ 项目运行时配置读写接口 |
| 图片上传接口：`POST /api/projects/{id}/images/upload`，存文件 + 写 DB |
| 图片列表接口：`GET /api/projects/{id}/images` |

**验收：** 能上传图片，前端展示图片列表。

---

### Phase 2 — 自动标注流水线（约 2 周）

| 任务 |
|---|
| `services/vllm_client.py`：封装 Guided Decoding 调用，定义输出 JSON Schema |
| `services/sam_service.py`：SAM 3 单例加载，封装 `set_image` / `predict` + “当前图” embedding 缓存 |
| `services/postprocess.py`：闭运算 + Douglas-Peucker 多边形逼近 |
| `tasks/annotation_task.py`：串联三级流水线，结果写 DB |
| `utils/gpu_lock.py`：GPU 互斥（Redis Lock 或单队列单并发），避免 FastAPI/Celery 多进程并发导致 OOM |
| Celery 配置：启用 Redis result backend，保证任务状态查询与 WS 推送可用 |
| **批量标注触发接口（项目级）**：`POST /api/projects/{id}/annotate`（默认标注 pending 图片，可选指定 `image_ids`），返回 task_id |
| 任务状态接口：`GET /api/tasks/{task_id}/status` |
| 前端标注画布：Fabric.js 渲染 Bbox 矩形、Mask 多边形轮廓、类别标签 |

**验收：** 上传图片 → 点击“批量自动标注” → 前端看到进度与图片状态变化 → 进入图片详情可看到标注结果。

---

### Phase 3 — Human-in-the-Loop 纠错（约 1 周）

| 任务 |
|---|
| 删除标注接口：`DELETE /api/annotations/{id}` |
| SAM 交互预测接口：`POST /api/images/{id}/predict`（支持 bbox / points 两种输入） |
| 确认标注接口：`PATCH /api/annotations/{id}/confirm` |
| WebSocket 进度推送：`WS /ws/tasks/{task_id}` |
| 前端：拖拽画框触发漏标补全；左/右键点击发送正/负点；右键菜单删除标注 |

**验收：** 删除标注、手动补框、点击正负点均正常；同一张图片连续点选纠错时（SAM embedding 已缓存）交互响应时间 < 300ms（GPU 空闲）。

---

### Phase 4 — LoRA 微调引擎（约 1.5 周）

| 任务 |
|---|
| `tools/export_dataset.py`：将 DB 中 `is_confirmed=1` 且 `images.split='train'` 的标注转为 LLaMA-Factory JSONL 格式 |
| `tools/prompt_templates.py`：多样化提示词模板池 |
| `services/finetune_service.py`：按显存自动生成 LLaMA-Factory yaml 配置 |
| `tasks/finetune_task.py`：subprocess 拉起训练，实时写 log，完成后更新 DB |
| 微调接口：`POST /api/finetune/start`，`GET /api/finetune/{id}/status`，`GET /api/finetune/{id}/log` |
| LoRA 激活接口：`POST /api/finetune/{id}/activate`（若微调期间暂停/关闭 vLLM，则此接口负责启动并加载新 adapter） |
| 前端微调控制台：显示日志、loss 曲线（轮询解析 log）、完成后切换模型 |
| `tools/import_dataset.py`：支持导入外部 YOLO / COCO 格式数据集 |

**说明（符合你的诉求）：**

- 微调是**手动触发的可选功能**，默认只做标注与纠错；用户数据不垂直/不想训练时，可完全跳过 Phase 4。
- 微调数据集来源：仅用 `is_confirmed=1` 的标注（尽量减少噪声标签把模型“越训越差”）。
- 训练/评估划分：用 `images.split` 手动划分即可（例如挑 30～50 张做 `val/test` 作为“黄金集”），不做自动拆分强绑定。

**验收：**

- 不点击微调：系统标注/纠错全流程正常。
- 点击开始微调：日志实时显示 → 完成后可选择激活 LoRA → 新模型可用于后续标注。

---

### Phase 5 — 收尾与演示（约 0.5 周）

| 任务 |
|---|
| 数据集导出：`GET /api/projects/{id}/export?format=yolo\|coco` |
| GPU 互斥与排队体验：GPU 忙时标注任务可 retry/排队；交互预测接口返回 “busy” 并提示稍后重试 |
| vLLM 超时重试（httpx timeout + retry） |
| 无效图片上传拦截（格式校验、最大尺寸限制） |
| 评估与质量（MVP）：离线指标评估（可选，val/test）+ 在线质量评分（无 GT，用于抽检/排序） |
| `start.sh`：一键启动 Redis、vLLM 子进程、Celery Worker、FastAPI |
| 使用 Phase 4 训练的 LoRA 权重演示闭环效果 |

**验收：** 完整演示上传 → 自动标注 → 纠错 → 微调 → 使用新模型标注全流程。

---

## 5. 模块详细设计

### 5.1 GPU 互斥锁

```python
# utils/gpu_lock.py
from contextlib import contextmanager
import os
import redis

REDIS_URL = os.getenv("REDIS_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0"))
_redis = redis.Redis.from_url(REDIS_URL)

class GPULock:
    @staticmethod
    @contextmanager
    def acquire(timeout: int | None = None, lock_timeout: int = 60 * 60):
        """
        跨进程互斥锁：
        - timeout: 获取锁等待时间（秒）。None=一直等；数字=等待指定秒数，失败抛 TimeoutError
        - lock_timeout: 锁 TTL（秒），避免异常退出导致死锁
        """
        lock = _redis.lock("gpu:lock", timeout=lock_timeout)
        ok = lock.acquire(blocking=True, blocking_timeout=timeout)
        if not ok:
            raise TimeoutError("GPU is busy")
        try:
            yield
        finally:
            # redis lock 可能因 TTL 过期而已释放，release 需要兜底
            try:
                lock.release()
            except Exception:
                pass
```

**为什么不用 `threading.Lock`：** FastAPI + Celery 通常是多进程部署，`threading.Lock` 只能在单进程内生效。

- 微调任务：`with GPULock.acquire(timeout=None): ...`（阻塞等待，保证训练独占）
- 标注任务：`with GPULock.acquire(timeout=5): ...` 获取失败则 `Celery retry`（形成排队体验）
- 交互预测接口：`with GPULock.acquire(timeout=0): ...` 获取失败直接返回 `409 busy`（避免卡住 UI）

---

### 5.2 vLLM 推理封装

```python
# services/vllm_client.py
import os

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8001")

ANNOTATION_SCHEMA = {
    "type": "object",
    "properties": {
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label":      {"type": "string"},
                    "confidence": {"type": "number"},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4, "maxItems": 4
                    }
                },
                "required": ["label", "bbox"]
            }
        }
    },
    "required": ["objects"]
}

SYSTEM_PROMPT = (
    "你是一个专业的图像标注助手。请检测图像中的所有目标，"
    "以 JSON 格式输出每个目标的类别名称和边界框坐标。"
    "边界框格式为 [xmin, ymin, xmax, ymax]，坐标归一化到 0~1 范围。"
)

def build_grounding_prompt(labels: list[str]) -> str:
    # 固定系统提示词 + 用户配置 labels 列表（不接收用户自由文本），降低提示词攻击风险
    if labels:
        labels_text = ", ".join(labels)
        return f"请仅检测图中属于以下类别列表的目标：{labels_text}。不在列表中的对象请忽略。"
    return "请检测图中所有目标。"

async def detect_objects(image_b64: str, labels: list[str]) -> dict:
    payload = {
        "model": "qwen3-vl",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text", "text": build_grounding_prompt(labels)}
                ]
            }
        ],
        "guided_json": ANNOTATION_SCHEMA,
        "max_tokens": 2048
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{VLLM_BASE_URL}/v1/chat/completions", json=payload)
        resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)
```

**进程生命周期建议（不做复杂编排）：**

- 日常标注：保持 vLLM 常驻（避免频繁启动开销）。
- 微调期间：若显存紧张，先停止 vLLM 再训练；训练结束后通过 `POST /api/finetune/{id}/activate` 重启并加载 LoRA。

---

### 5.3 SAM 3 服务

```python
# services/sam_service.py
from sam3 import build_sam3_image_model
import numpy as np

class SAMService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.model = build_sam3_image_model(
            checkpoint_path="models/sam3/sam3.1_multiplex.pt",
            device="cuda",
            enable_inst_interactivity=True,
        )
        self.predictor = self.model.inst_interactive_predictor
        # 注意：predictor 同一时间只“记得”一张图的 embedding。
        # 因此这里的缓存策略是：同一张图连续纠错时复用 embedding（最小可用且不易出错）。
        self._current_image_id = None

    def set_image(self, image_id: int, image_np: np.ndarray):
        if self._current_image_id != image_id:
            self.predictor.set_image(image_np)
            self._current_image_id = image_id

    def predict(self, image_id: int, image_np: np.ndarray,
                bbox: list = None, points: list = None, point_labels: list = None) -> np.ndarray:
        self.set_image(image_id, image_np)
        masks, scores, _ = self.predictor.predict(
            box=np.array(bbox) if bbox else None,
            point_coords=np.array(points) if points else None,
            point_labels=np.array(point_labels) if point_labels else None,
            multimask_output=False,
            normalize_coords=True,
        )
        return masks[0], scores[0]
```

---

### 5.4 OpenCV 后处理

```python
# services/postprocess.py
import cv2
import numpy as np

def smooth_mask(mask: np.ndarray, epsilon_ratio: float = 0.002) -> list:
    """
    输入: SAM 输出的 bool Mask (H, W)
    输出: 归一化多边形顶点 [[x,y], ...]
    """
    mask_u8 = mask.astype(np.uint8) * 255
    h, w = mask_u8.shape

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    closed = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contour = max(contours, key=cv2.contourArea)

    epsilon = epsilon_ratio * cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, epsilon, True)

    return [[float(p[0][0]) / w, float(p[0][1]) / h] for p in approx]
```

---

### 5.5 Celery 标注任务

```python
# tasks/annotation_task.py
@celery_app.task(bind=True, max_retries=5)
def run_annotation(self, image_id: int, labels: list[str], task_type: str):
    try:
        with GPULock.acquire(timeout=5):
            image = load_image(image_id)
            image_b64 = to_base64(image)

            result = asyncio.run(detect_objects(image_b64, labels))

            for obj in result["objects"]:
                bbox_norm = obj["bbox"]
                mask_path, polygon = None, None

                if task_type == "segmentation":
                    h, w = image.shape[:2]
                    bbox_px = denormalize_bbox(bbox_norm, w, h)
                    center_px = bbox_center(bbox_px)
                    sam = SAMService()
                    mask = sam.predict(image_id, image, bbox=bbox_px, points=[center_px], point_labels=[1])
                    polygon = smooth_mask(mask)
                    mask_path = save_mask(image_id, obj["label"], mask)

                save_annotation(image_id, obj["label"], bbox_norm, mask_path, polygon, obj.get("confidence"))

        update_image_status(image_id, "done")
    except TimeoutError:
        raise self.retry(countdown=30)
```

---

### 5.6 Celery 微调任务

```python
# tasks/finetune_task.py
@celery_app.task(bind=True)
def run_finetune(self, job_id: int):
    with GPULock.acquire():
        update_job_status(job_id, "running")
        # 推荐：微调前暂停/关闭 vLLM 释放显存，避免与训练并存导致 OOM
        # （微调完成后由 /api/finetune/{id}/activate 再启动并加载 LoRA）
        stop_vllm_server()
        config_path = generate_and_write_config(job_id)
        log_path = f"logs/finetune/{job_id}.log"

        proc = subprocess.Popen(
            ["llamafactory-cli", "train", config_path],
            stdout=open(log_path, "w"),
            stderr=subprocess.STDOUT
        )
        proc.wait()

        status = "done" if proc.returncode == 0 else "failed"
        update_job_status(job_id, status, log_path=log_path)
```

---

### 5.7 微调数据格式

每条样本 JSONL：

```jsonc
{
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "image", "image": "file:///data/projects/1/images/img001.jpg"},
        {"type": "text",  "text": "请检测图中所有缺陷目标并输出边界框。"}
      ]
    },
    {
      "role": "assistant",
      "content": "{\"objects\": [{\"label\": \"crack\", \"bbox\": [0.1, 0.2, 0.4, 0.6]}]}"
    }
  ]
}
```

提示词模板池（`tools/prompt_templates.py`）：

```python
TEMPLATES = [
    "请检测图中所有{category}目标并输出边界框。",
    "识别图像中的{category}，返回坐标。",
    "找出所有{category}的位置，以 JSON 格式输出。",
    "图中有哪些{category}？请给出 bounding box。",
    "标注图像中所有{category}，输出归一化坐标。",
]
```

---

### 5.8 微调配置自动生成

```python
# services/finetune_service.py
import torch

def generate_lora_config(project_id: int, job_id: int) -> dict:
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    model_size = "2B" if vram_gb < 12 else ("4B" if vram_gb < 20 else "8B")
    return {
        "model_name_or_path": f"models/qwen3-vl-{model_size}",
        "finetuning_type": "lora",
        "lora_rank": 8,
        "lora_target": "all",
        "dataset": f"project_{project_id}_train",
        "output_dir": f"models/lora/{job_id}",
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 8,
        "num_train_epochs": 3,
        "learning_rate": 1e-4,
        "bf16": True,
    }
```

---

### 5.9 前端标注画布（Fabric.js）

```javascript
// 渲染 Bbox
function renderBbox(ann, canvasW, canvasH) {
  const rect = new fabric.Rect({
    left:   ann.bbox[0] * canvasW,
    top:    ann.bbox[1] * canvasH,
    width:  (ann.bbox[2] - ann.bbox[0]) * canvasW,
    height: (ann.bbox[3] - ann.bbox[1]) * canvasH,
    stroke: '#00FF00', strokeWidth: 2, fill: 'transparent',
    data: { annotationId: ann.id }
  });
  canvas.add(rect);
}

// 渲染 Mask 多边形
function renderPolygon(ann, canvasW, canvasH) {
  const points = ann.polygon.map(([x, y]) => ({ x: x * canvasW, y: y * canvasH }));
  const poly = new fabric.Polygon(points, {
    stroke: '#FF4500', strokeWidth: 1.5,
    fill: 'rgba(255,69,0,0.15)',
    data: { annotationId: ann.id }
  });
  canvas.add(poly);
}

// 正/负点交互（防抖 300ms）
canvas.on('mouse:down', _.debounce((opt) => {
  const point = {
    x: opt.pointer.x / canvasW,
    y: opt.pointer.y / canvasH,
    label: opt.e.button === 2 ? 0 : 1  // 右键=负点
  };
  pendingPoints.push(point);
  api.predict(imageId, { points: pendingPoints }).then(refreshPolygon);
}, 300));
```

---

### 5.10 WebSocket 进度推送

```javascript
// 前端
const ws = new WebSocket(`ws://localhost:8000/ws/tasks/${taskId}`);
ws.onmessage = (event) => {
  const { progress, status } = JSON.parse(event.data);
  updateProgressBar(progress);
  if (status === 'SUCCESS') reloadAnnotations();
  if (status === 'FAILURE') showTaskError();
};
```

```python
# 后端 routers/websocket.py
@router.websocket("/ws/tasks/{task_id}")
async def task_ws(websocket: WebSocket, task_id: str):
    await websocket.accept()
    while True:
        result = celery_app.AsyncResult(task_id)
        meta = result.info if isinstance(result.info, dict) else {}
        await websocket.send_json({
            "status": result.status,
            "progress": meta.get("progress", 0)
        })
        if result.ready():
            break
        await asyncio.sleep(1)
```

---

## 6. 目录结构

```
project-root/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   ├── routers/
│   ├── services/
│   │   ├── settings_service.py
│   │   └── evaluation_service.py
│   ├── tasks/
│   │   └── evaluation_task.py
│   ├── tools/
│   └── utils/
├── frontend/
│   └── src/
│       ├── views/
│       │   ├── ProjectList.vue
│       │   ├── ImageList.vue
│       │   ├── AnnotationCanvas.vue
│       │   ├── FinetuneConsole.vue
│       │   └── EvaluationDashboard.vue
│       ├── components/
│       │   ├── FabricCanvas.vue
│       │   ├── AnnotationToolbar.vue
│       │   ├── ProgressPanel.vue
│       │   └── SettingsPanel.vue
│       ├── api/
│       └── store/
├── data/
├── models/
├── logs/
├── configs/
├── tests/
├── start.sh
└── requirements.txt
```

---

## 7. 接口文档

### 通用响应格式

```json
{ "code": 200, "message": "ok", "data": {} }
```

错误时 HTTP 状态码与 `code` 一致，`data` 为 `null`。常用状态码：`400` 参数错误，`404` 资源不存在，`409` 冲突（如微调任务正在运行），`500` 服务器错误。

---

### 项目管理

**GET `/api/projects`**
```json
// Response 200
{
  "code": 200, "message": "ok",
  "data": [{ "id": 1, "name": "工业缺陷", "task_type": "segmentation", "created_at": "2025-01-01T00:00:00" }]
}
```

**POST `/api/projects`**
```json
// Request
{ "name": "工业缺陷", "task_type": "segmentation" }
// Response 200
{ "code": 200, "message": "ok", "data": { "id": 1 } }
```

**DELETE `/api/projects/{id}`**
```json
{ "code": 200, "message": "ok", "data": null }
```

---

### 项目配置（运行时）

项目级配置存储在 `projects.config`（JSON），用于模型档位/后处理/评估参数等，可在运行时调整。

**GET `/api/projects/{id}/settings`**
```json
// Response 200
{
  "code": 200, "message": "ok",
  "data": {
    "labels": ["crack", "scratch"],
    "model_profile": "auto",
    "sam": { "checkpoint": "sam3", "device": "cuda" },
    "postprocess": { "enable_close": true, "close_kernel": 5, "epsilon_ratio": 0.002 }
  }
}
```

**PATCH `/api/projects/{id}/settings`**（部分更新）
```json
// Request（示例：关闭闭运算、增大多边形简化强度）
{
  "postprocess": { "enable_close": false, "epsilon_ratio": 0.003 }
}
// Response 200
{ "code": 200, "message": "ok", "data": null }
```

---

### 图片管理

**POST `/api/projects/{id}/images/upload`**

请求：`multipart/form-data`，字段 `files[]`（支持多文件）。
```json
// Response 200
{ "code": 200, "message": "ok", "data": { "uploaded": 3, "image_ids": [10, 11, 12] } }
```

**GET `/api/projects/{id}/images`**
```json
// Response 200
{
  "code": 200, "message": "ok",
  "data": [{
    "id": 10, "filename": "img001.jpg", "width": 1920, "height": 1080,
    "split": "train", "status": "done",
    "quality_score": 0.82
  }]
}
```

**PATCH `/api/images/{id}`**（可选：用于划分 train/val/test）
```json
// Request
{ "split": "val" }
// Response 200
{ "code": 200, "message": "ok", "data": null }
```

**DELETE `/api/images/{id}`**
```json
{ "code": 200, "message": "ok", "data": null }
```

---

### 标注操作

**POST `/api/projects/{id}/annotate`**（项目级批处理）
```json
// Request
{ "only_pending": true }
// 或（可选）指定部分图片
{ "image_ids": [10, 11, 12] }
// Response 200
{ "code": 200, "message": "ok", "data": { "task_id": "abc-123" } }
```

**GET `/api/images/{id}/annotations`**
```json
// Response 200
{
  "code": 200, "message": "ok",
  "data": [{
    "id": 55, "label": "crack",
    "bbox": [0.1, 0.2, 0.4, 0.6],
    "polygon": [[0.1, 0.2], [0.4, 0.2], [0.4, 0.6], [0.1, 0.6]],
    "confidence": 0.92, "source": "auto", "is_confirmed": false, "quality_score": 0.76
  }]
}
```

**DELETE `/api/annotations/{id}`**
```json
{ "code": 200, "message": "ok", "data": null }
```

**PATCH `/api/annotations/{id}/confirm`**
```json
{ "code": 200, "message": "ok", "data": null }
```

**POST `/api/images/{id}/predict`**

语义：

- `annotation_id = null`：创建新标注（需要同时传 `label`）
- `annotation_id != null`：更新已有标注（默认沿用原 `label`）

`bbox` 和 `points` 二选一传入：
```json
// 漏标补框
{ "annotation_id": null, "label": "crack", "bbox": [0.1, 0.1, 0.5, 0.5], "points": null }

// 正负点纠错
{ "annotation_id": 55, "bbox": null, "points": [{"x": 0.3, "y": 0.4, "label": 1}, {"x": 0.1, "y": 0.1, "label": 0}] }

// Response 200
{
  "code": 200, "message": "ok",
  "data": {
    "annotation_id": 55,
    "polygon": [[0.1, 0.2], [0.4, 0.2], [0.4, 0.6]],
    "mask_path": "data/projects/1/masks/55.png"
  }
}
```

---

### 任务状态

**GET `/api/tasks/{task_id}/status`**
```json
// Response 200
{ "code": 200, "message": "ok", "data": { "status": "STARTED", "progress": 60 } }
```
`status` 枚举：`PENDING` | `STARTED` | `SUCCESS` | `FAILURE`

**WS `/ws/tasks/{task_id}`** — 服务端每秒推送：
```json
{ "status": "STARTED", "progress": 60 }
```

---

### 微调

**POST `/api/finetune/start`**
```json
// Request
{ "project_id": 1 }
// Response 200
{ "code": 200, "message": "ok", "data": { "job_id": 3 } }
// Response 409
{ "code": 409, "message": "a finetune job is already running", "data": null }
```

**GET `/api/finetune/{id}/status`**
```json
{ "code": 200, "message": "ok", "data": { "status": "running", "started_at": "2025-01-01T10:00:00", "finished_at": null } }
```

**GET `/api/finetune/{id}/log`**
```json
{ "code": 200, "message": "ok", "data": { "log": "Epoch 1/3 | loss: 0.543\nEpoch 2/3 | loss: 0.321\n" } }
```

**POST `/api/finetune/{id}/activate`** — 启动/重启 vLLM 并加载对应 LoRA adapter（用于微调完成后的模型切换）。
```json
{ "code": 200, "message": "ok", "data": null }
```

---

### 数据集

**POST `/api/projects/{id}/import`** — `multipart/form-data`，字段：`file`（zip），`format`（`"yolo"` | `"coco"`）。
```json
{ "code": 200, "message": "ok", "data": { "imported_count": 120 } }
```

**GET `/api/projects/{id}/export?format=yolo`** — 返回 zip 文件流，`Content-Type: application/zip`。

---

### 评估

**POST `/api/projects/{id}/evaluate`**
```json
// Request（split 与 image_ids 二选一）
{ "split": "val", "model_tag": "base" }
// 或
{ "image_ids": [10, 11, 12], "model_tag": "lora:3" }

// Response 200
{ "code": 200, "message": "ok", "data": { "run_id": 12, "task_id": "eval-xyz" } }
```

**GET `/api/evaluations/{run_id}`**
```json
// Response 200
{
  "code": 200, "message": "ok",
  "data": {
    "id": 12, "status": "done", "split": "val", "model_tag": "lora:3",
    "metrics": { "precision": 0.71, "recall": 0.66, "f1": 0.68, "miou_bbox": 0.59 }
  }
}
```

**GET `/api/projects/{id}/evaluations`**（可选：列表）
```json
{ "code": 200, "message": "ok", "data": [{ "id": 12, "status": "done", "model_tag": "lora:3" }] }
```

---

## 8. 单元测试

测试框架：`pytest` + `pytest-asyncio`，测试目录 `tests/`。

### 后处理

```python
# tests/test_postprocess.py
def test_smooth_mask_returns_normalized_polygon():
    mask = np.zeros((100, 100), dtype=bool)
    mask[20:80, 20:80] = True
    polygon = smooth_mask(mask)
    assert len(polygon) >= 4
    for x, y in polygon:
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0

def test_smooth_mask_empty_returns_empty():
    mask = np.zeros((100, 100), dtype=bool)
    assert smooth_mask(mask) == []
```

### 坐标转换

```python
# tests/test_coords.py
def test_denormalize_bbox():
    assert denormalize_bbox([0.1, 0.2, 0.5, 0.6], w=100, h=200) == [10, 40, 50, 120]

def test_normalize_bbox():
    assert normalize_bbox([10, 40, 50, 120], w=100, h=200) == [0.1, 0.2, 0.5, 0.6]
```

### 数据格式转换

```python
# tests/test_export.py
def test_annotation_to_llama_format():
    ann = {"label": "crack", "bbox": [0.1, 0.2, 0.4, 0.6]}
    sample = annotation_to_llama_format("/data/projects/1/images/img001.jpg", [ann], prompt="请标注缺陷。")
    assert sample["messages"][0]["role"] == "user"
    assert sample["messages"][1]["role"] == "assistant"
    content = json.loads(sample["messages"][1]["content"])
    assert content["objects"][0]["label"] == "crack"
```

### GPU 锁

```python
# tests/test_gpu_lock.py
def test_lock_blocks_concurrent_access():
    results = []
    def task(name):
        with GPULock.acquire():
            results.append(f"{name}_enter")
            time.sleep(0.1)
            results.append(f"{name}_exit")

    t1 = threading.Thread(target=task, args=("A",))
    t2 = threading.Thread(target=task, args=("B",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    # A 和 B 的执行不交叉
    exit_a = results.index("A_exit")
    enter_b = results.index("B_enter")
    assert exit_a < enter_b or results.index("B_exit") < results.index("A_enter")
```

### API 接口

```python
# tests/test_api.py
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_create_project():
    resp = client.post("/api/projects", json={"name": "test", "task_type": "detection"})
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] is not None

def test_get_nonexistent_image_annotations():
    resp = client.get("/api/images/99999/annotations")
    assert resp.status_code == 404
    assert resp.json()["code"] == 404
```

---

## 9. 配置中心与运行时配置

### 9.1 为什么需要配置中心（结合你的 6GB/32GB 场景）

你的开发环境（约 6GB 显存）和演示环境（可能 32GB）差异很大，且“自动标注流水线”本身是多组件叠加（vLLM + SAM + OpenCV + 微调）。如果所有参数写死，会出现：

- 开发机跑不动（OOM 或速度极慢），导致无法迭代；
- 演示机无法一键切到更强模型，效果展示受限；
- SAM 后处理策略、阈值等需要在实验阶段快速调参，否则验证成本高。

因此这里的“配置中心”目标是：**把可变的东西集中管理 + 可在运行时调整**，同时保持实现简单。

### 9.2 配置分层（最小可用，不做复杂平台）

建议采用两层：

1) **全局静态配置（进程级）**：环境变量（`.env`）+ 可选 `configs/app.yaml`  
   用于端口、目录、Redis 地址、vLLM base url、可用模型列表等。

2) **项目级运行时配置（DB 持久化）**：存到 `projects.config`（JSON）  
   用于模型选择策略、SAM/后处理参数、评估参数等，可通过 API 更新并立即生效。

优点：实现成本低；每个项目有自己的“实验参数”；评估与微调可记录配置快照，便于复现。

### 9.3 项目配置 Schema（示例）

> 只保留“真的会变、且影响效果/性能”的参数，避免把所有底层参数都暴露出来。

```jsonc
{
  "labels": ["crack", "scratch"],
  "model_profile": "auto",               // 'dev_6gb'|'demo_32gb'|'auto'|'fixed'
  "llm": {
    "base_model": "qwen3-vl-2b",         // fixed 时使用
    "auto_order": ["2b", "4b", "8b"],    // auto 时按显存从小到大尝试
    "max_tokens": 2048
  },
  "sam": {
    "checkpoint": "sam3",                // 默认 symbolic alias；真实联调时可替换为本地 .pt 或启用 HF 下载
    "device": "cuda",                   // 'cuda'|'cpu'
    "multimask_output": false
  },
  "postprocess": {
    "enable_close": true,
    "close_kernel": 5,
    "enable_dp_simplify": true,
    "epsilon_ratio": 0.002,
    "min_area_ratio": 0.0005
  },
  "quality": {
    "enable": true,
    "threshold_review": 0.6,             // < threshold 时强烈建议人工复查
    "threshold_ok": 0.8,                 // >= threshold 时可降低抽检频率（不等于“正确”）
    "use_llm_confidence": true,
    "use_sam_score": true,
    "enable_consistency_check": false    // 可选：用轻微扰动重复 SAM 推理做稳定性评分（更准但更慢）
  },
  "evaluation": {
    "split": "val",
    "iou_threshold": 0.5,
    "max_samples": null
  }
}
```

### 9.4 模型加载策略（可选但不复杂）

支持四种策略即可覆盖你的需求：

- `dev_6gb`：固定小模型（如 Qwen3-VL 2B + SAM3 stub / CPU），优先保证开发与联调可持续。
- `demo_32gb`：固定大模型（如 Qwen3-VL 8B + SAM3.1 real stack），追求效果。
- `fixed`：用户显式指定 `llm.base_model`、`sam.checkpoint`。
- `auto`：后端探测 `torch.cuda.total_memory`，按 `auto_order` 选择“能跑得动的最大档”；选择结果写入日志并可回显到前端。

> 注意：vLLM 模型切换通常需要重启进程；因此“运行时切换 base 模型”建议做成**显式操作**（按钮/接口触发），不要每张图动态切。

### 9.5 配置接口（建议）

- `GET /api/projects/{id}/settings`：返回项目配置（含默认值合并结果）
- `PATCH /api/projects/{id}/settings`：更新部分字段（后端做 schema 校验）
- （可选）`POST /api/system/model/activate`：切换 vLLM base 模型 profile（会重启 vLLM）

前端建议提供一个轻量的 `SettingsPanel.vue`，只暴露上述 schema 中的关键字段。

### 9.6 配置生效规则（避免“看起来改了但其实没生效”）

将配置项明确分为两类，避免过度设计但能减少调参踩坑：

- **热更新（立即生效）**：后处理参数（`postprocess.*`）、质量评分参数（`quality.*`）、评估参数（`evaluation.*`）、提示词模板选择等  
  处理方式：API 更新后直接写 DB；任务执行时读取最新配置即可。

- **需重启/重载（显式操作）**：vLLM base 模型切换、SAM checkpoint 切换  
  处理方式：
  - vLLM：通过显式接口/脚本重启 vLLM 子进程（避免每张图动态切换造成频繁重启）。
  - SAM：可以在 Celery worker 内支持“按需 lazy load + 按项目切换时重载”，但建议**演示阶段先固定**一个 checkpoint（tiny/base/large）以降低复杂度。

---

## 10. 评估系统

本节包含两类能力：

- **离线评估（需要 GT）**：给出可量化、可对比、可复现的指标，用于论文/答辩展示“微调前后提升”。
- **在线质量评分（不需要 GT）**：对“待标注图片”的自动标注结果做风险提示/排序，辅助用户抽检与补救。

### 10.1 评估对象与数据来源

- **关键说明：**
  - **离线评估**（需要 GT）：用于论文/对比“微调前后提升”，必须依赖一小部分高质量标注（val/test 或导入数据）。
  - **在线质量评分**（不需要 GT）：用于真实使用场景中对“待标注图片”的结果进行**抽检排序/风险提示**，不能替代真实精度指标。

- **评估对象**：完整的自动标注流水线输出（LLM bbox +（可选）SAM mask + 后处理）。
- **Ground Truth（GT）来源**：
  - 导入的 COCO/YOLO 数据集（导入时标注默认 `is_confirmed=1` 作为 GT），或
  - 在系统内人工纠错并“确认”的标注（`is_confirmed=1`）。

评估时按 `images.split in ('val','test')` 选取图片，避免“用训练集自评”。

### 10.2 在线质量评分（无 GT，面向真实使用）

实际使用中，用户往往只有“待标注图片”，没有测试集/GT。此时无法计算 mAP/mIoU，但仍然可以给出**质量风险提示**：

- 输出：`images.quality_score`（0~1）和 `annotations.quality_score`（0~1）
- 用途：
  - 图片列表按 `quality_score` 排序：优先复查低分图片；
  - 对低分图片自动打 “needs_review” 提示（前端显示，不需要额外表字段）；
  - 形成“少量抽检 + 重点补救”的工作流。

**质量分的来源信号（不依赖 GT，尽量复用已有信息）：**

- LLM：`confidence`（若模型能稳定给出；否则权重降低或关闭 `use_llm_confidence`）
- SAM：`scores` / `predicted_iou`（分割任务可用；检测-only 项目忽略）
- 几何与一致性（纯规则，成本低）：
  - bbox/mask 是否越界、面积是否极端（过小/过大）、mask 是否贴边、polygon 顶点数是否异常
  - （可选）一致性检查：对 bbox 轻微 jitter，重复 1～2 次 SAM 推理，计算 mask IoU 稳定性（更准但更慢）

> 重要：在线质量评分是“风险提示/排序”，不是“正确率”。你可以在论文里把它称为 **Quality Estimation / Triage Score**。

### 10.3 指标（离线评估，MVP 版本）

按任务类型给最核心、最常用的指标：

**Detection（bbox）**

- `Precision@IoU=0.5`、`Recall@IoU=0.5`、`F1@IoU=0.5`
- `mIoU_bbox`（匹配到的样本 bbox IoU 均值）
- 按类别统计（可选）：每类的 P/R/F1（用于发现类别不均衡）

**Segmentation（mask/polygon）**

- `mIoU_mask`（像素 IoU 或 polygon rasterize 后 IoU）
- `Dice`（可选）

> 论文如需 COCO 标准 mAP，可选用 `pycocotools` 生成 COCO 格式并跑 `COCOeval`（实现工作量低，指标更“权威”）。

### 10.4 离线评估流程（异步任务）

1) 选择项目 + split（val/test）+ 模型版本（base / lora job）  
2) Celery 启动 `evaluation_task`：
   - 逐图跑推理（复用现有流水线代码，但**不写入 annotations 表**，只保存在评估临时结果中）
   - 与 GT 匹配并累计 TP/FP/FN
   - 计算汇总指标，写入 `evaluation_runs.metrics`
   - 可选输出详细报告到 `report_path`（json/csv）
3) 前端 `EvaluationDashboard.vue` 展示：本次指标 + 与上一次/指定 run 对比（微调前 vs 微调后）

### 10.5 数据库存储与复现

`evaluation_runs` 记录：

- 本次评估用的 `model_tag`（如 `base` / `lora:3` / `qwen3-vl-4b`）
- `split`、开始/结束时间
- `metrics`（汇总指标 JSON）
- `config`（项目配置快照，用于复现）
- `report_path`（可选：详细 per-image 结果，便于做失败案例分析）

### 10.6 评估接口（建议）

评估相关接口已在第 7 节 **“评估”** 小节中给出，这里不重复：

- `POST /api/projects/{id}/evaluate`（`split` 与 `image_ids` 二选一）
- `GET /api/evaluations/{run_id}`
- `GET /api/projects/{id}/evaluations`

### 10.7 性能与效率指标（可选，但对毕设很加分）

除了精度类指标，建议顺手记录“系统是否真的提效”，避免论文只谈 mAP：

- **自动标注耗时**：LLM 推理耗时、SAM 耗时、后处理耗时、总耗时（均值/p95）
- **交互纠错成本**：每张图平均点击次数（正/负点）、平均补框次数、平均删除次数
- **采纳率**：自动标注中被直接确认的比例（`is_confirmed=1` 且未被修改的占比）

实现上不需要复杂埋点：在任务执行时记录到日志或写入 `evaluation_runs.metrics` 的扩展字段即可。
