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
vllm_model_source="${VLLM_MODEL_SOURCE:-}"
vllm_base_url="${VLLM_BASE_URL:-}"
vllm_served_model_name=""
vllm_host="127.0.0.1"
vllm_port="8001"
vllm_max_model_len="${VLLM_MAX_MODEL_LEN:-}"
vllm_gpu_memory_utilization="${VLLM_GPU_MEMORY_UTILIZATION:-}"
vllm_max_num_seqs="${VLLM_MAX_NUM_SEQS:-}"
llamafactory_cli="${LLAMAFACTORY_CLI:-llamafactory-cli}"
managed_log_dir=""
declare -a managed_pids=()
started_pid=""

usage() {
  cat <<'EOF'
Usage: bash scripts/start-linux.sh [options]

One command for Linux-based setup + profile activation + local service orchestration.
It can:
  1. auto-install missing system dependencies on Ubuntu/Debian,
  2. create/update the Python virtualenv and frontend deps,
  3. write .env.active and frontend/.env.local from the selected profile,
  4. optionally run compileall + pytest + frontend build,
  5. start Redis / worker / backend / frontend / local vLLM with health checks.

Recommended smoke path:
  bash scripts/start-linux.sh --profile dev_low_resource --run-tests

Recommended real-stack path:
  VLLM_MODEL_SOURCE=Qwen/Qwen2.5-VL-7B-Instruct \
  bash scripts/start-linux.sh --profile test_real_stack --with-vllm --with-sam3 --with-llamafactory

Options:
  --profile <name>               Profile name. Default: dev_low_resource
  --venv <path>                  Virtualenv directory. Default: .venv
  --python <exe>                 Python executable used to create the venv
  --api-host <host>              Backend bind host. Default: 127.0.0.1
  --api-port <port>              Backend port. Default: 8000
  --frontend-host <host>         Frontend bind host. Default: 127.0.0.1
  --frontend-port <port>         Frontend port. Default: 5173
  --redis-host <host>            Redis host when using local managed Redis. Default: 127.0.0.1
  --redis-port <port>            Redis port when using local managed Redis. Default: 6379
  --redis-url <url>              Full Redis URL. Default: redis://127.0.0.1:<port>/0
  --with-vllm                    Install/start local vLLM if needed
  --skip-vllm                    Do not install/start local vLLM
  --with-sam3                    Install real SAM3 dependencies
  --skip-sam3                    Skip real SAM3 dependencies
  --with-llamafactory            Install LLaMA-Factory CLI
  --skip-llamafactory            Skip LLaMA-Factory CLI installation
  --vllm-model-source <value>    Hugging Face id or local path for local vLLM
  --vllm-base-url <url>          OpenAI-compatible base URL. Default: VLLM_BASE_URL or http://127.0.0.1:8001
  --vllm-served-model-name <v>   Served model name for local vLLM; defaults to profile VLLM_MODEL_NAME
  --vllm-host <host>             Local vLLM bind host. Default: 127.0.0.1
  --vllm-port <port>             Local vLLM bind port. Default: 8001
  --vllm-max-model-len <n>       Optional vLLM max model length. Default: VLLM_MAX_MODEL_LEN or profile backend value
  --vllm-gpu-memory-utilization  Optional vLLM GPU memory fraction. Default: VLLM_GPU_MEMORY_UTILIZATION or profile backend value
  --vllm-max-num-seqs <n>        Optional vLLM max concurrent sequences. Default: VLLM_MAX_NUM_SEQS or profile backend value
  --llamafactory-cli <command>   CLI used by backend FINETUNE_BACKEND=auto. Default: llamafactory-cli
  --download-sam3-checkpoint     Download the configured SAM3 checkpoint family
  --sam3-version <sam3|sam3.1>   Checkpoint family when downloading; auto by profile
  --run-tests                    Run compileall + pytest + frontend build before startup
  --setup-only                   Stop after environment setup and optional tests
  --skip-frontend-install        Skip npm ci / npm install
  --skip-system-deps             Do not try to apt-install missing Linux packages
  --embedded-worker              Keep TASK_EMBEDDED_WORKER=true and do not start a standalone worker
  --no-frontend                  Do not start the frontend dev server
  -h, --help                     Show this help

Environment overrides:
  PYTHON_BIN             Preferred Python executable
  TORCH_PIP_SPEC         Torch packages. Default: "torch torchvision"
  TORCH_EXTRA_INDEX_URL  Torch wheel index. Default: https://download.pytorch.org/whl/cu126
  SAM3_PIP_SPEC          SAM3 packages. Default: "git+https://github.com/facebookresearch/sam3.git huggingface_hub"
  VLLM_PIP_SPEC          vLLM packages. Default: "vllm"
  LLAMAFACTORY_PIP_SPEC  LLaMA-Factory package. Default: "llamafactory"
  VLLM_MAX_MODEL_LEN             Optional vLLM max context length override
  VLLM_GPU_MEMORY_UTILIZATION    Optional vLLM GPU memory fraction override
  VLLM_MAX_NUM_SEQS              Optional vLLM max concurrent sequences override
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

cleanup() {
  local index
  for (( index=${#managed_pids[@]}-1; index>=0; index-- )); do
    local pid="${managed_pids[$index]}"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
    fi
  done
}

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
    --with-sam3)
      with_sam3="yes"
      shift
      ;;
    --skip-sam3)
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
      shift 2
      ;;
    --vllm-base-url)
      vllm_base_url="$2"
      shift 2
      ;;
    --vllm-served-model-name)
      vllm_served_model_name="$2"
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
      shift 2
      ;;
    --vllm-gpu-memory-utilization)
      vllm_gpu_memory_utilization="$2"
      shift 2
      ;;
    --vllm-max-num-seqs)
      vllm_max_num_seqs="$2"
      shift 2
      ;;
    --llamafactory-cli)
      llamafactory_cli="$2"
      shift 2
      ;;
    --download-sam3-checkpoint)
      download_sam3_checkpoint=1
      shift
      ;;
    --sam3-version)
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

