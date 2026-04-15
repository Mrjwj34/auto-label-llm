#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile="dev_low_resource"
venv_dir="$repo_root/.venv"
python_bin=""
api_host="127.0.0.1"
api_port="8000"
frontend_host="127.0.0.1"
frontend_port="5173"
redis_host="127.0.0.1"
redis_port="6379"
redis_url=""
with_vllm="auto"
with_sam3="auto"
with_llamafactory="auto"
download_sam3_checkpoint=0
sam3_version=""
run_tests=0
setup_only=0
skip_frontend_install=0
skip_system_deps=0
embedded_worker=0
start_frontend=1
refresh_python_deps=0
refresh_frontend_deps=0
refresh_optional_deps=0

vllm_model_source="${VLLM_MODEL_SOURCE:-}"
vllm_model_source_source=""
[[ -n "$vllm_model_source" ]] && vllm_model_source_source="env"

vllm_base_url="${VLLM_BASE_URL:-}"
vllm_base_url_source=""
[[ -n "$vllm_base_url" ]] && vllm_base_url_source="env"

vllm_served_model_name="${VLLM_SERVED_MODEL_NAME:-}"
vllm_served_model_name_source=""
[[ -n "$vllm_served_model_name" ]] && vllm_served_model_name_source="env"

vllm_host="127.0.0.1"
vllm_port="8001"

vllm_max_model_len="${VLLM_MAX_MODEL_LEN:-}"
vllm_max_model_len_source=""
[[ -n "$vllm_max_model_len" ]] && vllm_max_model_len_source="env"

vllm_gpu_memory_utilization="${VLLM_GPU_MEMORY_UTILIZATION:-}"
vllm_gpu_memory_utilization_source=""
[[ -n "$vllm_gpu_memory_utilization" ]] && vllm_gpu_memory_utilization_source="env"

vllm_max_num_seqs="${VLLM_MAX_NUM_SEQS:-}"
vllm_max_num_seqs_source=""
[[ -n "$vllm_max_num_seqs" ]] && vllm_max_num_seqs_source="env"

vllm_dtype="${VLLM_DTYPE:-}"
vllm_dtype_source=""
[[ -n "$vllm_dtype" ]] && vllm_dtype_source="env"

vllm_tensor_parallel_size="${VLLM_TENSOR_PARALLEL_SIZE:-}"
vllm_tensor_parallel_size_source=""
[[ -n "$vllm_tensor_parallel_size" ]] && vllm_tensor_parallel_size_source="env"

vllm_pipeline_parallel_size="${VLLM_PIPELINE_PARALLEL_SIZE:-}"
vllm_pipeline_parallel_size_source=""
[[ -n "$vllm_pipeline_parallel_size" ]] && vllm_pipeline_parallel_size_source="env"

vllm_max_num_batched_tokens="${VLLM_MAX_NUM_BATCHED_TOKENS:-}"
vllm_max_num_batched_tokens_source=""
[[ -n "$vllm_max_num_batched_tokens" ]] && vllm_max_num_batched_tokens_source="env"

vllm_swap_space="${VLLM_SWAP_SPACE:-}"
vllm_swap_space_source=""
[[ -n "$vllm_swap_space" ]] && vllm_swap_space_source="env"

vllm_cpu_offload_gb="${VLLM_CPU_OFFLOAD_GB:-}"
vllm_cpu_offload_gb_source=""
[[ -n "$vllm_cpu_offload_gb" ]] && vllm_cpu_offload_gb_source="env"

vllm_download_dir="${VLLM_DOWNLOAD_DIR:-}"
vllm_download_dir_source=""
[[ -n "$vllm_download_dir" ]] && vllm_download_dir_source="env"

vllm_start_timeout="${VLLM_START_TIMEOUT:-300}"
vllm_log_tail_lines="${VLLM_LOG_TAIL_LINES:-20}"
vllm_safe_mode=1
vllm_enforce_eager=0
vllm_enforce_eager_explicit=0
vllm_disable_custom_all_reduce=0
vllm_disable_custom_all_reduce_explicit=0

llamafactory_cli="${LLAMAFACTORY_CLI:-llamafactory-cli}"
finetune_backend="${FINETUNE_BACKEND:-auto}"

timestamp="$(date +%Y%m%d-%H%M%S)"
session_log_dir=""
setup_log_dir=""
managed_log_dir=""
state_dir=""
install_state_dir=""
vllm_help_cache_path=""
vllm_last_progress_snapshot=""
local_vllm_state_path=""

declare -a managed_pids=()
declare -a managed_pgids=()
declare -a vllm_extra_args=()
started_pid=""

usage() {
  cat <<'EOF'
Usage: bash scripts/start-linux.sh [options]

One command for Linux-based setup + profile activation + local service orchestration.
It can:
  1. auto-install missing system dependencies on Ubuntu/Debian,
  2. create/update the Python virtualenv and frontend deps with cache-aware install markers,
  3. write .env.active and frontend/.env.local from the selected profile,
  4. optionally run compileall + pytest + frontend build,
  5. start Redis / worker / backend / frontend / local vLLM with health checks and live startup logs.

Recommended smoke path:
  bash scripts/start-linux.sh --profile dev_low_resource --run-tests

Recommended real-stack path:
  VLLM_MODEL_SOURCE=Qwen/Qwen3-VL-8B-Instruct-FP8 \
  bash scripts/start-linux.sh --profile test_real_stack --with-vllm --with-sam --with-llamafactory

Options:
  --profile <name>                  Profile name. Default: dev_low_resource
  --venv <path>                     Virtualenv directory. Default: .venv
  --python <exe>                    Python executable used to create the venv
  --api-host <host>                 Backend bind host. Default: 127.0.0.1
  --api-port <port>                 Backend port. Default: 8000
  --frontend-host <host>            Frontend bind host. Default: 127.0.0.1
  --frontend-port <port>            Frontend port. Default: 5173
  --redis-host <host>               Redis host when using local managed Redis. Default: 127.0.0.1
  --redis-port <port>               Redis port when using local managed Redis. Default: 6379
  --redis-url <url>                 Full Redis URL. Default: redis://127.0.0.1:<port>/0
  --with-vllm                       Install/start local vLLM if needed
  --skip-vllm                       Do not install/start local vLLM
  --with-sam                        Install real SAM dependencies (SAM2 default, SAM3 legacy compatible)
  --skip-sam                        Skip real SAM dependencies
  --with-sam3                       Legacy alias of --with-sam
  --skip-sam3                       Legacy alias of --skip-sam
  --with-llamafactory               Install LLaMA-Factory CLI
  --skip-llamafactory               Skip LLaMA-Factory CLI installation
  --vllm-model-source <value>       Hugging Face id or local path for local vLLM
  --vllm-base-url <url>             OpenAI-compatible base URL. Default: VLLM_BASE_URL or http://127.0.0.1:8001
  --vllm-served-model-name <value>  Served model name for local vLLM; defaults to profile VLLM_MODEL_NAME
  --vllm-host <host>                Local vLLM bind host. Default: 127.0.0.1
  --vllm-port <port>                Local vLLM bind port. Default: 8001
  --vllm-max-model-len <n>          Optional vLLM max model length override
  --vllm-gpu-memory-utilization <f> Optional vLLM GPU memory fraction override
  --vllm-max-num-seqs <n>           Optional vLLM max concurrent sequences override
  --vllm-dtype <value>              Optional vLLM dtype, e.g. half / bfloat16 / auto
  --vllm-tensor-parallel-size <n>   Optional vLLM tensor parallel size
  --vllm-pipeline-parallel-size <n> Optional vLLM pipeline parallel size
  --vllm-max-num-batched-tokens <n> Optional vLLM max batched tokens
  --vllm-swap-space <gb>            Optional vLLM CPU swap-space in GiB
  --vllm-cpu-offload-gb <gb>        Optional vLLM CPU offload size in GiB
  --vllm-download-dir <path>        Optional vLLM model download cache dir
  --vllm-start-timeout <sec>        vLLM readiness timeout. Default: 300
  --vllm-log-tail-lines <n>         Startup log lines to stream each round. Default: 20
  --vllm-enforce-eager              Add --enforce-eager when starting local vLLM
  --vllm-disable-custom-all-reduce  Add --disable-custom-all-reduce when starting local vLLM
  --vllm-no-safe-mode               Disable conservative vLLM auto-tuning / clamping
  --vllm-arg <token>                Append one raw extra token to the vLLM command; repeat as needed
  --llamafactory-cli <command>      CLI used by backend FINETUNE_BACKEND=auto. Default: llamafactory-cli
  --download-sam-checkpoint         Download the configured SAM checkpoint family
  --sam-version <sam2|sam2.1|sam3|sam3.1>
                                    Checkpoint family when downloading; auto by profile
  --download-sam3-checkpoint        Legacy alias of --download-sam-checkpoint
  --sam3-version <sam3|sam3.1>      Legacy alias of --sam-version
  --run-tests                       Run compileall + pytest + frontend build before startup
  --setup-only                      Stop after environment setup and optional tests
  --skip-frontend-install           Skip npm ci / npm install
  --skip-system-deps                Do not try to apt-install missing Linux packages
  --embedded-worker                 Keep TASK_EMBEDDED_WORKER=true and do not start a standalone worker
  --no-frontend                     Do not start the frontend dev server
  --refresh-python-deps             Force reinstall requirements.txt inside the venv
  --refresh-frontend-deps           Force reinstall frontend dependencies
  --refresh-optional-deps           Force reinstall optional packages such as vLLM / SAM / LLaMA-Factory
  --refresh-all-deps                Force reinstall every managed dependency bucket
  -h, --help                        Show this help

Environment overrides:
  PYTHON_BIN                 Preferred Python executable
  TORCH_PIP_SPEC             Torch packages. Default: "torch torchvision"
  TORCH_EXTRA_INDEX_URL      Torch wheel index. Default: https://download.pytorch.org/whl/cu126
  SAM_PIP_SPEC               SAM packages. Default: "git+https://github.com/facebookresearch/sam2.git huggingface_hub pycocotools"
  SAM3_PIP_SPEC              Legacy override for SAM3 packages
  VLLM_PIP_SPEC              vLLM packages. Default: "vllm"
  LLAMAFACTORY_PIP_SPEC      LLaMA-Factory packages. Default: "llamafactory bitsandbytes"
  VLLM_MAX_MODEL_LEN         Optional vLLM max context length override
  VLLM_GPU_MEMORY_UTILIZATION Optional vLLM GPU memory fraction override
  VLLM_MAX_NUM_SEQS          Optional vLLM max concurrent sequences override
  VLLM_DTYPE                 Optional vLLM dtype override
  VLLM_TENSOR_PARALLEL_SIZE  Optional vLLM tensor parallel size
  VLLM_PIPELINE_PARALLEL_SIZE Optional vLLM pipeline parallel size
  VLLM_MAX_NUM_BATCHED_TOKENS Optional vLLM max batched tokens
  VLLM_SWAP_SPACE            Optional vLLM swap-space in GiB
  VLLM_CPU_OFFLOAD_GB        Optional vLLM CPU offload in GiB
  VLLM_DOWNLOAD_DIR          Optional vLLM model download dir
  VLLM_START_TIMEOUT         vLLM readiness timeout in seconds
  VLLM_LOG_TAIL_LINES        Number of log lines to stream while vLLM starts
EOF
}

