from __future__ import annotations

import signal
import sys
from pathlib import Path

import pytest

from backend.config import get_settings
from backend.services import local_vllm_runtime


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
