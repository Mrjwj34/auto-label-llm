#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile="test_real_stack"
venv_dir="$repo_root/.venv"
install_frontend=1
install_sam3=""
install_vllm=""
download_sam3_checkpoint=0
sam3_version=""
python_bin="${PYTHON_BIN:-python3}"

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap-linux.sh [options]

Options:
  --profile <name>              Profile to activate. Default: test_real_stack
  --venv <path>                 Virtualenv path. Default: .venv
  --skip-frontend               Skip npm install in frontend/
  --with-sam3                   Force-install real SAM3 dependencies
  --skip-sam3                   Skip real SAM3 dependencies
  --with-vllm                   Force-install vLLM dependencies
  --skip-vllm                   Skip vLLM dependencies
  --download-sam3-checkpoint    Download a SAM3 checkpoint into models/sam3/
  --sam3-version <sam3|sam3.1>  SAM3 checkpoint family for downloads
  -h, --help                    Show this help

Environment overrides:
  PYTHON_BIN            Python executable used to create the venv. Default: python3
  TORCH_PIP_SPEC        Torch packages to install. Default: "torch torchvision"
  TORCH_EXTRA_INDEX_URL Extra index URL for torch wheels. Default: https://download.pytorch.org/whl/cu126
  SAM3_PIP_SPEC         SAM3 packages to install. Default: "git+https://github.com/facebookresearch/sam3.git huggingface_hub"
  VLLM_PIP_SPEC         vLLM package spec. Default: "vllm"
EOF
}

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
    --skip-frontend)
      install_frontend=0
      shift
      ;;
    --with-sam3)
      install_sam3=1
      shift
      ;;
    --skip-sam3)
      install_sam3=0
      shift
      ;;
    --with-vllm)
      install_vllm=1
      shift
      ;;
    --skip-vllm)
      install_vllm=0
      shift
      ;;
    --download-sam3-checkpoint)
      download_sam3_checkpoint=1
      shift
      ;;
    --sam3-version)
      sam3_version="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "scripts/bootstrap-linux.sh targets Linux. On Windows/macOS, use fallback profiles instead." >&2
  exit 1
fi

if [[ "$venv_dir" != /* ]]; then
  venv_dir="$repo_root/$venv_dir"
fi

if [[ -z "$install_sam3" ]]; then
  if [[ "$profile" == "dev_low_resource" ]]; then
    install_sam3=0
  else
    install_sam3=1
  fi
fi

if [[ -z "$install_vllm" ]]; then
  if [[ "$profile" == "dev_low_resource" ]]; then
    install_vllm=0
  else
    install_vllm=1
  fi
fi

if [[ -z "$sam3_version" ]]; then
  if [[ "$profile" == "demo_prod" || "$profile" == "test_real_stack" ]]; then
    sam3_version="sam3.1"
  else
    sam3_version="sam3"
  fi
fi

if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Python executable not found: $python_bin" >&2
  exit 1
fi

if [[ "$install_frontend" -eq 1 ]] && ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found in PATH. Install Node.js/npm first or rerun with --skip-frontend." >&2
  exit 1
fi

mkdir -p "$repo_root/models/sam3" "$repo_root/logs" "$repo_root/data"

if [[ ! -x "$venv_dir/bin/python" ]]; then
  "$python_bin" -m venv "$venv_dir"
fi

venv_python="$venv_dir/bin/python"
pip_cmd=("$venv_python" -m pip)

"${pip_cmd[@]}" install --upgrade pip setuptools wheel
"${pip_cmd[@]}" install -r "$repo_root/requirements.txt"
"$venv_python" "$repo_root/scripts/use_profile.py" --repo-root "$repo_root" --profile "$profile"

if [[ "$install_frontend" -eq 1 ]]; then
  (
    cd "$repo_root/frontend"
    npm install
  )
fi

if [[ "$install_sam3" -eq 1 || "$install_vllm" -eq 1 ]]; then
  read -r -a torch_packages <<<"${TORCH_PIP_SPEC:-torch torchvision}"
  "${pip_cmd[@]}" install --extra-index-url "${TORCH_EXTRA_INDEX_URL:-https://download.pytorch.org/whl/cu126}" "${torch_packages[@]}"
fi

if [[ "$install_sam3" -eq 1 ]]; then
  read -r -a sam3_packages <<<"${SAM3_PIP_SPEC:-git+https://github.com/facebookresearch/sam3.git huggingface_hub}"
  "${pip_cmd[@]}" install "${sam3_packages[@]}"
fi

if [[ "$install_vllm" -eq 1 ]]; then
  read -r -a vllm_packages <<<"${VLLM_PIP_SPEC:-vllm}"
  "${pip_cmd[@]}" install "${vllm_packages[@]}"
fi

if [[ "$download_sam3_checkpoint" -eq 1 ]]; then
  "$venv_python" - "$repo_root" "$sam3_version" <<'PY'
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
print(f"SAM3 checkpoint ready: {destination_path}")
PY
fi

cat <<EOF
Bootstrap complete.
Profile       : $profile
Backend env   : $repo_root/.env.active
Frontend env  : $repo_root/frontend/.env.local
Virtualenv    : $venv_dir
Real SAM3     : $install_sam3
Real vLLM     : $install_vllm
SAM3 version  : $sam3_version

Notes:
- M11 uses an OpenAI-compatible endpoint at \$VLLM_BASE_URL. The intended real backend is local/private vLLM on Linux, not the OpenAI cloud API.
- Current lora:{job_id} activation only switches route metadata and requested model tags. Real vLLM LoRA adapter mount/reload is still planned work.
- SAM3 checkpoints placed under $repo_root/models/sam3/ are auto-discovered by the backend. You can also set SAM3_CHECKPOINT_PATH to a specific file.
EOF
