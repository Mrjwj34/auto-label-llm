# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **auto-labeling system** for computer vision tasks (object detection and instance segmentation). It's a single-user, single-machine closed-loop system: upload images → auto-annotate (LLM bbox + optional SAM mask) → human correction → optional fine-tuning with corrected data.

**Key characteristics:**
- Single-user, single-machine deployment (not a multi-tenant platform)
- Supports detection (bbox) and segmentation (mask/polygon) tasks
- Uses multimodal LLMs (Qwen3-VL family) for bbox detection via vLLM
- Uses SAM2/SAM2.1 for instance segmentation
- Optional LoRA fine-tuning via LLaMA-Factory
- Redis-based task queue with WebSocket progress updates
- FastAPI backend + React frontend (migrating from Vue)

## Development Commands

### Starting the System

**Primary method (Linux):**
```bash
# Low-resource development (stub backends, CPU-friendly)
bash scripts/start-linux.sh --profile dev_low_resource --run-tests

# Real stack testing (local vLLM + SAM2 + LLaMA-Factory)
VLLM_MODEL_SOURCE=Qwen/Qwen3-VL-8B-Instruct-FP8 \
bash scripts/start-linux.sh --profile test_real_stack --with-vllm --with-sam --with-llamafactory

# Setup only (no services, useful for prepping GPU machines)
bash scripts/start-linux.sh --profile test_real_stack --setup-only --with-sam --with-llamafactory

# Skip vLLM if already running elsewhere
VLLM_BASE_URL=http://127.0.0.1:8001 \
bash scripts/start-linux.sh --profile test_real_stack --skip-vllm
```

The `start-linux.sh` script handles:
- System dependency checks (Ubuntu/Debian)
- Python venv creation and dependency caching
- Frontend dependency installation
- Profile-based `.env.active` and `frontend/.env.local` generation
- Optional pytest + frontend build
- Service startup (Redis, worker, FastAPI, frontend dev server)
- Optional local vLLM/SAM2/LLaMA-Factory setup

**Manual backend startup:**
```bash
# Activate venv
source .venv/bin/activate  # or .venv/Scripts/activate on Windows

# Run backend
python -m backend.main

# Run worker (if TASK_EMBEDDED_WORKER=false)
python -m backend.task_worker_main
```

**Manual frontend startup:**
```bash
cd frontend
npm install
npm run dev
```

### Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_api_m4_auto_annotations.py

# Run with verbose output
pytest -v

# Run tests matching pattern
pytest -k "test_annotation"
```

**Browser-based integration tests:**
```bash
# M13 (task queue + WebSocket)
python scripts/verify_m13_real_redis.py --redis-url redis://127.0.0.1:6379/15 --flush-redis-db

# M14 (fine-tuning)
python scripts/verify_m14_browser.py --redis-url redis://127.0.0.1:6379/14 --flush-redis-db

# Real stack verification
python scripts/verify_design_doc_real_stack.py
```

### Linting and Type Checking

The project does not currently have configured linters or type checkers in the repository. If you need to check code quality, use standard Python tools:

```bash
# Type checking (if needed)
mypy backend/