if [[ -z "$sam3_version" ]]; then
  if [[ "$profile" == "test_real_stack" || "$profile" == "demo_prod" ]]; then
    sam3_version="sam3.1"
  else
    sam3_version="sam3"
  fi
fi

if [[ -z "$vllm_base_url" ]]; then
  vllm_base_url="http://${vllm_host}:${vllm_port}"
fi

sudo_cmd=()
if [[ "$(id -u)" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    sudo_cmd=(sudo)
  fi
fi

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

system_python="$(choose_python)"

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

ensure_base_tools

mkdir -p "$repo_root/data" "$repo_root/logs" "$repo_root/models/sam3"

if [[ ! -x "$venv_dir/bin/python" ]]; then
  log "Creating virtualenv at $venv_dir"
  create_virtualenv
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
  else
    die "pip is missing in the virtualenv, and neither ensurepip nor system pip is available. Install python3-venv / python3-pip and retry."
  fi
fi

pip_cmd=("$venv_python" -m pip)

log "Installing Python requirements"
"${pip_cmd[@]}" install --upgrade pip setuptools wheel
"${pip_cmd[@]}" install -r "$repo_root/requirements.txt"

if [[ "$with_sam3" == "yes" || "$with_vllm" == "yes" || "$with_llamafactory" == "yes" ]]; then
  read -r -a torch_packages <<<"${TORCH_PIP_SPEC:-torch torchvision}"
  log "Installing Torch packages: ${torch_packages[*]}"
  "${pip_cmd[@]}" install --extra-index-url "${TORCH_EXTRA_INDEX_URL:-https://download.pytorch.org/whl/cu126}" "${torch_packages[@]}"
fi

if [[ "$with_sam3" == "yes" ]]; then
  read -r -a sam3_packages <<<"${SAM3_PIP_SPEC:-git+https://github.com/facebookresearch/sam3.git huggingface_hub}"
  log "Installing SAM3 packages: ${sam3_packages[*]}"
  "${pip_cmd[@]}" install "${sam3_packages[@]}"
fi

if [[ "$with_vllm" == "yes" ]]; then
  read -r -a vllm_packages <<<"${VLLM_PIP_SPEC:-vllm}"
  log "Installing vLLM packages: ${vllm_packages[*]}"
  "${pip_cmd[@]}" install "${vllm_packages[@]}"
fi

if [[ "$with_llamafactory" == "yes" ]]; then
  read -r -a llamafactory_packages <<<"${LLAMAFACTORY_PIP_SPEC:-llamafactory}"
  log "Installing LLaMA-Factory packages: ${llamafactory_packages[*]}"
  "${pip_cmd[@]}" install "${llamafactory_packages[@]}"
fi

if [[ "$skip_frontend_install" -ne 1 ]]; then
  log "Installing frontend dependencies"
  (
    cd "$repo_root/frontend"
    if [[ -f package-lock.json ]]; then
      npm ci
    else
      npm install
    fi
  )
elif [[ "$setup_only" -ne 1 && "$start_frontend" -eq 1 && ! -d "$repo_root/frontend/node_modules" ]]; then
  die "frontend/node_modules is missing. Re-run without --skip-frontend-install or use --no-frontend."
fi

write_profile_envs() {
  "$venv_python" - "$repo_root" "$profile" "$api_host" "$api_port" "$frontend_host" "$frontend_port" "$redis_url" "$vllm_host" "$vllm_port" "$embedded_worker" "$llamafactory_cli" <<'PY'
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
vllm_host = sys.argv[8]
vllm_port = sys.argv[9]
embedded_worker = sys.argv[10] == "1"
llamafactory_cli = sys.argv[11]

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
backend_values["VLLM_BASE_URL"] = f"http://{vllm_host}:{vllm_port}"
backend_values["LLAMAFACTORY_CLI"] = llamafactory_cli

frontend_values["VITE_APP_PROFILE"] = profile_name
frontend_values["VITE_API_BASE_URL"] = f"http://{api_host}:{api_port}"

write_env_file(active_backend_env_path(repo_root), backend_values, header=f"Generated from profile: {profile_name}")
write_env_file(active_frontend_env_path(repo_root), frontend_values, header=f"Generated from profile: {profile_name}")
PY
}

write_profile_envs

if [[ "$download_sam3_checkpoint" -eq 1 ]]; then
  log "Downloading SAM3 checkpoint family: $sam3_version"
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
source_path = Path(download_ckpt_from_hf(version=version)).resolve()
destination_path = destination_dir / source_path.name
if source_path != destination_path.resolve():
    shutil.copy2(source_path, destination_path)
print(destination_path)
PY
fi

if [[ "$run_tests" -eq 1 ]]; then
  log "Running compileall"
  "$venv_python" -m compileall "$repo_root/backend" "$repo_root/tests" "$repo_root/scripts"
  log "Running pytest"
  "$venv_python" -m pytest -q
  if [[ "$skip_frontend_install" -eq 1 ]]; then
    warn "Skipping frontend build because --skip-frontend-install was used."
  else
    log "Running frontend build"
    (
      cd "$repo_root/frontend"
      npm run build
    )
  fi
fi

if [[ "$setup_only" -eq 1 ]]; then
  log "Setup complete."
  log "Profile      : $profile"
  log "Backend env  : $repo_root/.env.active"
  log "Frontend env : $repo_root/frontend/.env.local"
  log "Virtualenv   : $venv_dir"
  exit 0
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
managed_log_dir="$repo_root/logs/start-linux-$timestamp"
mkdir -p "$managed_log_dir"

tail_last_lines() {
  local path="$1"
  if [[ -f "$path" ]]; then
    printf '\n----- %s (last 40 lines) -----\n' "$path" >&2
    tail -n 40 "$path" >&2 || true
  fi
}

wait_for_http() {
  local url="$1"
  local timeout_seconds="$2"
  "$venv_python" - "$url" "$timeout_seconds" <<'PY'
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request

url = sys.argv[1]
timeout_seconds = float(sys.argv[2])
deadline = time.monotonic() + timeout_seconds
last_error = ""
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            if 200 <= response.status < 500:
                raise SystemExit(0)
    except Exception as exc:  # noqa: BLE001
        last_error = str(exc)
        time.sleep(0.3)
raise SystemExit(last_error or "timeout")
PY
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
  log "Starting $name"
  (
    cd "$repo_root"
    "$@"
  ) >"$log_path" 2>&1 &
  started_pid="$!"
  managed_pids+=("$started_pid")
}

redis_reused=0
if ping_redis_url "$redis_url" >/dev/null 2>&1; then
  redis_reused=1
  log "Reusing existing Redis: $redis_url"
else
  command -v redis-server >/dev/null 2>&1 || die "redis-server was not found."
  start_service redis redis-server --save '' --appendonly no --bind "$redis_host" --port "$redis_port" --protected-mode no
  redis_pid="$started_pid"
  sleep 0.5
  ping_redis_url "$redis_url" >/dev/null 2>&1 || {
    tail_last_lines "$managed_log_dir/redis.log"
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
PY
)
annotation_backend="${_runtime_env_parts[0]:-stub}"
profile_vllm_model_name="${_runtime_env_parts[1]:-qwen3-vl-4b}"
profile_vllm_max_model_len="${_runtime_env_parts[2]:-}"
profile_vllm_gpu_memory_utilization="${_runtime_env_parts[3]:-}"
profile_vllm_max_num_seqs="${_runtime_env_parts[4]:-}"

if [[ "$annotation_backend" == "openai_compatible" && "$with_vllm" == "yes" && -n "$vllm_model_source" ]]; then
  start_local_vllm=1
fi

if [[ "$start_local_vllm" -eq 1 ]]; then
  command -v nvidia-smi >/dev/null 2>&1 || die "Local vLLM requested, but nvidia-smi was not found. Supply an external VLLM_BASE_URL or use --skip-vllm."
  if [[ -z "$vllm_served_model_name" ]]; then
    vllm_served_model_name="$profile_vllm_model_name"
  fi
  if [[ -z "$vllm_max_model_len" ]]; then
    vllm_max_model_len="$profile_vllm_max_model_len"
  fi
  if [[ -z "$vllm_gpu_memory_utilization" ]]; then
    vllm_gpu_memory_utilization="$profile_vllm_gpu_memory_utilization"
  fi
  if [[ -z "$vllm_max_num_seqs" ]]; then
    vllm_max_num_seqs="$profile_vllm_max_num_seqs"
  fi
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
    vllm_command+=(--max-model-len "$vllm_max_model_len")
  fi
  if [[ -n "$vllm_gpu_memory_utilization" ]]; then
    vllm_command+=(--gpu-memory-utilization "$vllm_gpu_memory_utilization")
  fi
  if [[ -n "$vllm_max_num_seqs" ]]; then
    vllm_command+=(--max-num-seqs "$vllm_max_num_seqs")
  fi
  start_service vllm "${vllm_command[@]}"
  vllm_pid="$started_pid"
  wait_for_http "http://${vllm_host}:${vllm_port}/health" 180 >/dev/null 2>&1 || wait_for_http "http://${vllm_host}:${vllm_port}/v1/models" 180 >/dev/null 2>&1 || {
    tail_last_lines "$managed_log_dir/vllm.log"
    die "Local vLLM failed to become healthy."
  }
  log "Local vLLM started with pid $vllm_pid"
elif [[ "$annotation_backend" == "openai_compatible" ]]; then
  wait_for_http "http://${vllm_host}:${vllm_port}/health" 20 >/dev/null 2>&1 || wait_for_http "http://${vllm_host}:${vllm_port}/v1/models" 20 >/dev/null 2>&1 || {
    die "Profile ${profile} expects an OpenAI-compatible endpoint at http://${vllm_host}:${vllm_port}, but it is not healthy. Pass --vllm-model-source with --with-vllm, or point VLLM_BASE_URL to a running service."
  }
  log "Using external/already-running OpenAI-compatible endpoint at http://${vllm_host}:${vllm_port}"
fi

if [[ "$embedded_worker" -eq 0 ]]; then
  start_service worker "$venv_python" -m backend.task_worker_main
  worker_pid="$started_pid"
  sleep 0.5
  if ! kill -0 "$worker_pid" >/dev/null 2>&1; then
    tail_last_lines "$managed_log_dir/worker.log"
    die "Worker exited early."
  fi
  log "Standalone worker started with pid $worker_pid"
else
  log "Using embedded task worker."
fi

start_service backend "$venv_python" -m uvicorn backend.main:app --host "$api_host" --port "$api_port"
backend_pid="$started_pid"
wait_for_http "http://${api_host}:${api_port}/healthz" 60 >/dev/null 2>&1 || {
  tail_last_lines "$managed_log_dir/backend.log"
  die "Backend did not become healthy."
}
log "Backend started with pid $backend_pid"

if [[ "$start_frontend" -eq 1 ]]; then
  start_service frontend bash -lc "cd '$repo_root/frontend' && npm run dev -- --host '$frontend_host' --port '$frontend_port' --strictPort"
  frontend_pid="$started_pid"
  wait_for_http "http://${frontend_host}:${frontend_port}" 90 >/dev/null 2>&1 || {
    tail_last_lines "$managed_log_dir/frontend.log"
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
  OpenAI route  : http://${vllm_host}:${vllm_port}
  Logs          : $managed_log_dir

Press Ctrl+C to stop all managed services.
EOF

while true; do
  sleep 2
  for pid in "${managed_pids[@]}"; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      warn "A managed service exited unexpectedly."
      for log_file in "$managed_log_dir"/*.log; do
        tail_last_lines "$log_file"
      done
      exit 1
    fi
  done
done
