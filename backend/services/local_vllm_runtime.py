from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from backend.config import get_settings


LOCAL_VLLM_STATE_FILENAME = "local-vllm-state.json"
LOCAL_VLLM_STATE_VERSION = 1
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}
_VLLM_PROCESS_MARKER = "vllm.entrypoints.openai.api_server"


def local_vllm_state_path(root_dir: Path | None = None) -> Path:
    root = root_dir or get_settings().root_dir
    return (root / ".cache" / "start-linux" / LOCAL_VLLM_STATE_FILENAME).resolve()


def read_local_vllm_state(root_dir: Path | None = None) -> dict[str, Any] | None:
    path = local_vllm_state_path(root_dir)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def write_local_vllm_state(payload: dict[str, Any], root_dir: Path | None = None) -> Path:
    path = local_vllm_state_path(root_dir)
    stored = dict(payload)
    stored.setdefault("version", LOCAL_VLLM_STATE_VERSION)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def clear_local_vllm_state(root_dir: Path | None = None) -> None:
    path = local_vllm_state_path(root_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def is_local_vllm_managed_for_settings(
    settings=None,
    *,
    state: dict[str, Any] | None = None,
) -> bool:
    resolved_settings = settings or get_settings()
    payload = state or read_local_vllm_state()
    if not payload:
        return False

    managed_by = str(payload.get("managed_by") or "").strip()
    if managed_by != "scripts/start-linux.sh":
        return False

    normalized_settings_url = _normalize_base_url(str(resolved_settings.vllm_base_url or ""))
    normalized_state_url = _normalize_base_url(str(payload.get("base_url") or ""))
    if not normalized_settings_url or normalized_settings_url != normalized_state_url:
        return False

    parsed = urlparse(normalized_settings_url)
    return (parsed.hostname or "").strip().lower() in _LOCAL_HOSTS


def stop_local_managed_vllm(*, timeout: float = 90.0) -> dict[str, Any]:
    state = read_local_vllm_state()
    if not is_local_vllm_managed_for_settings(state=state):
        return {
            "status": "skipped",
            "reason": "unmanaged",
            "message": "Local managed vLLM state is unavailable for the active settings.",
        }

    pid = _extract_pid(state)
    if pid <= 0 or not _is_expected_vllm_pid(pid):
        _store_stopped_state(state)
        return {
            "status": "already_stopped",
            "pid": pid or None,
            "message": "Local managed vLLM is already stopped.",
        }

    forced = False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    deadline = time.monotonic() + max(1.0, timeout)
    while time.monotonic() < deadline:
        if not _is_expected_vllm_pid(pid):
            break
        time.sleep(0.2)

    if _is_expected_vllm_pid(pid):
        forced = True
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    _wait_for_vllm_shutdown(str(state.get("base_url") or ""), timeout=max(5.0, min(timeout, 30.0)))
    _store_stopped_state(state)

    return {
        "status": "stopped",
        "pid": pid,
        "forced": forced,
        "message": "Stopped local managed vLLM before GPU-exclusive work.",
    }


def ensure_local_managed_vllm_started(
    *,
    enable_lora: bool,
    timeout: float | None = None,
) -> dict[str, Any]:
    state = read_local_vllm_state()
    if not is_local_vllm_managed_for_settings(state=state):
        return {
            "status": "skipped",
            "reason": "unmanaged",
            "message": "Local managed vLLM state is unavailable for the active settings.",
        }

    if state is None:
        return {
            "status": "skipped",
            "reason": "missing_state",
            "message": "Local managed vLLM state file is missing.",
        }

    command = _build_command_for_start(state, enable_lora=enable_lora)
    running_pid = _extract_pid(state)
    running = running_pid > 0 and _is_expected_vllm_pid(running_pid)
    healthy = _is_vllm_healthy(str(state.get("base_url") or ""))

    if running and healthy and _command_satisfies_mode(state, enable_lora=enable_lora):
        return {
            "status": "already_running",
            "pid": running_pid,
            "command": command,
            "message": "Local managed vLLM is already healthy.",
        }

    if running:
        stop_local_managed_vllm(timeout=max(10.0, float(timeout or 90.0)))

    env = os.environ.copy()
    for key in state.get("env_unset", []):
        env.pop(str(key), None)
    for key, value in (state.get("env_set") or {}).items():
        env[str(key)] = str(value)

    cwd = Path(str(state.get("cwd") or get_settings().root_dir)).resolve()
    log_path = Path(str(state.get("log_path") or (get_settings().root_dir / "logs" / "vllm-runtime.log"))).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start_timeout = _resolve_start_timeout(state, timeout=timeout)
    commands = [command, *_build_retry_commands(command)]
    last_error: Exception | None = None

    for attempt_index, attempt_command in enumerate(commands):
        with log_path.open("ab") as log_handle:
            process = subprocess.Popen(  # noqa: S603
                attempt_command,
                cwd=str(cwd),
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        state["command"] = attempt_command
        state["pid"] = process.pid
        state["started_at"] = _utc_now()
        state["stopped_at"] = None
        state["enable_lora"] = "--enable-lora" in attempt_command
        write_local_vllm_state(state)

        try:
            _wait_for_vllm_ready(
                str(state.get("base_url") or ""),
                timeout=start_timeout,
                pid=process.pid,
            )
            return {
                "status": "started",
                "pid": process.pid,
                "command": attempt_command,
                "message": "Started local managed vLLM.",
            }
        except Exception as exc:
            last_error = exc
            try:
                os.kill(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            _store_stopped_state(state)
            _wait_for_vllm_shutdown(str(state.get("base_url") or ""), timeout=5.0)

            if attempt_index >= len(commands) - 1 or not _should_retry_with_lower_memory(log_path, exc):
                raise

    raise RuntimeError(f"Local managed vLLM did not start successfully: {last_error}")


def _build_command_for_start(state: dict[str, Any], *, enable_lora: bool) -> list[str]:
    command = [str(part) for part in (state.get("command") or []) if str(part).strip()]
    if not command:
        raise RuntimeError("Local managed vLLM state does not contain a restartable command.")

    command = [part for part in command if part != "--no-enable-lora"]
    if enable_lora and "--enable-lora" not in command:
        if not bool(state.get("supports_enable_lora", False)):
            raise RuntimeError("The installed vLLM does not support --enable-lora.")
        command.append("--enable-lora")
    return command


def _build_retry_commands(command: list[str]) -> list[list[str]]:
    retries: list[list[str]] = []
    original_gpu_util = _extract_flag_value(command, "--gpu-memory-utilization")
    original_max_num_seqs = _extract_flag_value(command, "--max-num-seqs")
    original_max_batched_tokens = _extract_flag_value(command, "--max-num-batched-tokens")

    try:
        gpu_util = float(original_gpu_util) if original_gpu_util is not None else None
    except Exception:
        gpu_util = None
    try:
        max_num_seqs = int(original_max_num_seqs) if original_max_num_seqs is not None else None
    except Exception:
        max_num_seqs = None
    try:
        max_batched_tokens = int(original_max_batched_tokens) if original_max_batched_tokens is not None else None
    except Exception:
        max_batched_tokens = None

    for next_gpu_util in _retry_gpu_utils(gpu_util):
        retry = list(command)
        retry = _upsert_flag(retry, "--gpu-memory-utilization", f"{next_gpu_util:.2f}")
        if max_num_seqs is not None and max_num_seqs > 1:
            retry = _upsert_flag(retry, "--max-num-seqs", "1")
        if max_batched_tokens is not None and max_batched_tokens > 2048:
            retry = _upsert_flag(retry, "--max-num-batched-tokens", "2048")
        retries.append(retry)

    return retries


def _retry_gpu_utils(current: float | None) -> list[float]:
    if current is None:
        return []
    candidates: list[float] = []
    for candidate in (current - 0.02, current - 0.05, current - 0.08):
        rounded = round(candidate, 2)
        if rounded < 0.72:
            continue
        if rounded >= current:
            continue
        if rounded not in candidates:
            candidates.append(rounded)
    return candidates


def _command_satisfies_mode(state: dict[str, Any], *, enable_lora: bool) -> bool:
    command = [str(part) for part in (state.get("command") or [])]
    if not enable_lora:
        return True
    return "--enable-lora" in command


def _extract_flag_value(command: list[str], flag: str) -> str | None:
    for index, part in enumerate(command):
        if part == flag and index + 1 < len(command):
            return str(command[index + 1])
        if part.startswith(f"{flag}="):
            return part.split("=", 1)[1]
    return None


def _upsert_flag(command: list[str], flag: str, value: str) -> list[str]:
    updated = list(command)
    for index, part in enumerate(updated):
        if part == flag:
            if index + 1 < len(updated):
                updated[index + 1] = value
                return updated
        if part.startswith(f"{flag}="):
            updated[index] = f"{flag}={value}"
            return updated
    updated.extend([flag, value])
    return updated


def _store_stopped_state(state: dict[str, Any]) -> None:
    stored = dict(state)
    stored["pid"] = None
    stored["stopped_at"] = _utc_now()
    write_local_vllm_state(stored)


def _resolve_start_timeout(state: dict[str, Any], *, timeout: float | None) -> float | None:
    if timeout is not None:
        return max(5.0, float(timeout))

    state_timeout = _coerce_positive_float(state.get("start_timeout"))
    if state_timeout is not None:
        return max(5.0, state_timeout)

    env_timeout = _coerce_positive_float(os.getenv("VLLM_START_TIMEOUT"))
    if env_timeout is not None:
        return max(5.0, env_timeout)

    return None


def _extract_pid(state: dict[str, Any] | None) -> int:
    if not state:
        return 0
    try:
        return int(state.get("pid") or 0)
    except Exception:
        return 0


def _is_expected_vllm_pid(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.exists():
        try:
            text = proc_cmdline.read_text(encoding="utf-8", errors="ignore").replace("\x00", " ")
        except Exception:
            return True
        return _VLLM_PROCESS_MARKER in text
    return True


def _wait_for_vllm_ready(base_url: str, *, timeout: float | None, pid: int | None = None) -> None:
    deadline = time.monotonic() + max(5.0, float(timeout or 300.0))
    probe_urls = _probe_urls(base_url)
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if pid is not None and pid > 0 and not _is_expected_vllm_pid(pid):
            raise RuntimeError(f"Local managed vLLM exited before becoming healthy (pid={pid}).")
        try:
            with httpx.Client(timeout=5.0) as client:
                for url in probe_urls:
                    response = client.get(url)
                    if response.status_code < 500:
                        return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(1.0)
    raise RuntimeError(f"Local managed vLLM did not become healthy: {last_error}")


def _wait_for_vllm_shutdown(base_url: str, *, timeout: float) -> None:
    deadline = time.monotonic() + max(1.0, timeout)
    probe_urls = _probe_urls(base_url)
    while time.monotonic() < deadline:
        if not _is_vllm_healthy(base_url, probe_urls=probe_urls):
            return
        time.sleep(0.5)


def _is_vllm_healthy(base_url: str, *, probe_urls: list[str] | None = None) -> bool:
    urls = probe_urls or _probe_urls(base_url)
    try:
        with httpx.Client(timeout=2.0) as client:
            for url in urls:
                response = client.get(url)
                if response.status_code < 500:
                    return True
    except Exception:
        return False
    return False


def _should_retry_with_lower_memory(log_path: Path, error: Exception) -> bool:
    text = str(error)
    if "less than desired GPU memory utilization" in text:
        return True
    if "exited before becoming healthy" in text:
        tail = _read_log_tail(log_path)
        if "less than desired GPU memory utilization" in tail:
            return True
        if "Decrease GPU memory utilization" in tail:
            return True
    return False


def _read_log_tail(log_path: Path, *, max_bytes: int = 16384) -> str:
    if not log_path.exists():
        return ""
    try:
        with log_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _probe_urls(base_url: str) -> list[str]:
    raw = str(base_url or "").rstrip("/")
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
        return [f"{origin}/health", f"{origin}{path}/models"]
    if path:
        return [f"{origin}{path}/health", f"{origin}{path}/v1/models"]
    return [f"{origin}/health", f"{origin}/v1/models"]


def _normalize_base_url(base_url: str) -> str:
    raw = base_url.strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = parsed.scheme or "http"
    if parsed.netloc:
        netloc = parsed.netloc
        path = parsed.path.rstrip("/")
    else:
        netloc = parsed.path
        path = ""
    return urlunparse((scheme, netloc, path, "", "", ""))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed <= 0:
        return None
    return parsed