# Code formatting (if needed)
black backend/ tests/
```

## Architecture

### Backend Structure

```
backend/
├── main.py              # FastAPI app entry point
├── app.py               # App factory
├── config.py            # Settings (pydantic-settings, reads .env/.env.active)
├── database.py          # SQLAlchemy setup
├── models/              # SQLAlchemy ORM models
├── routers/             # FastAPI route handlers
├── services/            # Business logic
│   ├── vllm_client.py           # OpenAI-compatible LLM client
│   ├── sam_service.py           # SAM2 inference service
│   ├── auto_annotator.py        # Auto-annotation pipeline
│   ├── annotation_tasks.py      # Task queue handlers
│   ├── finetune_service.py      # LoRA fine-tuning
│   ├── evaluation_service.py    # Evaluation metrics
│   ├── postprocess.py           # Mask smoothing (OpenCV)
│   ├── dataset_io.py            # COCO/YOLO import/export
│   └── local_vllm_runtime.py    # Local vLLM process management
├── tasks/               # Redis task queue
│   ├── task_manager.py          # Task state management
│   ├── worker.py                # Task worker
│   └── job_handlers.py          # Job type registry
├── workflows/           # Workflow orchestration
└── utils/               # Utilities (GPU lock, storage, etc.)
```

### Frontend Structure

```
frontend/src/
├── main.tsx             # React entry point
├── App.tsx              # Root component with routing
├── api.ts               # API client
├── types.ts             # TypeScript types
├── pages/               # Page components
│   ├── ProjectList.tsx
│   ├── ImageList.tsx
│   └── ImageDetail.tsx
├── components/          # Reusable components
│   └── TaskTicker.tsx   # Task progress display
└── styles.css           # Global styles
```

**Note:** The frontend is currently migrating from Vue to React. Some documentation may still reference Vue components.

### Key Services

**vLLM Client (`services/vllm_client.py`):**
- Calls OpenAI-compatible `/v1/chat/completions` endpoint
- Uses guided JSON decoding with strict schema
- Supports model routing: `base`, `lora:{job_id}`, or direct model names
- Handles LoRA adapter loading/unloading via vLLM runtime API (if enabled)
- Automatically disables Qwen3 thinking mode for annotation tasks

**SAM Service (`services/sam_service.py`):**
- Singleton SAM2/SAM2.1 predictor
- Caches `set_image` embeddings per image_id
- Supports bbox and point-based prompts
- GPU lock for concurrent access control

**Auto Annotator (`services/auto_annotator.py`):**
- Orchestrates LLM → SAM → postprocessing pipeline
- Falls back to stub backend if real backend fails
- Records inference route metadata for debugging

**Fine-tuning (`services/finetune_service.py`):**
- Exports confirmed annotations to LLaMA-Factory JSONL format
- Generates training configs based on available VRAM
- Supports mock runner (for testing) and real LLaMA-Factory CLI
- Optional vLLM runtime LoRA loading after training

### Configuration System

**Three-tier configuration:**

1. **System settings** (`backend/config.py`): Environment variables from `.env` or `.env.active`
2. **Profile presets** (`configs/profiles/*.json`): Named configurations (dev_low_resource, test_real_stack, demo_prod)
3. **Project settings** (stored in `projects.config` JSON column): Per-project runtime settings

**Key environment variables:**
- `APP_PROFILE`: Profile name (dev_low_resource, test_real_stack, demo_prod)
- `ANNOTATION_BACKEND`: stub | openai_compatible
- `VLLM_BASE_URL`: vLLM service URL (default: http://127.0.0.1:8001)
- `VLLM_MODEL_NAME`: Logical model name for requests
- `VLLM_MODEL_SOURCE`: Physical model path/HF repo (for local vLLM startup)
- `REDIS_URL`: Redis connection string
- `TASK_EMBEDDED_WORKER`: true | false (run worker in main process or separately)
- `FINETUNE_BACKEND`: auto | mock | llamafactory
- `VLLM_ENABLE_RUNTIME_LORA_UPDATE`: Enable runtime LoRA loading/unloading

**Profile switching:**
The `start-linux.sh` script generates `.env.active` and `frontend/.env.local` from profile JSON files. To switch profiles, re-run the script with a different `--profile` argument.

### Model Routing

The system supports multiple model routing modes:

- **`base`**: Use the base LLM model (no LoRA)
- **`lora:{job_id}`**: Use a fine-tuned LoRA adapter from a completed fine-tuning job
- **Direct model name**: Use a specific model by name

Model routing is resolved per-project via `active_model_tag` in project settings. The `resolve_inference_route()` function in `vllm_client.py` handles routing logic.

**Runtime LoRA management:**
- If `VLLM_ENABLE_RUNTIME_LORA_UPDATE=true`, activating a LoRA calls vLLM's `/v1/load_lora_adapter` endpoint
- Otherwise, only project metadata is updated (requires manual vLLM restart)

### Task Queue

**Redis-based task system:**
- `RedisTaskManager` (`tasks/task_manager.py`): Task state persistence
- `RedisTaskWorker` (`tasks/worker.py`): Consumes annotation/evaluation/finetune queues
- WebSocket endpoint (`/ws/tasks/{task_id}`): Real-time progress updates
- Fallback to polling (`/api/tasks/{task_id}/status`) if WebSocket unavailable

**Task types:**
- `project_annotation`: Batch annotate multiple images
- `image_annotation`: Annotate single image
- `finetune`: Run LoRA fine-tuning
- `evaluation`: Run evaluation on val/test split

**GPU locking:**
- `GPULock` (`utils/gpu_lock.py`): Redis-based distributed lock
- Prevents OOM from concurrent vLLM/SAM/training processes
- Annotation tasks retry on lock timeout; interactive predict returns 409

### Database Schema

**SQLite with SQLAlchemy ORM:**

- `projects`: Project metadata, task_type (detection/segmentation), config JSON
- `images`: Uploaded images, status (pending/annotating/done/error), quality_score
- `annotations`: Bbox/mask/polygon annotations, source (auto/manual/corrected), is_confirmed
- `finetune_jobs`: Fine-tuning job status, lora_path, config snapshot
- `evaluation_runs`: Evaluation metrics, model_tag, config snapshot

**Coordinate conventions:**
- Database: Normalized 0-1, `[xmin, ymin, xmax, ymax]`
- SAM input: Pixel coordinates (converted at runtime)
- Frontend: Canvas coordinates (converted at render time)
- YOLO export: Normalized `[cx, cy, w, h]`
- COCO export: Pixel `[xmin, ymin, w, h]`

### Data Storage

```
data/
├── projects/{project_id}/
│   ├── images/          # Uploaded images
│   ├── masks/           # Binary mask PNGs
│   └── exports/         # Dataset exports
│       └── finetune/    # Fine-tuning datasets
│           └── job_{job_id}/
│               ├── project_{project_id}_train.jsonl
│               ├── dataset_info.json
│               └── llamafactory-train.yaml
└── system/
    └── runtime_settings.json  # System-level runtime settings

models/
├── sam2/                # SAM2 checkpoints
└── lora/{job_id}/       # LoRA adapters
```

## Common Workflows

### Adding a New API Endpoint

1. Define route in `backend/routers/` (e.g., `projects.py`)
2. Add business logic in `backend/services/`
3. Update ORM models in `backend/models/` if needed
4. Add tests in `tests/test_api_*.py`
5. Update frontend API client in `frontend/src/api.ts`

### Adding a New Task Type

1. Define handler function in `backend/services/` or `backend/tasks/`
2. Register in `backend/tasks/job_handlers.py`
3. Submit via `task_manager.submit_task(task_type, payload)`
4. Add tests in `tests/test_api_*.py`

### Modifying Auto-Annotation Pipeline

The pipeline is in `backend/services/auto_annotator.py`:
1. `generate_auto_annotations()`: Orchestrates LLM → SAM → postprocessing
2. `replace_auto_annotations()`: Writes results to database
3. Modify `vllm_client.py` for LLM changes
4. Modify `sam_service.py` for SAM changes
5. Modify `postprocess.py` for mask smoothing changes

### Adding a New Profile

1. Create `configs/profiles/{profile_name}.json`
2. Define `backend`, `frontend`, and `project_defaults` sections
3. Use with `bash scripts/start-linux.sh --profile {profile_name}`

## Important Notes

### GPU Memory Management

- vLLM, SAM, and fine-tuning compete for GPU memory
- Use `GPULock` for mutual exclusion
- Consider stopping vLLM before fine-tuning on low-memory GPUs
- The `start-linux.sh` script uses conservative vLLM memory settings by default

### Stub vs Real Backends

- **Stub backends** (default in dev_low_resource): Fast, CPU-friendly, generate synthetic data
- **Real backends** (test_real_stack, demo_prod): Require GPU, download models, slower but accurate
- Stub SAM generates realistic masks for testing the full pipeline without GPU

### Fine-tuning Considerations

- Fine-tuning is **optional** and **manually triggered**
- Only uses `is_confirmed=1` annotations (human-verified)
- Mock runner available for testing without LLaMA-Factory
- Real runner requires `llamafactory-cli` in PATH or `LLAMAFACTORY_CLI` env var

### Testing Strategy

- Unit tests use `fakeredis` and temporary SQLite databases
- Integration tests use real Redis (specify with `--redis-url`)
- Browser tests use Playwright for end-to-end validation
- Always run tests before committing changes to core services

### Coordinate System Pitfalls

- LLM outputs normalized 0-1 coordinates
- SAM expects pixel coordinates (multiply by image dimensions)
- Frontend canvas uses canvas-relative coordinates
- Always verify coordinate conversions when modifying annotation code

### WebSocket vs Polling

- WebSocket is preferred for real-time progress updates
- Frontend automatically falls back to polling if WebSocket fails
- Both methods query the same Redis task state

## Troubleshooting

**vLLM connection errors:**
- Check `VLLM_BASE_URL` is correct
- Verify vLLM is running: `curl http://127.0.0.1:8001/v1/models`
- Check vLLM logs for OOM or startup errors

**SAM errors:**
- Verify checkpoint path in project settings or `SAM_CHECKPOINT_PATH`
- Check GPU availability: `nvidia-smi`
- Try CPU mode: set `sam.device: "cpu"` in project settings

**Task queue not processing:**
- Check Redis is running: `redis-cli ping`
- Verify worker is running (or `TASK_EMBEDDED_WORKER=true`)
- Check worker logs for exceptions

**Fine-tuning fails:**
- Verify `llamafactory-cli` is available: `which llamafactory-cli`
- Check GPU memory: `nvidia-smi`
- Review fine-tuning logs in `logs/finetune/{job_id}.log`

**Frontend build errors:**
- Delete `node_modules` and `package-lock.json`, then `npm install`
- Check Node.js version (requires Node 18+)

## References

- Design document: `docs/design_doc.md`
- Development plan: `docs/dev_plan.md`
- OCI distribution plan: `docs/oci_distribution_plan.md`
