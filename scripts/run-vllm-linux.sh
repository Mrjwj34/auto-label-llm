#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_python="$repo_root/.venv/bin/python"
model_source="${VLLM_MODEL_SOURCE:-}"
served_model_name=""
host="${VLLM_HOST:-127.0.0.1}"
port="${VLLM_PORT:-8001}"
extra_args=()

usage() {
  cat <<'EOF'
Usage: scripts/run-vllm-linux.sh --model-source <hf-id-or-local-path> [options] [-- extra-vllm-args...]

Options:
  --model-source <value>       Real Hugging Face model id or local model path
  --served-model-name <value>  Logical model name exposed to the backend. Defaults to VLLM_MODEL_NAME or qwen3-vl-4b
  --host <value>               Bind host. Default: 127.0.0.1
  --port <value>               Bind port. Default: 8001
  -h, --help                   Show this help

Environment:
  VLLM_MODEL_SOURCE     Same as --model-source
  VLLM_MODEL_NAME       Default served model name used by backend routing
  VLLM_HOST             Default host
  VLLM_PORT             Default port
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model-source)
      model_source="$2"
      shift 2
      ;;
    --served-model-name)
      served_model_name="$2"
      shift 2
      ;;
    --host)
      host="$2"
      shift 2
      ;;
    --port)
      port="$2"
      shift 2
      ;;
    --)
      shift
      extra_args+=("$@")
      break
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      extra_args+=("$1")
      shift
      ;;
  esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "scripts/run-vllm-linux.sh targets Linux. On non-Linux systems, use fallback profiles or run vLLM elsewhere." >&2
  exit 1
fi

if [[ ! -x "$venv_python" ]]; then
  echo "Backend virtualenv Python was not found: $venv_python" >&2
  echo "Run scripts/bootstrap-linux.sh first." >&2
  exit 1
fi

if [[ -z "$model_source" ]]; then
  echo "Missing model source. Set VLLM_MODEL_SOURCE or pass --model-source." >&2
  exit 1
fi

if [[ -z "$served_model_name" ]]; then
  served_model_name="${VLLM_MODEL_NAME:-qwen3-vl-4b}"
fi

exec "$venv_python" -m vllm.entrypoints.openai.api_server \
  --model "$model_source" \
  --served-model-name "$served_model_name" \
  --host "$host" \
  --port "$port" \
  "${extra_args[@]}"
