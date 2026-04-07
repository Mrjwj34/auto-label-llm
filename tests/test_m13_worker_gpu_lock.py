from __future__ import annotations

import threading
import time

import pytest

from backend.config import get_settings
from backend.services.redis_client import _get_redis_client
from backend.tasks import task_manager as task_manager_module
from backend.tasks.task_manager import get_task_manager
from backend.tasks.worker import RedisTaskWorker
from backend.utils.gpu_lock import GPUBusyError, GPULock


def _reset_task_runtime(monkeypatch, tmp_path, *, redis_name: str, sam_max_concurrency: str = "1") -> None:
    root_dir = tmp_path / redis_name
    data_dir = root_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("ROOT_DIR", str(root_dir))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("REDIS_URL", f"fakeredis://{redis_name}")
    monkeypatch.setenv("SAM_MAX_CONCURRENCY", sam_max_concurrency)
    monkeypatch.setenv("TASK_WORKER_CONCURRENCY", "1")

    get_settings.cache_clear()
    _get_redis_client.cache_clear()
    task_manager_module._manager = None


def test_worker_processes_queued_tasks_in_order(monkeypatch, tmp_path):
    _reset_task_runtime(monkeypatch, tmp_path, redis_name="m13-worker-order")

    events: list[tuple[str, int]] = []

    def demo_handler(ctx, payload):
        value = int(payload["value"])
        events.append(("start", value))
        ctx.set_progress(60, f"working {value}")
        time.sleep(0.05)
        events.append(("done", value))

    worker = RedisTaskWorker(handlers={"demo": demo_handler}, queues=["demo"], concurrency=1).start_in_background()
    manager = get_task_manager()

    try:
        first_task_id = manager.create(kind="demo", payload={"value": 1}, queue="demo")
        second_task_id = manager.create(kind="demo", payload={"value": 2}, queue="demo")

        deadline = time.time() + 5.0
        while time.time() < deadline:
            first_state = manager.get(first_task_id)
            second_state = manager.get(second_task_id)
            if first_state is not None and second_state is not None and second_state.status == "SUCCESS":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("queued tasks did not finish in time")

        assert events == [("start", 1), ("done", 1), ("start", 2), ("done", 2)]
        assert manager.to_dict(first_task_id)["status"] == "SUCCESS"
        assert manager.to_dict(second_task_id)["status"] == "SUCCESS"
        assert manager.to_dict(second_task_id)["progress"] == 100
    finally:
        worker.stop()


def test_gpu_training_lock_waits_for_active_sam(monkeypatch, tmp_path):
    _reset_task_runtime(monkeypatch, tmp_path, redis_name="m13-gpu-wait")

    timeline: list[str] = []
    sam_entered = threading.Event()

    def run_sam():
        with GPULock.acquire_sam(timeout=0.5):
            timeline.append("sam_enter")
            sam_entered.set()
            time.sleep(0.2)
            timeline.append("sam_exit")

    def run_training():
        assert sam_entered.wait(timeout=1.0)
        with GPULock.acquire_training():
            timeline.append("train_enter")

    sam_thread = threading.Thread(target=run_sam, daemon=True)
    training_thread = threading.Thread(target=run_training, daemon=True)
    sam_thread.start()
    training_thread.start()
    sam_thread.join(timeout=4.0)
    training_thread.join(timeout=4.0)

    assert not sam_thread.is_alive()
    assert not training_thread.is_alive()
    assert timeline == ["sam_enter", "sam_exit", "train_enter"]


def test_gpu_training_lock_blocks_new_sam_requests(monkeypatch, tmp_path):
    _reset_task_runtime(monkeypatch, tmp_path, redis_name="m13-gpu-block")

    release_training = threading.Event()
    training_entered = threading.Event()

    def run_training():
        with GPULock.acquire_training(timeout=1.0):
            training_entered.set()
            assert release_training.wait(timeout=1.0)

    training_thread = threading.Thread(target=run_training, daemon=True)
    training_thread.start()
    assert training_entered.wait(timeout=1.0)

    with pytest.raises(GPUBusyError):
        with GPULock.acquire_sam(timeout=0.1):
            pass

    release_training.set()
    training_thread.join(timeout=2.0)
    assert not training_thread.is_alive()
