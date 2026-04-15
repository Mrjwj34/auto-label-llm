from __future__ import annotations

from contextlib import contextmanager
import signal
import sys
from pathlib import Path

import pytest

from backend.config import get_settings
from backend.models.project import Project
from backend.services import local_vllm_runtime
from backend.services import vllm_client
from backend.services.vllm_client import InferenceRoute


@pytest.fixture()
def local_vllm_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root_dir = tmp_path / "runtime-root"
    root_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:8001")
    get_settings.cache_clear()
    yield root_dir
    get_settings.cache_clear()


def _write_state(root_dir: Path, **overrides):
    payload = {
        "version": 1,
        "managed_by": "scripts/start-linux.sh",
        "repo_root": root_dir.as_posix(),
        "cwd": root_dir.as_posix(),
        "base_url": "http://127.0.0.1:8001",
        "host": "127.0.0.1",
        "port": 8001,
        "model_source": "Qwen/Qwen3-VL-8B-Instruct-FP8",
        "served_model_name": "qwen3-vl-8b",
        "pid": 1234,
        "log_path": (root_dir / "logs" / "vllm.log").as_posix(),
        "env_unset": ["VLLM_BASE_URL"],
        "env_set": {"PYTHONUNBUFFERED": "1"},
        "command": [sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", "demo"],
        "start_timeout": 900,
        "supports_enable_lora": True,
    }
    payload.update(overrides)
    local_vllm_runtime.write_local_vllm_state(payload, root_dir=root_dir)


def test_is_local_vllm_managed_for_settings_matches_local_state(local_vllm_env: Path):
    _write_state(local_vllm_env)

    assert local_vllm_runtime.is_local_vllm_managed_for_settings() is True


def test_ensure_local_managed_vllm_started_adds_enable_lora_and_updates_state(
    local_vllm_env: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _write_state(local_vllm_env, pid=None)
    seen: dict[str, object] = {}

    class _FakeProcess:
        pid = 4321

    def fake_popen(command, cwd, env, stdout, stderr, start_new_session):  # noqa: ANN001
        seen["command"] = command
        seen["cwd"] = cwd
        seen["env"] = env
        return _FakeProcess()

    monkeypatch.setattr(local_vllm_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(local_vllm_runtime, "_wait_for_vllm_ready", lambda *args, **kwargs: None)

    assert get_settings().vllm_base_url == "http://127.0.0.1:8001"
    monkeypatch.setenv("VLLM_BASE_URL", "will-be-unset")
    result = local_vllm_runtime.ensure_local_managed_vllm_started(enable_lora=True, timeout=5)

    assert result["status"] == "started"
    assert "--enable-lora" in seen["command"]
    assert seen["cwd"] == str(local_vllm_env.resolve())
    assert "VLLM_BASE_URL" not in seen["env"]

    stored = local_vllm_runtime.read_local_vllm_state(local_vllm_env)
    assert stored is not None
    assert stored["pid"] == 4321
    assert "--enable-lora" in stored["command"]


def test_ensure_local_managed_vllm_started_uses_state_timeout_when_not_overridden(
    local_vllm_env: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _write_state(local_vllm_env, pid=None, start_timeout=901)

    class _FakeProcess:
        pid = 4321

    seen: dict[str, object] = {}

    monkeypatch.setattr(
        local_vllm_runtime.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        local_vllm_runtime,
        "_wait_for_vllm_ready",
        lambda base_url, *, timeout, pid=None: seen.setdefault("timeout", timeout),
    )

    result = local_vllm_runtime.ensure_local_managed_vllm_started(enable_lora=False)

    assert result["status"] == "started"
    assert seen["timeout"] == 901


def test_ensure_local_managed_vllm_started_fails_fast_when_process_exits_before_healthy(
    local_vllm_env: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _write_state(local_vllm_env, pid=None)

    class _FakeProcess:
        pid = 4321

    class _FailingClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):  # noqa: ANN001
            raise RuntimeError(f"connection refused for {url}")

    monkeypatch.setattr(local_vllm_runtime.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess())
    monkeypatch.setattr(local_vllm_runtime.httpx, "Client", lambda timeout=5.0: _FailingClient())
    monkeypatch.setattr(local_vllm_runtime, "_is_expected_vllm_pid", lambda pid: False)

    with pytest.raises(RuntimeError, match="exited before becoming healthy"):
        local_vllm_runtime.ensure_local_managed_vllm_started(enable_lora=False, timeout=5)

    stored = local_vllm_runtime.read_local_vllm_state(local_vllm_env)
    assert stored is not None
    assert stored["pid"] is None


def test_ensure_local_managed_vllm_started_retries_with_lower_memory_settings(
    local_vllm_env: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    log_path = local_vllm_env / "logs" / "vllm.log"
    _write_state(
        local_vllm_env,
        pid=None,
        log_path=log_path.as_posix(),
        command=[
            sys.executable,
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            "demo",
            "--gpu-memory-utilization",
            "0.90",
            "--max-num-seqs",
            "2",
            "--max-num-batched-tokens",
            "4096",
        ],
    )

    seen_commands: list[list[str]] = []
    wait_calls = {"count": 0}

    class _FakeProcess:
        def __init__(self, pid: int):
            self.pid = pid

    def fake_popen(command, cwd, env, stdout, stderr, start_new_session):  # noqa: ANN001
        seen_commands.append(list(command))
        return _FakeProcess(4300 + len(seen_commands))

    def fake_wait(base_url, *, timeout, pid=None):  # noqa: ANN001
        wait_calls["count"] += 1
        if wait_calls["count"] == 1:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                "ValueError: Free memory on device cuda:0 (20.9/23.52 GiB) on startup is less than desired "
                "GPU memory utilization (0.9, 21.17 GiB). Decrease GPU memory utilization or reduce GPU memory used "
                "by other processes.\n",
                encoding="utf-8",
            )
            raise RuntimeError("Local managed vLLM exited before becoming healthy (pid=4301).")

    monkeypatch.setattr(local_vllm_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(local_vllm_runtime, "_wait_for_vllm_ready", fake_wait)
    monkeypatch.setattr(local_vllm_runtime, "_wait_for_vllm_shutdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(local_vllm_runtime.os, "kill", lambda pid, sig: None)

    result = local_vllm_runtime.ensure_local_managed_vllm_started(enable_lora=False, timeout=5)

    assert result["status"] == "started"
    assert len(seen_commands) == 2
    assert local_vllm_runtime._extract_flag_value(seen_commands[0], "--gpu-memory-utilization") == "0.90"
    assert local_vllm_runtime._extract_flag_value(seen_commands[1], "--gpu-memory-utilization") == "0.88"
    assert local_vllm_runtime._extract_flag_value(seen_commands[1], "--max-num-seqs") == "1"
    assert local_vllm_runtime._extract_flag_value(seen_commands[1], "--max-num-batched-tokens") == "2048"

    stored = local_vllm_runtime.read_local_vllm_state(local_vllm_env)
    assert stored is not None
    assert stored["pid"] == 4302
    assert local_vllm_runtime._extract_flag_value(stored["command"], "--gpu-memory-utilization") == "0.88"


def test_stop_local_managed_vllm_marks_state_stopped(local_vllm_env: Path, monkeypatch: pytest.MonkeyPatch):
    _write_state(local_vllm_env, pid=5678)
    running = {"value": True}
    killed: list[tuple[int, int]] = []

    def fake_is_expected(pid: int) -> bool:
        return running["value"] and pid == 5678

    def fake_kill(pid: int, sig: int) -> None:
        killed.append((pid, sig))
        running["value"] = False

    monkeypatch.setattr(local_vllm_runtime, "_is_expected_vllm_pid", fake_is_expected)
    monkeypatch.setattr(local_vllm_runtime.os, "kill", fake_kill)
    monkeypatch.setattr(local_vllm_runtime, "_wait_for_vllm_shutdown", lambda *args, **kwargs: None)

    result = local_vllm_runtime.stop_local_managed_vllm(timeout=1)

    assert result["status"] == "stopped"
    assert killed[0] == (5678, signal.SIGTERM)

    stored = local_vllm_runtime.read_local_vllm_state(local_vllm_env)
    assert stored is not None
    assert stored["pid"] is None


def test_local_runtime_sync_boots_managed_service_and_loads_lora(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings().model_copy(deep=True)
    settings.annotation_backend = "openai_compatible"
    monkeypatch.setattr(vllm_client, "get_settings", lambda: settings)
    monkeypatch.setattr(vllm_client, "is_local_vllm_managed_for_settings", lambda settings: True)
    monkeypatch.setattr(
        vllm_client,
        "ensure_local_managed_vllm_started",
        lambda *, enable_lora, timeout=None: {"status": "started", "pid": 4321, "message": "started"},
    )

    @contextmanager
    def fake_reload_lock(*args, **kwargs):
        yield

    monkeypatch.setattr(vllm_client.GPULock, "acquire_model_reload", fake_reload_lock)
    monkeypatch.setattr(
        vllm_client,
        "_sync_vllm_runtime_actions",
        lambda *args, **kwargs: {"actions": [{"action": "load", "model_tag": "lora:7"}]},
    )

    project = Project(id=1, name="demo", task_type="detection", config="{}")
    route = InferenceRoute(
        requested_model_tag="lora:7",
        effective_model_tag="lora:7",
        request_model_name="lora:7",
        base_model_name="qwen3-vl-8b",
        resolved_project_profile="test_real_stack",
        route_kind="lora",
        adapter_path="models/lora/7",
        finetune_job_id=7,
    )

    result = vllm_client._sync_local_managed_vllm_runtime(
        project,
        previous_model_tag="base",
        target_route=route,
        db=None,
    )

    assert result is not None
    assert result["mode"] == "local_managed_vllm"
    assert result["status"] == "synced"
    assert result["actions"][0]["action"] == "start"
    assert result["actions"][1]["action"] == "load"