log() {
  printf '[start-linux] %s\n' "$*"
}

warn() {
  printf '[start-linux] WARN: %s\n' "$*" >&2
}

die() {
  printf '[start-linux] ERROR: %s\n' "$*" >&2
  exit 1
}

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|Yes|on|ON|On)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

cleanup() {
  local index
  for (( index=${#managed_pids[@]}-1; index>=0; index-- )); do
    local pid="${managed_pids[$index]}"
    local pgid="${managed_pgids[$index]:-}"
    if [[ "$pgid" =~ ^[0-9]+$ && "$pgid" -gt 1 ]]; then
      kill -TERM -- "-$pgid" >/dev/null 2>&1 || true
      sleep 0.2
      kill -KILL -- "-$pgid" >/dev/null 2>&1 || true
    fi
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
    fi
  done
  if [[ -n "$local_vllm_state_path" ]]; then
    local state_pid
    state_pid="$(current_local_vllm_state_pid 2>/dev/null || echo 0)"
    if [[ "$state_pid" =~ ^[0-9]+$ && "$state_pid" -gt 0 ]] && kill -0 "$state_pid" >/dev/null 2>&1; then
      local state_pgid
      state_pgid="$(ps -o pgid= -p "$state_pid" 2>/dev/null | tr -d '[:space:]' || true)"
      if [[ "$state_pgid" =~ ^[0-9]+$ && "$state_pgid" -gt 1 ]]; then
        kill -TERM -- "-$state_pgid" >/dev/null 2>&1 || true
        sleep 0.2
        kill -KILL -- "-$state_pgid" >/dev/null 2>&1 || true
      fi
      kill "$state_pid" >/dev/null 2>&1 || true
      wait "$state_pid" >/dev/null 2>&1 || true
    fi
    rm -f "$local_vllm_state_path" >/dev/null 2>&1 || true
  fi
}

tail_last_lines() {
  local path="$1"
  local lines="${2:-40}"
  if [[ -f "$path" ]]; then
    printf '\n----- %s (last %s lines) -----\n' "$path" "$lines" >&2
    tail -n "$lines" "$path" >&2 || true
  fi
}

count_log_lines() {
  local path="$1"
  if [[ -f "$path" ]]; then
    wc -l <"$path" 2>/dev/null || echo 0
  else
    echo 0
  fi
}

json_array_from_words() {
  "$venv_python" - "$@" <<'PY'
from __future__ import annotations

import json
import sys

print(json.dumps(sys.argv[1:], ensure_ascii=False))
PY
}

clear_local_vllm_runtime_state() {
  [[ -n "$local_vllm_state_path" ]] || return 0
  rm -f "$local_vllm_state_path" >/dev/null 2>&1 || true
}

write_local_vllm_runtime_state() {
  local pid="$1"
  local log_path="$2"
  local supports_enable_lora="$3"
  local env_unset_json="$4"
  local env_set_json="$5"
  local command_json="$6"
  local start_timeout="$7"
  [[ -n "$local_vllm_state_path" ]] || return 0

  "$venv_python" - \
    "$local_vllm_state_path" \
    "$repo_root" \
    "$vllm_base_url" \
    "$vllm_host" \
    "$vllm_port" \
    "$vllm_model_source" \
    "$vllm_served_model_name" \
    "$pid" \
    "$log_path" \
    "$supports_enable_lora" \
    "$env_unset_json" \
    "$env_set_json" \
    "$command_json" \
    "$start_timeout" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

state_path = Path(sys.argv[1]).resolve()
repo_root = Path(sys.argv[2]).resolve()
base_url = sys.argv[3]
host = sys.argv[4]
port = int(sys.argv[5])
model_source = sys.argv[6]
served_model_name = sys.argv[7]
pid = int(sys.argv[8])
log_path = str(Path(sys.argv[9]).resolve())
supports_enable_lora = sys.argv[10] == "1"
env_unset = json.loads(sys.argv[11])
env_set = json.loads(sys.argv[12])
command = json.loads(sys.argv[13])
start_timeout = int(sys.argv[14])

payload = {
    "version": 1,
    "managed_by": "scripts/start-linux.sh",
    "repo_root": repo_root.as_posix(),
    "cwd": repo_root.as_posix(),
    "base_url": base_url,
    "host": host,
    "port": port,
    "model_source": model_source,
    "served_model_name": served_model_name,
    "pid": pid,
    "log_path": log_path,
    "env_unset": env_unset,
    "env_set": env_set,
    "command": command,
    "start_timeout": start_timeout,
    "supports_enable_lora": supports_enable_lora,
    "started_at": datetime.now(timezone.utc).isoformat(),
}
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

current_local_vllm_state_pid() {
  [[ -n "$local_vllm_state_path" && -f "$local_vllm_state_path" ]] || {
    echo 0
    return 0
  }

  "$venv_python" - "$local_vllm_state_path" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print(0)
    raise SystemExit(0)

if not isinstance(payload, dict):
    print(0)
    raise SystemExit(0)

try:
    print(int(payload.get("pid") or 0))
except Exception:
    print(0)
PY
}

format_bytes() {
  local bytes="${1:-0}"
  local units=("B" "KiB" "MiB" "GiB" "TiB" "PiB")
  local unit_index=0
  local whole=0
  local remainder=0
  local decimal=0

  if [[ "$bytes" =~ ^[0-9]+$ ]]; then
    whole="$bytes"
  fi

  while (( whole >= 1024 && unit_index < ${#units[@]} - 1 )); do
    remainder=$((whole % 1024))
    whole=$((whole / 1024))
    unit_index=$((unit_index + 1))
  done

  if (( unit_index == 0 || whole >= 10 || remainder == 0 )); then
    printf '%s%s' "$whole" "${units[$unit_index]}"
    return 0
  fi

  decimal=$(((remainder * 10) / 1024))
  printf '%s.%s%s' "$whole" "$decimal" "${units[$unit_index]}"
}

resolve_hf_hub_cache_dir() {
  if [[ -n "${HUGGINGFACE_HUB_CACHE:-}" ]]; then
    printf '%s\n' "$HUGGINGFACE_HUB_CACHE"
    return 0
  fi
  if [[ -n "${HF_HOME:-}" ]]; then
    printf '%s\n' "${HF_HOME%/}/hub"
    return 0
  fi
  if [[ -d /workspace/.hf_home/hub ]]; then
    printf '%s\n' "/workspace/.hf_home/hub"
    return 0
  fi
  printf '%s\n' "${HOME}/.cache/huggingface/hub"
}

resolve_hf_xet_cache_dir() {
  if [[ -n "${HF_XET_CACHE:-}" ]]; then
    printf '%s\n' "$HF_XET_CACHE"
    return 0
  fi
  if [[ -n "${HF_HOME:-}" ]]; then
    printf '%s\n' "${HF_HOME%/}/xet"
    return 0
  fi
  if [[ -d /workspace/.hf_home/xet ]]; then
    printf '%s\n' "/workspace/.hf_home/xet"
    return 0
  fi
  printf '%s\n' "${HOME}/.cache/huggingface/xet"
}

build_hf_repo_cache_dir() {
  local model_source="$1"
  if [[ "$model_source" != */* || "$model_source" == /* || "$model_source" == http*://* ]]; then
    return 1
  fi

  local hub_cache_dir
  hub_cache_dir="$(resolve_hf_hub_cache_dir)"
  printf '%s/models--%s\n' "$hub_cache_dir" "${model_source//\//--}"
}

find_local_sam_checkpoint() {
  local wanted="${1:-sam2}"
  local python_exe="${venv_python:-${system_python:-python3}}"
  "$python_exe" - "$repo_root" "$wanted" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
wanted = str(sys.argv[2] or "sam2").strip().casefold()
family = "sam3" if ("sam3" in wanted or "3.1" in wanted) else "sam2"
model_dir = repo_root / "models" / family
if not model_dir.exists():
    raise SystemExit(1)

candidates = sorted(
    [path for path in model_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".pt", ".pth"}],
    key=lambda path: path.name.casefold(),
)
if not candidates:
    raise SystemExit(1)

wanted_tags: list[str] = []
if family == "sam3":
    if "3.1" in wanted:
        wanted_tags.extend(["3.1", "sam3.1", "multiplex"])
    elif wanted == "sam3":
        wanted_tags.extend(["sam3", "3.1", "multiplex"])
    elif wanted:
        wanted_tags.append(wanted)
else:
    if "2.1" in wanted:
        wanted_tags.extend(["sam2.1", "2.1"])
    elif wanted in {"", "sam2"}:
        wanted_tags.extend(["sam2.1", "2.1", "sam2"])
    else:
        wanted_tags.append(wanted)

    if any(tag in wanted for tag in ("tiny", "hiera_t", "_t")):
        wanted_tags.extend(["tiny", "hiera_t"])
    elif any(tag in wanted for tag in ("small", "hiera_s", "_s")):
        wanted_tags.extend(["small", "hiera_s"])
    elif any(tag in wanted for tag in ("base_plus", "base+", "b+", "hiera_b")):
        wanted_tags.extend(["base_plus", "base+", "b+", "hiera_b"])
    else:
        wanted_tags.extend(["large", "hiera_l"])

selected = None
for tag in wanted_tags:
    for candidate in candidates:
        if tag in candidate.name.casefold():
            selected = candidate
            break
    if selected is not None:
        break
if selected is None:
    selected = candidates[0]

print(selected.resolve())
PY
}

has_hf_hub_auth() {
  if [[ -n "${HF_TOKEN:-}" || -n "${HUGGING_FACE_HUB_TOKEN:-}" ]]; then
    return 0
  fi
  if [[ -n "${HF_HOME:-}" && -f "${HF_HOME%/}/token" ]]; then
    return 0
  fi
  if [[ -f "${HOME}/.cache/huggingface/token" ]]; then
    return 0
  fi
  if [[ -f "${HOME}/.huggingface/token" ]]; then
    return 0
  fi
  return 1
}

emit_local_vllm_progress() {
  local model_source="${1:-}"
  local repo_cache_dir=""
  local cache_bytes=""
  local incomplete_count=""
  local incomplete_bytes=""
  local xet_cache_dir=""
  local xet_bytes=""
  local gpu_memory_used=""
  local summary=""

  if [[ -n "$model_source" ]]; then
    repo_cache_dir="$(build_hf_repo_cache_dir "$model_source" 2>/dev/null || true)"
  fi

  if [[ -n "$repo_cache_dir" && -d "$repo_cache_dir" ]]; then
    cache_bytes="$(du -sb "$repo_cache_dir" 2>/dev/null | awk '{print $1}')"
    incomplete_count="$(find "$repo_cache_dir" -type f -name '*.incomplete' 2>/dev/null | wc -l | tr -d ' ')"
    incomplete_bytes="$(
      find "$repo_cache_dir" -type f -name '*.incomplete' -printf '%s\n' 2>/dev/null \
        | awk '{sum += $1} END {print sum + 0}'
    )"
  fi

  xet_cache_dir="$(resolve_hf_xet_cache_dir)"
  if [[ -d "$xet_cache_dir" ]]; then
    xet_bytes="$(du -sb "$xet_cache_dir" 2>/dev/null | awk '{print $1}')"
  fi

  if command -v nvidia-smi >/dev/null 2>&1; then
    gpu_memory_used="$(
      nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null \
        | head -n 1 \
        | tr -d ' '
    )"
  fi

  if [[ -n "$gpu_memory_used" ]]; then
    summary+="gpu=${gpu_memory_used}MiB"
  fi
  if [[ -n "$cache_bytes" ]]; then
    [[ -n "$summary" ]] && summary+=", "
    summary+="hub_cache=$(format_bytes "$cache_bytes")"
  fi
  if [[ -n "$incomplete_count" && "$incomplete_count" != "0" ]]; then
    [[ -n "$summary" ]] && summary+=", "
    summary+="incomplete=$(format_bytes "${incomplete_bytes:-0}") in ${incomplete_count} file(s)"
  fi
  if [[ -n "$xet_bytes" ]]; then
    [[ -n "$summary" ]] && summary+=", "
    summary+="xet_cache=$(format_bytes "$xet_bytes")"
  fi

  if [[ -z "$summary" || "$summary" == "$vllm_last_progress_snapshot" ]]; then
    return 1
  fi

  vllm_last_progress_snapshot="$summary"
  log "Local vLLM progress: $summary"
  return 0
}

emit_new_log_lines() {
  local path="$1"
  local seen_lines="$2"
  local max_lines="${3:-20}"
  local total_lines

  total_lines="$(count_log_lines "$path")"
  if (( total_lines <= seen_lines )); then
    printf '%s\n' "$seen_lines"
    return 0
  fi

  local start_line=$((seen_lines + 1))
  if (( total_lines - start_line + 1 > max_lines )); then
    start_line=$((total_lines - max_lines + 1))
  fi
  sed -n "${start_line},${total_lines}p" "$path" >&2 || true
  printf '%s\n' "$total_lines"
}

run_logged_step() {
  local description="$1"
  local log_path="$2"
  shift 2

  log "$description"
  if "$@" >"$log_path" 2>&1; then
    log "$description completed."
    return 0
  fi

  tail_last_lines "$log_path" 80
  die "$description failed. Full log: $log_path"
}

run_logged_step_in_dir() {
  local description="$1"
  local log_path="$2"
  local workdir="$3"
  shift 3

  log "$description"
  if (
    cd "$workdir"
    "$@"
  ) >"$log_path" 2>&1; then
    log "$description completed."
    return 0
  fi

  tail_last_lines "$log_path" 80
  die "$description failed. Full log: $log_path"
}

compute_fingerprint() {
  local python_exe="$1"
  shift
  "$python_exe" - "$@" <<'PY'
from __future__ import annotations

import hashlib
import sys

h = hashlib.sha256()
for item in sys.argv[1:]:
    if item.startswith("file:"):
        path = item[5:]
        h.update(f"file:{path}\n".encode("utf-8"))
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
    else:
        h.update(f"str:{item}\n".encode("utf-8"))
print(h.hexdigest())
PY
}

run_cached_step() {
  local marker_name="$1"
  local fingerprint="$2"
  local force_run="$3"
  local description="$4"
  shift 4

  local marker_path="$install_state_dir/${marker_name}.sha256"
  local log_path="$setup_log_dir/${marker_name}.log"
  local current=""
  if [[ -f "$marker_path" ]]; then
    current="$(<"$marker_path")"
  fi

  if [[ "$force_run" -eq 0 && "$current" == "$fingerprint" ]]; then
    log "Reusing $description (cache hit)"
    return 0
  fi

  run_logged_step "$description" "$log_path" "$@"
  printf '%s\n' "$fingerprint" >"$marker_path"
}

http_is_ready() {
  local url="$1"
  "$venv_python" - "$url" <<'PY'
from __future__ import annotations

import sys
import urllib.error
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=2.0) as response:
        if 200 <= response.status < 500:
            raise SystemExit(0)
except Exception:
    raise SystemExit(1)
PY
}

wait_for_any_url() {
  local timeout_seconds="$1"
  shift
  local deadline=$((SECONDS + timeout_seconds))
  local url

  while (( SECONDS < deadline )); do
    for url in "$@"; do
      if http_is_ready "$url" >/dev/null 2>&1; then
        return 0
      fi
    done
    sleep 1
  done

  return 1
}

wait_for_service_ready() {
  local name="$1"
  local pid="$2"
  local timeout_seconds="$3"
  local log_path="$4"
  shift 4
  local probe_urls=("$@")

  local deadline=$((SECONDS + timeout_seconds))
  local last_notice=-1000
  local seen_lines=0
  local current_lines=0
  local url=""

  while (( SECONDS < deadline )); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      warn "$name exited before becoming healthy."
      tail_last_lines "$log_path" 80
      return 1
    fi

    for url in "${probe_urls[@]}"; do
      if http_is_ready "$url" >/dev/null 2>&1; then
        return 0
      fi
    done

    current_lines="$(count_log_lines "$log_path")"
    if (( current_lines > seen_lines )); then
      log "$name is still starting; recent log output:"
      seen_lines="$(emit_new_log_lines "$log_path" "$seen_lines" "$vllm_log_tail_lines")"
      if [[ "$name" == "Local vLLM" ]]; then
        deadline=$((SECONDS + timeout_seconds))
      fi
      last_notice="$SECONDS"
    elif [[ "$name" == "Local vLLM" ]] && emit_local_vllm_progress "$vllm_model_source"; then
      deadline=$((SECONDS + timeout_seconds))
      last_notice="$SECONDS"
    elif (( SECONDS - last_notice >= 10 )); then
      log "$name is still starting... (waiting up to ${timeout_seconds}s, log: $log_path)"
      last_notice="$SECONDS"
    fi

    sleep 2
  done

  warn "$name did not become healthy within ${timeout_seconds}s."
  tail_last_lines "$log_path" 80
  return 1
}

build_vllm_probe_urls() {
  local base_url="$1"
  "$venv_python" - "$base_url" <<'PY'
from __future__ import annotations

import sys
from urllib.parse import urlparse, urlunparse

raw = sys.argv[1].rstrip("/")
parsed = urlparse(raw)
scheme = parsed.scheme or "http"
if parsed.netloc:
    netloc = parsed.netloc
    path = parsed.path.rstrip("/")
else:
    netloc = parsed.path
    path = ""

origin = urlunparse((scheme, netloc, "", "", "", ""))
if path.endswith("/v1"):
    print(f"{origin}/health")
    print(f"{origin}{path}/models")
elif path:
    print(f"{origin}{path}/health")
    print(f"{origin}{path}/v1/models")
else:
    print(f"{origin}/health")
    print(f"{origin}/v1/models")
PY
}

ensure_vllm_help_cache() {
  [[ -n "$vllm_help_cache_path" ]] || vllm_help_cache_path="$setup_log_dir/vllm-api-server-help.txt"
  if [[ -s "$vllm_help_cache_path" ]]; then
    return 0
  fi

  "$venv_python" -m vllm.entrypoints.openai.api_server --help >"$vllm_help_cache_path" 2>&1 || {
    tail_last_lines "$vllm_help_cache_path" 80
    die "Failed to inspect local vLLM CLI help."
  }
}

vllm_supports_argument() {
  local argument="$1"
  ensure_vllm_help_cache
  grep -F -- "$argument" "$vllm_help_cache_path" >/dev/null 2>&1
}

append_vllm_value_option() {
  local option="$1"
  shift
  if vllm_supports_argument "$option"; then
    vllm_command+=("$option" "$@")
  else
    warn "Skipping unsupported vLLM option for this installed version: $option"
  fi
}

append_vllm_flag_option() {
  local option="$1"
  if vllm_supports_argument "$option"; then
    vllm_command+=("$option")
  else
    warn "Skipping unsupported vLLM flag for this installed version: $option"
  fi
}

ping_redis_url() {
  local url="$1"
  "$venv_python" - "$url" <<'PY'
from __future__ import annotations

import sys

import redis

client = redis.Redis.from_url(
    sys.argv[1],
    decode_responses=True,
    socket_connect_timeout=2.0,
    socket_timeout=2.0,
)
client.ping()
PY
}

start_service() {
  local name="$1"
  shift
  local log_path="$managed_log_dir/${name}.log"
  log "Starting $name (log: $log_path)"
  (
    cd "$repo_root"
    if command -v setsid >/dev/null 2>&1; then
      if command -v stdbuf >/dev/null 2>&1; then
        exec setsid stdbuf -oL -eL "$@"
      else
        exec setsid "$@"
      fi
    else
      if command -v stdbuf >/dev/null 2>&1; then
        exec stdbuf -oL -eL "$@"
      else
        exec "$@"
      fi
    fi
  ) >"$log_path" 2>&1 &
  started_pid="$!"
  local started_pgid="$started_pid"
  local resolved_pgid
  resolved_pgid="$(ps -o pgid= -p "$started_pid" 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ "$resolved_pgid" =~ ^[0-9]+$ && "$resolved_pgid" -gt 1 ]]; then
    started_pgid="$resolved_pgid"
  fi
  managed_pids+=("$started_pid")
  managed_pgids+=("$started_pgid")
}

node_major_version() {
  if ! command -v node >/dev/null 2>&1; then
    echo 0
    return
  fi
  local raw
  raw="$(node -p "process.versions.node.split('.')[0]" 2>/dev/null || echo 0)"
  echo "${raw:-0}"
}

ensure_apt_packages() {
  local packages=("$@")
  [[ ${#packages[@]} -gt 0 ]] || return 0
  if [[ "$skip_system_deps" -eq 1 ]]; then
    die "Missing required Linux packages: ${packages[*]}. Re-run without --skip-system-deps."
  fi
  command -v apt-get >/dev/null 2>&1 || die "Automatic package install currently supports apt-based Linux only."
  [[ ${#sudo_cmd[@]} -gt 0 || "$(id -u)" -eq 0 ]] || die "Need root/sudo to install missing Linux packages: ${packages[*]}"
  log "Installing apt packages: ${packages[*]}"
  "${sudo_cmd[@]}" apt-get update -y
  DEBIAN_FRONTEND=noninteractive "${sudo_cmd[@]}" apt-get install -y "${packages[@]}"
}

ensure_node_22() {
  local current_major
  current_major="$(node_major_version)"
  if (( current_major >= 20 )); then
    return 0
  fi
  if [[ "$skip_system_deps" -eq 1 ]]; then
    die "Node.js >= 20 is required (current major: ${current_major}). Re-run without --skip-system-deps."
  fi
  command -v apt-get >/dev/null 2>&1 || die "Automatic Node.js installation currently supports apt-based Linux only."
  [[ ${#sudo_cmd[@]} -gt 0 || "$(id -u)" -eq 0 ]] || die "Need root/sudo to install Node.js 22."
  log "Installing Node.js 22 from NodeSource."
  "${sudo_cmd[@]}" apt-get update -y
  ensure_apt_packages ca-certificates curl gnupg
  if [[ ${#sudo_cmd[@]} -gt 0 ]]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | "${sudo_cmd[@]}" -E bash -
  else
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  fi
  DEBIAN_FRONTEND=noninteractive "${sudo_cmd[@]}" apt-get install -y nodejs
}

choose_python() {
  local candidate
  if [[ -n "${python_bin}" ]]; then
    command -v "$python_bin" >/dev/null 2>&1 || die "Python executable not found: $python_bin"
    echo "$python_bin"
    return
  fi
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    command -v "${PYTHON_BIN}" >/dev/null 2>&1 || die "Python executable not found: ${PYTHON_BIN}"
    echo "${PYTHON_BIN}"
    return
  fi
  for candidate in python3.11 python3.10 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return
    fi
  done
  die "No suitable Python executable found. Install python3 and python3-venv first."
}

create_virtualenv() {
  if "$system_python" -m venv "$venv_dir"; then
    return 0
  fi
  if ! "$system_python" -m pip --version >/dev/null 2>&1; then
    die "Failed to create virtualenv via stdlib venv, and system pip is unavailable for a virtualenv fallback."
  fi
  log "Falling back to virtualenv because stdlib venv did not succeed."
  "$system_python" -m pip install --user virtualenv
  "$system_python" -m virtualenv "$venv_dir"
}

ensure_base_tools() {
  local packages=()
  command -v git >/dev/null 2>&1 || packages+=(git)
  command -v curl >/dev/null 2>&1 || packages+=(curl)
  command -v redis-server >/dev/null 2>&1 || packages+=(redis-server)
  command -v redis-cli >/dev/null 2>&1 || packages+=(redis-tools)
  command -v "$system_python" >/dev/null 2>&1 || packages+=(python3 python3-venv python3-pip)
  if [[ "$with_vllm" == "yes" || "$with_llamafactory" == "yes" ]]; then
    command -v gcc >/dev/null 2>&1 || packages+=(build-essential)
  fi
  ensure_apt_packages "${packages[@]}"
  if [[ "$skip_frontend_install" -ne 1 || ( "$setup_only" -ne 1 && "$start_frontend" -eq 1 ) ]]; then
    ensure_node_22
  fi
}

detect_visible_gpu_memory_mib() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo 0
    return
  fi
  nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1 | tr -d ' ' || echo 0
}

normalize_local_model_source() {
  local raw="$1"
  if [[ -z "$raw" || "$raw" == /* ]]; then
    printf '%s\n' "$raw"
    return
  fi

  if [[ -e "$raw" ]]; then
    (cd "$(dirname "$raw")" && printf '%s/%s\n' "$(pwd)" "$(basename "$raw")")
    return
  fi

  if [[ -e "$repo_root/$raw" ]]; then
    printf '%s\n' "$repo_root/$raw"
    return
  fi

  printf '%s\n' "$raw"
}

apply_vllm_safe_defaults() {
  local gpu_mib="$1"
  local safe_max_model_len=""
  local safe_gpu_util=""
  local safe_max_num_seqs=""
  local safe_max_num_batched_tokens=""
  local safe_swap_space=""
  local safe_cpu_offload_gb=""

  if [[ "$vllm_safe_mode" -ne 1 ]]; then
    return 0
  fi

  if [[ "$gpu_mib" =~ ^[0-9]+$ ]] && (( gpu_mib > 0 )); then
    if (( gpu_mib <= 12288 )); then
      safe_max_model_len="1024"
      safe_gpu_util="0.68"
      safe_max_num_seqs="1"
      safe_max_num_batched_tokens="512"
      safe_swap_space="8"
      safe_cpu_offload_gb="12"
    elif (( gpu_mib <= 18432 )); then
      safe_max_model_len="2048"
      safe_gpu_util="0.72"
      safe_max_num_seqs="1"
      safe_max_num_batched_tokens="1024"
      safe_swap_space="8"
      safe_cpu_offload_gb="8"
    elif (( gpu_mib < 24000 )); then
      safe_max_model_len="4096"
      safe_gpu_util="0.82"
      safe_max_num_seqs="1"
      safe_max_num_batched_tokens="2048"
      safe_swap_space="8"
      safe_cpu_offload_gb="4"
    else
      safe_max_model_len="8192"
      safe_gpu_util="0.90"
      safe_max_num_seqs="2"
      safe_max_num_batched_tokens="4096"
      safe_swap_space="4"
      safe_cpu_offload_gb="0"
    fi
  else
    safe_max_model_len="4096"
    safe_gpu_util="0.82"
    safe_max_num_seqs="1"
    safe_max_num_batched_tokens="2048"
    safe_swap_space="8"
    safe_cpu_offload_gb="4"
  fi

  if [[ -z "$vllm_max_model_len" ]]; then
    vllm_max_model_len="$safe_max_model_len"
    vllm_max_model_len_source="auto"
  elif [[ "$vllm_max_model_len_source" == "profile" && "$vllm_max_model_len" =~ ^[0-9]+$ && "$safe_max_model_len" =~ ^[0-9]+$ && "$vllm_max_model_len" -gt "$safe_max_model_len" ]]; then
    warn "Profile requested VLLM_MAX_MODEL_LEN=$vllm_max_model_len, but safe mode clamps it to $safe_max_model_len for this GPU."
    vllm_max_model_len="$safe_max_model_len"
    vllm_max_model_len_source="auto-clamped"
  fi

  if [[ -z "$vllm_gpu_memory_utilization" ]]; then
    vllm_gpu_memory_utilization="$safe_gpu_util"
    vllm_gpu_memory_utilization_source="auto"
  elif [[ "$vllm_gpu_memory_utilization_source" == "profile" ]]; then
    local current_util
    current_util="$(printf '%s\n%s\n' "$vllm_gpu_memory_utilization" "$safe_gpu_util" | sort -g | tail -n 1)"
    if [[ "$current_util" == "$vllm_gpu_memory_utilization" && "$vllm_gpu_memory_utilization" != "$safe_gpu_util" ]]; then
      warn "Profile requested VLLM_GPU_MEMORY_UTILIZATION=$vllm_gpu_memory_utilization, but safe mode clamps it to $safe_gpu_util."
      vllm_gpu_memory_utilization="$safe_gpu_util"
      vllm_gpu_memory_utilization_source="auto-clamped"
    fi
  fi

  if [[ -z "$vllm_max_num_seqs" ]]; then
    vllm_max_num_seqs="$safe_max_num_seqs"
    vllm_max_num_seqs_source="auto"
  elif [[ "$vllm_max_num_seqs_source" == "profile" && "$vllm_max_num_seqs" =~ ^[0-9]+$ && "$safe_max_num_seqs" =~ ^[0-9]+$ && "$vllm_max_num_seqs" -gt "$safe_max_num_seqs" ]]; then
    warn "Profile requested VLLM_MAX_NUM_SEQS=$vllm_max_num_seqs, but safe mode clamps it to $safe_max_num_seqs."
    vllm_max_num_seqs="$safe_max_num_seqs"
    vllm_max_num_seqs_source="auto-clamped"
  fi

  if [[ -z "$vllm_dtype" ]]; then
    vllm_dtype="half"
    vllm_dtype_source="auto"
  fi

  if [[ -z "$vllm_max_num_batched_tokens" ]]; then
    vllm_max_num_batched_tokens="$safe_max_num_batched_tokens"
    vllm_max_num_batched_tokens_source="auto"
  elif [[ "$vllm_max_num_batched_tokens_source" == "profile" && "$vllm_max_num_batched_tokens" =~ ^[0-9]+$ && "$safe_max_num_batched_tokens" =~ ^[0-9]+$ && "$vllm_max_num_batched_tokens" -gt "$safe_max_num_batched_tokens" ]]; then
    warn "Profile requested VLLM_MAX_NUM_BATCHED_TOKENS=$vllm_max_num_batched_tokens, but safe mode clamps it to $safe_max_num_batched_tokens."
    vllm_max_num_batched_tokens="$safe_max_num_batched_tokens"
    vllm_max_num_batched_tokens_source="auto-clamped"
  fi

  if [[ -z "$vllm_swap_space" ]]; then
    vllm_swap_space="$safe_swap_space"
    vllm_swap_space_source="auto"
  fi

  if [[ -z "$vllm_cpu_offload_gb" ]]; then
    if [[ -n "$safe_cpu_offload_gb" && "$safe_cpu_offload_gb" != "0" ]]; then
      vllm_cpu_offload_gb="$safe_cpu_offload_gb"
      vllm_cpu_offload_gb_source="auto"
    fi
  elif [[ "$vllm_cpu_offload_gb_source" == "profile" && "$vllm_cpu_offload_gb" =~ ^[0-9]+$ && "$safe_cpu_offload_gb" =~ ^[0-9]+$ && "$safe_cpu_offload_gb" -gt "$vllm_cpu_offload_gb" ]]; then
    warn "Profile requested VLLM_CPU_OFFLOAD_GB=$vllm_cpu_offload_gb, but safe mode raises it to $safe_cpu_offload_gb for this GPU."
    vllm_cpu_offload_gb="$safe_cpu_offload_gb"
    vllm_cpu_offload_gb_source="auto-clamped"
  fi

  if [[ "$vllm_enforce_eager_explicit" -eq 0 ]]; then
    vllm_enforce_eager=0
  fi
}

if is_truthy "${VLLM_ENFORCE_EAGER:-}"; then
  vllm_enforce_eager=1
  vllm_enforce_eager_explicit=1
fi

if is_truthy "${VLLM_DISABLE_CUSTOM_ALL_REDUCE:-}"; then
  vllm_disable_custom_all_reduce=1
  vllm_disable_custom_all_reduce_explicit=1
fi

if [[ -n "${VLLM_SAFE_MODE:-}" ]]; then
  if is_truthy "${VLLM_SAFE_MODE}"; then
    vllm_safe_mode=1
  else
    vllm_safe_mode=0
  fi
fi

trap cleanup EXIT INT TERM

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      profile="$2"
      shift 2
      ;;
    --venv)
      venv_dir="$2"
      shift 2
      ;;
    --python)
      python_bin="$2"
      shift 2
      ;;
    --api-host)
      api_host="$2"
      shift 2
      ;;
    --api-port)
      api_port="$2"
      shift 2
      ;;
    --frontend-host)
      frontend_host="$2"
      shift 2
      ;;
    --frontend-port)
      frontend_port="$2"
      shift 2
      ;;
    --redis-host)
      redis_host="$2"
      shift 2
      ;;
    --redis-port)
      redis_port="$2"
      shift 2
      ;;
    --redis-url)
      redis_url="$2"
      shift 2
      ;;
    --with-vllm)
      with_vllm="yes"
      shift
      ;;
    --skip-vllm)
      with_vllm="no"
      shift
      ;;
    --with-sam|--with-sam3)
      with_sam3="yes"
      shift
      ;;
    --skip-sam|--skip-sam3)
      with_sam3="no"
      shift
      ;;
    --with-llamafactory)
      with_llamafactory="yes"
      shift
      ;;
    --skip-llamafactory)
      with_llamafactory="no"
      shift
      ;;
    --vllm-model-source)
      vllm_model_source="$2"
      vllm_model_source_source="cli"
      shift 2
      ;;
    --vllm-base-url)
      vllm_base_url="$2"
      vllm_base_url_source="cli"
      shift 2
      ;;
    --vllm-served-model-name)
      vllm_served_model_name="$2"
      vllm_served_model_name_source="cli"
      shift 2
      ;;
    --vllm-host)
      vllm_host="$2"
      shift 2
      ;;
    --vllm-port)
      vllm_port="$2"
      shift 2
      ;;
    --vllm-max-model-len)
      vllm_max_model_len="$2"
      vllm_max_model_len_source="cli"
      shift 2
      ;;
    --vllm-gpu-memory-utilization)
      vllm_gpu_memory_utilization="$2"
      vllm_gpu_memory_utilization_source="cli"
      shift 2
      ;;
    --vllm-max-num-seqs)
      vllm_max_num_seqs="$2"
      vllm_max_num_seqs_source="cli"
      shift 2
      ;;
    --vllm-dtype)
      vllm_dtype="$2"
      vllm_dtype_source="cli"
      shift 2
      ;;
    --vllm-tensor-parallel-size)
      vllm_tensor_parallel_size="$2"
      vllm_tensor_parallel_size_source="cli"
      shift 2
      ;;
    --vllm-pipeline-parallel-size)
      vllm_pipeline_parallel_size="$2"
      vllm_pipeline_parallel_size_source="cli"
      shift 2
      ;;
    --vllm-max-num-batched-tokens)
      vllm_max_num_batched_tokens="$2"
      vllm_max_num_batched_tokens_source="cli"
      shift 2
      ;;
    --vllm-swap-space)
      vllm_swap_space="$2"
      vllm_swap_space_source="cli"
      shift 2
      ;;
    --vllm-cpu-offload-gb)
      vllm_cpu_offload_gb="$2"
      vllm_cpu_offload_gb_source="cli"
      shift 2
      ;;
    --vllm-download-dir)
      vllm_download_dir="$2"
      vllm_download_dir_source="cli"
      shift 2
      ;;
    --vllm-start-timeout)
      vllm_start_timeout="$2"
      shift 2
      ;;
    --vllm-log-tail-lines)
      vllm_log_tail_lines="$2"
      shift 2
      ;;
    --vllm-enforce-eager)
      vllm_enforce_eager=1
      vllm_enforce_eager_explicit=1
      shift
      ;;
    --vllm-disable-custom-all-reduce)
      vllm_disable_custom_all_reduce=1
      vllm_disable_custom_all_reduce_explicit=1
      shift
      ;;
    --vllm-no-safe-mode)
      vllm_safe_mode=0
      shift
      ;;
    --vllm-arg)
      vllm_extra_args+=("$2")
      shift 2
      ;;
    --llamafactory-cli)
      llamafactory_cli="$2"
      shift 2
      ;;
    --download-sam-checkpoint|--download-sam3-checkpoint)
      download_sam3_checkpoint=1
      shift
      ;;
    --sam-version|--sam3-version)
      sam3_version="$2"
      shift 2
      ;;
    --run-tests)
      run_tests=1
      shift
      ;;
    --setup-only)
      setup_only=1
      shift
      ;;
    --skip-frontend-install)
      skip_frontend_install=1
      shift
      ;;
    --skip-system-deps)
      skip_system_deps=1
      shift
      ;;
    --embedded-worker)
      embedded_worker=1
      shift
      ;;
    --no-frontend)
      start_frontend=0
      shift
      ;;
    --refresh-python-deps)
      refresh_python_deps=1
      shift
      ;;
    --refresh-frontend-deps)
      refresh_frontend_deps=1
      shift
      ;;
    --refresh-optional-deps)
      refresh_optional_deps=1
      shift
      ;;
    --refresh-all-deps)
      refresh_python_deps=1
      refresh_frontend_deps=1
      refresh_optional_deps=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[[ "$(uname -s)" == "Linux" ]] || die "scripts/start-linux.sh targets Linux only."

if [[ "$venv_dir" != /* ]]; then
  venv_dir="$repo_root/$venv_dir"
fi

if [[ -z "$redis_url" ]]; then
  redis_url="redis://${redis_host}:${redis_port}/0"
fi

if [[ "$with_vllm" == "auto" ]]; then
  if [[ "$profile" == "dev_low_resource" ]]; then
    with_vllm="no"
  else
    with_vllm="yes"
  fi
fi

if [[ "$with_sam3" == "auto" ]]; then
  if [[ "$profile" == "dev_low_resource" ]]; then
    with_sam3="no"
  else
    with_sam3="yes"
  fi
fi

if [[ "$with_llamafactory" == "auto" ]]; then
  if [[ "$profile" == "dev_low_resource" ]]; then
    with_llamafactory="no"
  else
    with_llamafactory="yes"
  fi
fi

if [[ "$finetune_backend" == "auto" ]]; then
  if [[ "$with_llamafactory" == "yes" ]]; then
    finetune_backend="llamafactory"
  else
    finetune_backend="mock"
  fi
fi

if [[ "$profile" == "test_real_stack" || "$profile" == "demo_prod" ]]; then
  if [[ "$finetune_backend" != "llamafactory" ]]; then
    log "WARNING: $profile is not configured for real finetune (FINETUNE_BACKEND=$finetune_backend). Real phase2 verification will fail fast."
  fi
fi

if [[ -z "$sam3_version" ]]; then
  if [[ "$profile" == "test_real_stack" || "$profile" == "demo_prod" ]]; then
    sam3_version="sam2.1"
  else
    sam3_version="sam2"
  fi
fi

if [[ -z "$vllm_base_url" ]]; then
  vllm_base_url="http://${vllm_host}:${vllm_port}"
  vllm_base_url_source="default"
fi

sudo_cmd=()
if [[ "$(id -u)" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    sudo_cmd=(sudo)
  fi
fi

system_python="$(choose_python)"

ensure_base_tools

mkdir -p "$repo_root/data" "$repo_root/logs" "$repo_root/models/sam2" "$repo_root/models/sam3"
session_log_dir="$repo_root/logs/start-linux-$timestamp"
setup_log_dir="$session_log_dir/setup"
managed_log_dir="$session_log_dir/runtime"
state_dir="$repo_root/.cache/start-linux"
install_state_dir="$state_dir/install-state"
mkdir -p "$setup_log_dir" "$managed_log_dir" "$install_state_dir"
local_vllm_state_path="$state_dir/local-vllm-state.json"

require_real_sam3_checkpoint=0
if [[ "$with_sam3" == "yes" ]]; then
  if [[ "$profile" == "test_real_stack" || "$profile" == "demo_prod" ]]; then
    require_real_sam3_checkpoint=1
  fi
  if [[ "$require_real_sam3_checkpoint" -eq 1 && "$download_sam3_checkpoint" -eq 0 ]]; then
    if ! find_local_sam_checkpoint "$sam3_version" >/dev/null 2>&1; then
      download_sam3_checkpoint=1
      log "No local SAM checkpoint found for $sam3_version; auto-enabling checkpoint download for profile $profile."
    fi
  fi
fi

readarray -t _vllm_parts < <("$system_python" - "$vllm_base_url" <<'PY'
from __future__ import annotations

import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
host = parsed.hostname or "127.0.0.1"
port = parsed.port or (443 if parsed.scheme == "https" else 80)
print(host)
print(port)
PY
)
vllm_host="${_vllm_parts[0]:-$vllm_host}"
vllm_port="${_vllm_parts[1]:-$vllm_port}"

venv_created=0
if [[ ! -x "$venv_dir/bin/python" ]]; then
  log "Creating virtualenv at $venv_dir"
  create_virtualenv
  venv_created=1
fi

venv_python="$venv_dir/bin/python"
[[ -x "$venv_python" ]] || die "Virtualenv Python was not created: $venv_python"

if ! "$venv_python" -m pip --version >/dev/null 2>&1; then
  if "$venv_python" -m ensurepip --upgrade >/dev/null 2>&1; then
    log "Bootstrapped pip inside the virtualenv via ensurepip"
  elif "$system_python" -m pip --version >/dev/null 2>&1; then
    log "Rebuilding the virtualenv via virtualenv because ensurepip is unavailable."
    "$system_python" -m pip install --user virtualenv
    "$system_python" -m virtualenv --clear "$venv_dir"
    venv_created=1
  else
    die "pip is missing in the virtualenv, and neither ensurepip nor system pip is available. Install python3-venv / python3-pip and retry."
  fi
fi

python_runtime_id="$("$venv_python" -c 'import platform, sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}|{platform.platform()}")')"

if [[ "$venv_created" -eq 1 || "$refresh_python_deps" -eq 1 ]]; then
  run_logged_step \
    "Bootstrapping pip/setuptools/wheel" \
    "$setup_log_dir/pip-bootstrap.log" \
    "$venv_python" -m pip install --disable-pip-version-check --progress-bar off --upgrade pip setuptools wheel
fi

base_requirements_fingerprint="$(
  compute_fingerprint \
    "$venv_python" \
    "bucket:python-requirements" \
    "python:$python_runtime_id" \
    "file:$repo_root/requirements.txt"
)"
run_cached_step \
  "python-requirements" \
  "$base_requirements_fingerprint" \
  "$(( venv_created || refresh_python_deps ))" \
  "Installing Python requirements from requirements.txt" \
  "$venv_python" -m pip install --disable-pip-version-check --progress-bar off -r "$repo_root/requirements.txt"

need_shared_torch=0
if [[ "$with_sam3" == "yes" || "$with_llamafactory" == "yes" ]]; then
  need_shared_torch=1
elif [[ "$with_vllm" == "yes" && -n "${TORCH_PIP_SPEC:-}" ]]; then
  need_shared_torch=1
fi

if [[ "$need_shared_torch" -eq 1 ]]; then
  read -r -a torch_packages <<<"${TORCH_PIP_SPEC:-torch torchvision}"
  torch_fingerprint="$(
    compute_fingerprint \
      "$venv_python" \
      "bucket:torch" \
      "python:$python_runtime_id" \
      "extra-index:${TORCH_EXTRA_INDEX_URL:-https://download.pytorch.org/whl/cu126}" \
      "spec:${torch_packages[*]}"
  )"
  run_cached_step \
    "torch" \
    "$torch_fingerprint" \
    "$(( venv_created || refresh_optional_deps ))" \
    "Installing Torch packages: ${torch_packages[*]}" \
    "$venv_python" -m pip install --disable-pip-version-check --progress-bar off --extra-index-url "${TORCH_EXTRA_INDEX_URL:-https://download.pytorch.org/whl/cu126}" "${torch_packages[@]}"
elif [[ "$with_vllm" == "yes" ]]; then
  log "Skipping standalone Torch install for vLLM-only path; letting the vLLM package manage its own runtime dependency set."
fi

if [[ "$with_sam3" == "yes" ]]; then
  read -r -a sam3_packages <<<"${SAM_PIP_SPEC:-${SAM3_PIP_SPEC:-git+https://github.com/facebookresearch/sam2.git huggingface_hub pycocotools}}"
  sam3_fingerprint="$(
    compute_fingerprint \
      "$venv_python" \
      "bucket:sam" \
      "python:$python_runtime_id" \
      "spec:${sam3_packages[*]}"
  )"
  run_cached_step \
    "sam" \
    "$sam3_fingerprint" \
    "$(( venv_created || refresh_optional_deps ))" \
    "Installing SAM packages: ${sam3_packages[*]}" \
    "$venv_python" -m pip install --disable-pip-version-check --progress-bar off "${sam3_packages[@]}"
fi

if [[ "$with_vllm" == "yes" ]]; then
  read -r -a vllm_packages <<<"${VLLM_PIP_SPEC:-vllm}"
  vllm_fingerprint="$(
    compute_fingerprint \
      "$venv_python" \
      "bucket:vllm" \
      "python:$python_runtime_id" \
      "spec:${vllm_packages[*]}"
  )"
  run_cached_step \
    "vllm" \
    "$vllm_fingerprint" \
    "$(( venv_created || refresh_optional_deps ))" \
    "Installing vLLM packages: ${vllm_packages[*]}" \
    "$venv_python" -m pip install --disable-pip-version-check --progress-bar off "${vllm_packages[@]}"
fi

if [[ "$with_llamafactory" == "yes" ]]; then
  read -r -a llamafactory_packages <<<"${LLAMAFACTORY_PIP_SPEC:-llamafactory bitsandbytes}"
  llamafactory_fingerprint="$(
    compute_fingerprint \
      "$venv_python" \
      "bucket:llamafactory" \
      "python:$python_runtime_id" \
      "spec:${llamafactory_packages[*]}"
  )"
  run_cached_step \
    "llamafactory" \
    "$llamafactory_fingerprint" \
    "$(( venv_created || refresh_optional_deps ))" \
    "Installing LLaMA-Factory packages: ${llamafactory_packages[*]}" \
    "$venv_python" -m pip install --disable-pip-version-check --progress-bar off "${llamafactory_packages[@]}"
fi

if [[ "$skip_frontend_install" -ne 1 ]]; then
  frontend_manifest="$repo_root/frontend/package.json"
  frontend_lockfile="$repo_root/frontend/package-lock.json"
  frontend_node_modules="$repo_root/frontend/node_modules"
  node_runtime_id="$(node -v 2>/dev/null || echo unknown-node)"
  frontend_fingerprint_args=(
    "bucket:frontend"
    "node:$node_runtime_id"
    "file:$frontend_manifest"
  )
  if [[ -f "$frontend_lockfile" ]]; then
    frontend_fingerprint_args+=("file:$frontend_lockfile")
  fi
  frontend_fingerprint="$(compute_fingerprint "$venv_python" "${frontend_fingerprint_args[@]}")"
  frontend_force_run=0
  if [[ "$refresh_frontend_deps" -eq 1 || ! -d "$frontend_node_modules" ]]; then
    frontend_force_run=1
  fi

  if [[ -f "$frontend_lockfile" ]]; then
    run_cached_step \
      "frontend-deps" \
      "$frontend_fingerprint" \
      "$frontend_force_run" \
      "Installing frontend dependencies with npm ci" \
      bash -lc "cd '$repo_root/frontend' && npm ci --no-audit --no-fund"
  else
    run_cached_step \
      "frontend-deps" \
      "$frontend_fingerprint" \
      "$frontend_force_run" \
      "Installing frontend dependencies with npm install" \
      bash -lc "cd '$repo_root/frontend' && npm install --no-audit --no-fund"
  fi
elif [[ "$setup_only" -ne 1 && "$start_frontend" -eq 1 && ! -d "$repo_root/frontend/node_modules" ]]; then
  die "frontend/node_modules is missing. Re-run without --skip-frontend-install or use --no-frontend."
fi

write_profile_envs() {
  "$venv_python" - "$repo_root" "$profile" "$api_host" "$api_port" "$frontend_host" "$frontend_port" "$redis_url" "$vllm_base_url" "$embedded_worker" "$llamafactory_cli" "$vllm_model_source" "$finetune_backend" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.services.system_profiles import (
    active_backend_env_path,
    active_frontend_env_path,
    read_system_profile,
    write_env_file,
)


repo_root = Path(sys.argv[1]).resolve()
profile_name = sys.argv[2]
api_host = sys.argv[3]
api_port = sys.argv[4]
frontend_host = sys.argv[5]
frontend_port = sys.argv[6]
redis_url = sys.argv[7]
vllm_base_url = sys.argv[8]
embedded_worker = sys.argv[9] == "1"
llamafactory_cli = sys.argv[10]
vllm_model_source = sys.argv[11]
finetune_backend = sys.argv[12]

profile = read_system_profile(profile_name, root_dir=repo_root)
backend_values = dict(profile["backend"])
frontend_values = dict(profile["frontend"])

frontend_origins = [
    f"http://localhost:{frontend_port}",
    f"http://127.0.0.1:{frontend_port}",
]
if frontend_host not in {"localhost", "127.0.0.1"}:
    frontend_origins.append(f"http://{frontend_host}:{frontend_port}")

backend_values["APP_PROFILE"] = profile_name
backend_values["HOST"] = api_host
backend_values["PORT"] = api_port
backend_values["REDIS_URL"] = redis_url
backend_values["TASK_EMBEDDED_WORKER"] = "true" if embedded_worker else "false"
backend_values["CORS_ALLOW_ORIGINS"] = json.dumps(frontend_origins, ensure_ascii=False)
backend_values["VLLM_BASE_URL"] = vllm_base_url
backend_values["FINETUNE_BACKEND"] = finetune_backend
backend_values["LLAMAFACTORY_CLI"] = llamafactory_cli
if vllm_model_source:
    backend_values["VLLM_MODEL_SOURCE"] = vllm_model_source

frontend_values["VITE_APP_PROFILE"] = profile_name
frontend_values["VITE_API_BASE_URL"] = f"http://{api_host}:{api_port}"

write_env_file(active_backend_env_path(repo_root), backend_values, header=f"Generated from profile: {profile_name}")
write_env_file(active_frontend_env_path(repo_root), frontend_values, header=f"Generated from profile: {profile_name}")
PY
}

if [[ "$llamafactory_cli" == "llamafactory-cli" && -x "$venv_dir/bin/llamafactory-cli" ]]; then
  llamafactory_cli="$venv_dir/bin/llamafactory-cli"
fi

write_profile_envs

if [[ "$download_sam3_checkpoint" -eq 1 ]]; then
  if [[ "$sam3_version" == sam2* ]]; then
    run_logged_step \
      "Downloading SAM checkpoint family: $sam3_version" \
      "$setup_log_dir/download-sam.log" \
      "$venv_python" - "$repo_root" "$sam3_version" <<'PY'
from __future__ import annotations

import shutil
import sys
import urllib.request
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
version = sys.argv[2]
destination_dir = repo_root / "models" / "sam2"
destination_dir.mkdir(parents=True, exist_ok=True)

url_map = {
    "sam2": "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_large.pt",
    "sam2.1": "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt",
}
url = url_map.get(version)
if not url:
    raise SystemExit(f"Unsupported SAM version for auto-download: {version}")

filename = url.rsplit("/", 1)[-1]
destination_path = destination_dir / filename
if destination_path.exists():
    print(destination_path)
    raise SystemExit(0)

with urllib.request.urlopen(url) as response, destination_path.open("wb") as handle:
    shutil.copyfileobj(response, handle)
print(destination_path)
PY
  else
    if ! has_hf_hub_auth; then
      die "Downloading SAM3 checkpoints requires Hugging Face access to facebook/$sam3_version. Set HF_TOKEN (or HUGGING_FACE_HUB_TOKEN), run '$venv_dir/bin/hf auth login', or place a local .pt checkpoint under $repo_root/models/sam3."
    fi
    run_logged_step \
      "Downloading SAM checkpoint family: $sam3_version" \
      "$setup_log_dir/download-sam.log" \
      "$venv_python" - "$repo_root" "$sam3_version" <<'PY'
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from sam3.model_builder import download_ckpt_from_hf

repo_root = Path(sys.argv[1]).resolve()
version = sys.argv[2]
destination_dir = repo_root / "models" / "sam3"
destination_dir.mkdir(parents=True, exist_ok=True)
try:
    source_path = Path(download_ckpt_from_hf(version=version)).resolve()
except Exception as exc:  # noqa: BLE001
    message = str(exc)
    if "GatedRepoError" in type(exc).__name__ or "Cannot access gated repo" in message or "401 Client Error" in message:
        raise SystemExit(
            "SAM3 checkpoint download requires authenticated Hugging Face access to "
            f"facebook/{version}. Run '.venv/bin/hf auth login', set HF_TOKEN, or "
            f"place a local checkpoint under {destination_dir}."
        )
    raise
destination_path = destination_dir / source_path.name
if source_path != destination_path.resolve():
    shutil.copy2(source_path, destination_path)
print(destination_path)
PY
  fi
fi

if [[ "$with_sam3" == "yes" ]]; then
  sam3_checkpoint_path="$(find_local_sam_checkpoint "$sam3_version" 2>/dev/null || true)"
  if [[ -n "$sam3_checkpoint_path" ]]; then
    log "Resolved SAM checkpoint: $sam3_checkpoint_path"
  elif [[ "$require_real_sam3_checkpoint" -eq 1 ]]; then
    if [[ "$sam3_version" == sam2* ]]; then
      die "Profile $profile requires a real SAM2 checkpoint, but none is available under $repo_root/models/sam2. Re-run with network access or provide a local checkpoint."
    fi
    die "Profile $profile requires a real SAM3 checkpoint, but none is available under $repo_root/models/sam3. Re-run with network access or provide a local checkpoint."
  else
    warn "No local SAM checkpoint was found for $sam3_version; the backend may fall back to the SAM stub runtime."
  fi
fi

if [[ "$run_tests" -eq 1 ]]; then
  run_logged_step \
    "Running compileall" \
    "$setup_log_dir/compileall.log" \
    "$venv_python" -m compileall "$repo_root/backend" "$repo_root/tests" "$repo_root/scripts"

  run_logged_step \
    "Running pytest" \
    "$setup_log_dir/pytest.log" \
    "$venv_python" -m pytest -q

  if [[ "$skip_frontend_install" -eq 1 ]]; then
    warn "Skipping frontend build because --skip-frontend-install was used."
  else
    run_logged_step_in_dir \
      "Running frontend build" \
      "$setup_log_dir/frontend-build.log" \
      "$repo_root/frontend" \
      npm run build
  fi
fi

if [[ "$setup_only" -eq 1 ]]; then
  cat <<EOF

Setup complete.
  Profile       : $profile
  Backend env   : $repo_root/.env.active
  Frontend env  : $repo_root/frontend/.env.local
  Virtualenv    : $venv_dir
  Logs          : $session_log_dir
  Install cache : $install_state_dir
EOF
  exit 0
fi

redis_reused=0
if ping_redis_url "$redis_url" >/dev/null 2>&1; then
  redis_reused=1
  log "Reusing existing Redis: $redis_url"
else
  command -v redis-server >/dev/null 2>&1 || die "redis-server was not found."
  start_service redis redis-server --save '' --appendonly no --bind "$redis_host" --port "$redis_port" --protected-mode no
  redis_pid="$started_pid"
  sleep 1
  ping_redis_url "$redis_url" >/dev/null 2>&1 || {
    tail_last_lines "$managed_log_dir/redis.log" 80
    die "Managed Redis failed to start at $redis_url"
  }
  log "Managed Redis started with pid $redis_pid"
fi

start_local_vllm=0
readarray -t _runtime_env_parts < <("$venv_python" - "$repo_root" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))

from backend.services.system_profiles import parse_env_file

payload = parse_env_file(root / ".env.active")
print(payload.get("ANNOTATION_BACKEND", "stub"))
print(payload.get("VLLM_MODEL_NAME", "qwen3-vl-4b"))
print(payload.get("VLLM_MAX_MODEL_LEN", ""))
print(payload.get("VLLM_GPU_MEMORY_UTILIZATION", ""))
print(payload.get("VLLM_MAX_NUM_SEQS", ""))
print(payload.get("VLLM_MAX_NUM_BATCHED_TOKENS", ""))
print(payload.get("VLLM_CPU_OFFLOAD_GB", ""))
PY
)
annotation_backend="${_runtime_env_parts[0]:-stub}"
profile_vllm_model_name="${_runtime_env_parts[1]:-qwen3-vl-4b}"
profile_vllm_max_model_len="${_runtime_env_parts[2]:-}"
profile_vllm_gpu_memory_utilization="${_runtime_env_parts[3]:-}"
profile_vllm_max_num_seqs="${_runtime_env_parts[4]:-}"
profile_vllm_max_num_batched_tokens="${_runtime_env_parts[5]:-}"
profile_vllm_cpu_offload_gb="${_runtime_env_parts[6]:-}"

if [[ "$annotation_backend" == "openai_compatible" && "$with_vllm" == "yes" && -n "$vllm_model_source" ]]; then
  start_local_vllm=1
fi

if [[ "$start_local_vllm" -eq 1 ]]; then
  command -v nvidia-smi >/dev/null 2>&1 || die "Local vLLM requested, but nvidia-smi was not found. Supply an external VLLM_BASE_URL or use --skip-vllm."
  vllm_model_source="$(normalize_local_model_source "$vllm_model_source")"

  if [[ -z "$vllm_served_model_name" ]]; then
    vllm_served_model_name="$profile_vllm_model_name"
    vllm_served_model_name_source="profile"
  fi
  if [[ -z "$vllm_max_model_len" && -n "$profile_vllm_max_model_len" ]]; then
    vllm_max_model_len="$profile_vllm_max_model_len"
    vllm_max_model_len_source="profile"
  fi
  if [[ -z "$vllm_gpu_memory_utilization" && -n "$profile_vllm_gpu_memory_utilization" ]]; then
    vllm_gpu_memory_utilization="$profile_vllm_gpu_memory_utilization"
    vllm_gpu_memory_utilization_source="profile"
  fi
  if [[ -z "$vllm_max_num_seqs" && -n "$profile_vllm_max_num_seqs" ]]; then
    vllm_max_num_seqs="$profile_vllm_max_num_seqs"
    vllm_max_num_seqs_source="profile"
  fi
  if [[ -z "$vllm_max_num_batched_tokens" && -n "$profile_vllm_max_num_batched_tokens" ]]; then
    vllm_max_num_batched_tokens="$profile_vllm_max_num_batched_tokens"
    vllm_max_num_batched_tokens_source="profile"
  fi
  if [[ -z "$vllm_cpu_offload_gb" && -n "$profile_vllm_cpu_offload_gb" ]]; then
    vllm_cpu_offload_gb="$profile_vllm_cpu_offload_gb"
    vllm_cpu_offload_gb_source="profile"
  fi

  visible_gpu_memory_mib="$(detect_visible_gpu_memory_mib)"
  apply_vllm_safe_defaults "$visible_gpu_memory_mib"

  vllm_base_url="http://${vllm_host}:${vllm_port}"
  write_profile_envs
  ensure_vllm_help_cache

  log "Resolved local vLLM settings:"
  log "  model_source=$vllm_model_source"
  log "  served_model_name=${vllm_served_model_name:-<empty>}"
  log "  gpu_memory_mib=${visible_gpu_memory_mib:-unknown}"
  log "  max_model_len=${vllm_max_model_len:-<auto>}"
  log "  gpu_memory_utilization=${vllm_gpu_memory_utilization:-<auto>}"
  log "  max_num_seqs=${vllm_max_num_seqs:-<auto>}"
  log "  dtype=${vllm_dtype:-<auto>}"
  log "  tensor_parallel_size=${vllm_tensor_parallel_size:-<default>}"
  log "  pipeline_parallel_size=${vllm_pipeline_parallel_size:-<default>}"
  log "  max_num_batched_tokens=${vllm_max_num_batched_tokens:-<default>}"
  log "  swap_space=${vllm_swap_space:-<default>}"
  log "  safe_mode=$vllm_safe_mode"

  vllm_env_unset=(
    VLLM_MODEL_SOURCE
    VLLM_BASE_URL
    VLLM_SERVED_MODEL_NAME
    VLLM_MAX_MODEL_LEN
    VLLM_GPU_MEMORY_UTILIZATION
    VLLM_MAX_NUM_SEQS
    VLLM_DTYPE
    VLLM_TENSOR_PARALLEL_SIZE
    VLLM_PIPELINE_PARALLEL_SIZE
    VLLM_MAX_NUM_BATCHED_TOKENS
    VLLM_SWAP_SPACE
    VLLM_CPU_OFFLOAD_GB
    VLLM_DOWNLOAD_DIR
    VLLM_START_TIMEOUT
    VLLM_LOG_TAIL_LINES
  )
  vllm_command=(
    "$venv_python"
    -m
    vllm.entrypoints.openai.api_server
    --model "$vllm_model_source"
    --served-model-name "$vllm_served_model_name"
    --host "$vllm_host"
    --port "$vllm_port"
  )
  if [[ -n "$vllm_max_model_len" ]]; then
    append_vllm_value_option --max-model-len "$vllm_max_model_len"
  fi
  if [[ -n "$vllm_gpu_memory_utilization" ]]; then
    append_vllm_value_option --gpu-memory-utilization "$vllm_gpu_memory_utilization"
  fi
  if [[ -n "$vllm_max_num_seqs" ]]; then
    append_vllm_value_option --max-num-seqs "$vllm_max_num_seqs"
  fi
  if [[ -n "$vllm_dtype" ]]; then
    append_vllm_value_option --dtype "$vllm_dtype"
  fi
  if [[ -n "$vllm_tensor_parallel_size" ]]; then
    append_vllm_value_option --tensor-parallel-size "$vllm_tensor_parallel_size"
  fi
  if [[ -n "$vllm_pipeline_parallel_size" ]]; then
    append_vllm_value_option --pipeline-parallel-size "$vllm_pipeline_parallel_size"
  fi
  if [[ -n "$vllm_max_num_batched_tokens" ]]; then
    append_vllm_value_option --max-num-batched-tokens "$vllm_max_num_batched_tokens"
  fi
  if [[ -n "$vllm_swap_space" ]]; then
    append_vllm_value_option --swap-space "$vllm_swap_space"
  fi
  if [[ -n "$vllm_cpu_offload_gb" ]]; then
    append_vllm_value_option --cpu-offload-gb "$vllm_cpu_offload_gb"
  fi
  if [[ -n "$vllm_download_dir" ]]; then
    mkdir -p "$vllm_download_dir"
    append_vllm_value_option --download-dir "$vllm_download_dir"
  fi
  if [[ "$vllm_enforce_eager" -eq 1 ]]; then
    append_vllm_flag_option --enforce-eager
  fi
  if [[ "$vllm_disable_custom_all_reduce" -eq 1 ]]; then
    append_vllm_flag_option --disable-custom-all-reduce
  fi
  if [[ ${#vllm_extra_args[@]} -gt 0 ]]; then
    vllm_command+=("${vllm_extra_args[@]}")
  fi

  supports_enable_lora=0
  if vllm_supports_argument --enable-lora; then
    supports_enable_lora=1
  fi

  vllm_launch_command=(env)
  for env_name in "${vllm_env_unset[@]}"; do
    if [[ -n "${!env_name:-}" ]]; then
      vllm_launch_command+=(-u "$env_name")
    fi
  done
  vllm_launch_command+=(
    PYTHONUNBUFFERED=1
    VLLM_ALLOW_RUNTIME_LORA_UPDATING=1
    "${vllm_command[@]}"
  )

  clear_local_vllm_runtime_state
  start_service vllm "${vllm_launch_command[@]}"
  vllm_pid="$started_pid"
  readarray -t vllm_probe_urls < <(build_vllm_probe_urls "$vllm_base_url")
  wait_for_service_ready "Local vLLM" "$vllm_pid" "$vllm_start_timeout" "$managed_log_dir/vllm.log" "${vllm_probe_urls[@]}" || {
    die "Local vLLM failed to become healthy."
  }
  env_unset_json="$(json_array_from_words "${vllm_env_unset[@]}")"
  env_set_json='{"PYTHONUNBUFFERED":"1","VLLM_ALLOW_RUNTIME_LORA_UPDATING":"1"}'
  command_json="$(json_array_from_words "${vllm_command[@]}")"
  write_local_vllm_runtime_state \
    "$vllm_pid" \
    "$managed_log_dir/vllm.log" \
    "$supports_enable_lora" \
    "$env_unset_json" \
    "$env_set_json" \
    "$command_json" \
    "$vllm_start_timeout"
  log "Local vLLM started with pid $vllm_pid"
elif [[ "$annotation_backend" == "openai_compatible" ]]; then
  clear_local_vllm_runtime_state
  readarray -t vllm_probe_urls < <(build_vllm_probe_urls "$vllm_base_url")
  wait_for_any_url 20 "${vllm_probe_urls[@]}" || {
    die "Profile ${profile} expects an OpenAI-compatible endpoint at ${vllm_base_url}, but it is not healthy. Pass --vllm-model-source with --with-vllm, or point VLLM_BASE_URL to a running service."
  }
  log "Using external/already-running OpenAI-compatible endpoint at ${vllm_base_url}"
else
  clear_local_vllm_runtime_state
fi

if [[ "$embedded_worker" -eq 0 ]]; then
  start_service worker env PYTHONUNBUFFERED=1 "$venv_python" -m backend.task_worker_main
  worker_pid="$started_pid"
  sleep 1
  if ! kill -0 "$worker_pid" >/dev/null 2>&1; then
    tail_last_lines "$managed_log_dir/worker.log" 80
    die "Worker exited early."
  fi
  log "Standalone worker started with pid $worker_pid"
else
  log "Using embedded task worker."
fi

start_service backend env PYTHONUNBUFFERED=1 "$venv_python" -m uvicorn backend.main:app --host "$api_host" --port "$api_port"
backend_pid="$started_pid"
wait_for_service_ready "Backend" "$backend_pid" 60 "$managed_log_dir/backend.log" "http://${api_host}:${api_port}/healthz" || {
  die "Backend did not become healthy."
}
log "Backend started with pid $backend_pid"

if [[ "$start_frontend" -eq 1 ]]; then
  start_service frontend bash -lc "cd '$repo_root/frontend' && npm run dev -- --host '$frontend_host' --port '$frontend_port' --strictPort"
  frontend_pid="$started_pid"
  wait_for_service_ready "Frontend" "$frontend_pid" 90 "$managed_log_dir/frontend.log" "http://${frontend_host}:${frontend_port}" || {
    die "Frontend did not become healthy."
  }
  log "Frontend started with pid $frontend_pid"
fi

cat <<EOF

Ready.
  Profile       : $profile
  Backend       : http://${api_host}:${api_port}
  Health        : http://${api_host}:${api_port}/healthz
  Frontend      : $( [[ "$start_frontend" -eq 1 ]] && printf 'http://%s:%s' "$frontend_host" "$frontend_port" || printf 'disabled' )
  Redis         : $redis_url$( [[ "$redis_reused" -eq 1 ]] && printf ' (reused)' || printf ' (managed)' )
  OpenAI route  : $vllm_base_url
  Finetune      : $finetune_backend$( [[ "$finetune_backend" == "llamafactory" ]] && printf ' (%s)' "$llamafactory_cli" || printf '' )
  Logs          : $session_log_dir
  Install cache : $install_state_dir

Press Ctrl+C to stop all managed services.
EOF

while true; do
  sleep 2
  for index in "${!managed_pids[@]}"; do
    pid="${managed_pids[$index]}"
    if [[ -n "${vllm_pid:-}" && "$pid" == "${vllm_pid:-}" && -f "$local_vllm_state_path" ]]; then
      state_pid="$(current_local_vllm_state_pid)"
      if [[ "$state_pid" =~ ^[0-9]+$ && "$state_pid" -gt 0 && "$state_pid" != "$pid" ]]; then
        managed_pids[$index]="$state_pid"
        vllm_pid="$state_pid"
        pid="$state_pid"
      elif [[ "$state_pid" == "0" ]]; then
        continue
      fi
    fi
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      warn "A managed service exited unexpectedly."
      for log_file in "$managed_log_dir"/*.log; do
        tail_last_lines "$log_file" 80
      done
      exit 1
    fi
  done
done
