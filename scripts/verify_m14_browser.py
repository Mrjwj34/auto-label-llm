from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

import httpx
import redis
from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the M14 browser verification flow with a real Redis instance and a mock LLaMA-Factory subprocess."
    )
    parser.add_argument(
        "--redis-url",
        default="redis://127.0.0.1:6379/14",
        help="Redis URL used by the temporary backend stack.",
    )
    parser.add_argument("--api-port", type=int, default=8020, help="Backend port for the temporary verification stack.")
    parser.add_argument("--app-port", type=int, default=5178, help="Frontend port for the temporary verification stack.")
    parser.add_argument(
        "--artifact-dir",
        default=str(Path("output") / "playwright" / "m14-browser"),
        help="Directory used for logs, screenshots, and the temporary runtime root.",
    )
    parser.add_argument(
        "--flush-redis-db",
        action="store_true",
        help="Flush the selected Redis database before the verification run.",
    )
    return parser.parse_args()


def wait_for_http(url: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if 200 <= response.status_code < 500:
                return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"Timed out waiting for {url}")


def wait_for_tcp(host: str, port: int, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for TCP {host}:{port}")


def start_process(
    *,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[subprocess.Popen[str], TextIO, TextIO]:
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    creationflags = 0
    popen_kwargs: dict[str, object] = {}
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=str(cwd),
        env=env,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
        creationflags=creationflags,
        **popen_kwargs,
    )
    return process, stdout_handle, stderr_handle


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(  # noqa: S603
                ["cmd", "/c", "taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5.0)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def ensure_runtime_root(repo_root: Path, artifact_dir: Path) -> Path:
    runtime_root = artifact_dir / "runtime"
    profiles_target = runtime_root / "configs" / "profiles"
    frontend_target = runtime_root / "frontend"
    data_target = runtime_root / "data"
    profiles_target.mkdir(parents=True, exist_ok=True)
    frontend_target.mkdir(parents=True, exist_ok=True)
    data_target.mkdir(parents=True, exist_ok=True)

    for profile in (repo_root / "configs" / "profiles").glob("*.json"):
        shutil.copy2(profile, profiles_target / profile.name)
    return runtime_root


def maybe_flush_redis(redis_url: str, *, enabled: bool) -> None:
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    client.ping()
    if enabled:
        client.flushdb()


def create_browser_context(*, api_base_url: str, frontend_url: str, artifact_dir: Path) -> dict[str, int | str]:
    sample_image = artifact_dir / "sample.png"
    image = Image.new("RGB", (128, 96), color=(96, 156, 84))
    image.save(sample_image, format="PNG")

    with httpx.Client(base_url=api_base_url, timeout=10.0) as client:
        project = client.post("/api/projects", json={"name": "m14-browser", "task_type": "detection"})
        project.raise_for_status()
        project_id = int(project.json()["data"]["id"])

        patch = client.patch(f"/api/projects/{project_id}/settings", json={"labels": ["crack"]})
        patch.raise_for_status()

        upload = client.post(
            f"/api/projects/{project_id}/images/upload",
            files={"files[]": ("sample.png", sample_image.read_bytes(), "image/png")},
        )
        upload.raise_for_status()
        image_id = int(upload.json()["data"]["image_ids"][0])

        annotation = client.post(
            f"/api/images/{image_id}/annotations",
            json={"label": "crack", "bbox": [0.2, 0.25, 0.65, 0.75], "source": "manual"},
        )
        annotation.raise_for_status()
        annotation_id = int(annotation.json()["data"]["id"])

        confirm = client.patch(f"/api/annotations/{annotation_id}/confirm")
        confirm.raise_for_status()

    payload: dict[str, int | str] = {
        "project_id": project_id,
        "image_id": image_id,
        "annotation_id": annotation_id,
        "project_url": f"{frontend_url}/projects/{project_id}",
        "api_base_url": api_base_url,
        "frontend_url": frontend_url,
        "sample_path": str(sample_image.resolve()),
    }
    (artifact_dir / "context.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    runtime_root = ensure_runtime_root(repo_root, artifact_dir)
    runtime_data = runtime_root / "data"

    maybe_flush_redis(args.redis_url, enabled=args.flush_redis_db)

    python_exe = repo_root / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        raise RuntimeError(f"Python executable not found: {python_exe}")
    npm_exe = "npm.cmd" if os.name == "nt" else "npm"
    mock_cli = repo_root / "tests" / "helpers" / "mock_llamafactory_cli.py"
    llamafactory_cli = subprocess.list2cmdline([str(python_exe), str(mock_cli)]) if os.name == "nt" else f"{python_exe} {mock_cli}"

    common_env = os.environ.copy()
    common_env.update(
        {
            "ROOT_DIR": str(runtime_root),
            "DATA_DIR": str(runtime_data),
            "DATABASE_URL": f"sqlite:///{(runtime_data / 'app.db').as_posix()}",
            "APP_PROFILE": "dev_low_resource",
            "ANNOTATION_BACKEND": "stub",
            "REDIS_URL": args.redis_url,
            "CORS_ALLOW_ORIGINS": json.dumps([f"http://localhost:{args.app_port}", f"http://127.0.0.1:{args.app_port}"]),
            "TASK_EMBEDDED_WORKER": "true",
            "TASK_WORKER_CONCURRENCY": "1",
            "FINETUNE_BACKEND": "llamafactory",
            "LLAMAFACTORY_CLI": llamafactory_cli,
            "PYTHONUNBUFFERED": "1",
        }
    )

    frontend_env = os.environ.copy()
    frontend_env.update(
        {
            "VITE_API_BASE_URL": f"http://127.0.0.1:{args.api_port}",
        }
    )

    backend_process = frontend_process = None
    opened_logs: list[TextIO] = []

    try:
        backend_process, out_handle, err_handle = start_process(
            command=[
                str(python_exe),
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
            ],
            cwd=repo_root,
            env=common_env,
            stdout_path=artifact_dir / "backend.out.log",
            stderr_path=artifact_dir / "backend.err.log",
        )
        opened_logs.extend([out_handle, err_handle])

        frontend_process, out_handle, err_handle = start_process(
            command=[
                npm_exe,
                "run",
                "dev",
                "--",
                "--host",
                "localhost",
                "--port",
                str(args.app_port),
                "--strictPort",
            ],
            cwd=repo_root / "frontend",
            env=frontend_env,
            stdout_path=artifact_dir / "frontend.out.log",
            stderr_path=artifact_dir / "frontend.err.log",
        )
        opened_logs.extend([out_handle, err_handle])

        wait_for_tcp("127.0.0.1", args.api_port, timeout=30.0)
        wait_for_http(f"http://127.0.0.1:{args.api_port}/healthz", timeout=30.0)
        wait_for_http(f"http://localhost:{args.app_port}", timeout=30.0)

        context = create_browser_context(
            api_base_url=f"http://127.0.0.1:{args.api_port}",
            frontend_url=f"http://localhost:{args.app_port}",
            artifact_dir=artifact_dir,
        )

        browser_env = os.environ.copy()
        browser_env.update(
            {
                "APP_BASE_URL": f"http://localhost:{args.app_port}",
                "API_BASE_URL": f"http://127.0.0.1:{args.api_port}",
                "PLAYWRIGHT_ARTIFACT_DIR": str(artifact_dir),
            }
        )
        subprocess.run(  # noqa: S603
            ["node", str(repo_root / "scripts" / "e2e-m14.cjs")],
            cwd=str(repo_root),
            env=browser_env,
            check=True,
        )

        summary = {
            "ok": True,
            "api_port": args.api_port,
            "app_port": args.app_port,
            "redis_url": args.redis_url,
            "project_id": context["project_id"],
            "artifact_dir": str(artifact_dir),
        }
        (artifact_dir / "verify-result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop_process(frontend_process)
        stop_process(backend_process)
        for handle in opened_logs:
            handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
