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

import redis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the M13 browser verification flow against a real Redis instance and a standalone worker."
    )
    parser.add_argument(
        "--redis-url",
        default="redis://127.0.0.1:6379/15",
        help="Redis URL used by both the API process and the standalone worker.",
    )
    parser.add_argument("--api-port", type=int, default=8014, help="Backend port for the temporary verification stack.")
    parser.add_argument("--app-port", type=int, default=5176, help="Frontend port for the temporary verification stack.")
    parser.add_argument(
        "--artifact-dir",
        default=str(Path("output") / "playwright" / "m13-real-redis"),
        help="Directory used for logs, screenshots, and the temporary runtime root.",
    )
    parser.add_argument(
        "--profile",
        default="dev_low_resource",
        help="Application profile used for verification. Keep dev_low_resource unless you want a heavier stack.",
    )
    parser.add_argument(
        "--annotation-backend",
        default="stub",
        choices=("stub", "openai_compatible"),
        help="Annotation backend used during the verification run.",
    )
    parser.add_argument(
        "--flush-redis-db",
        action="store_true",
        help="Flush the selected Redis database before the verification run.",
    )
    return parser.parse_args()


def wait_for_http(url: str, *, timeout: float) -> None:
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                if 200 <= response.status < 500:
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


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    runtime_root = ensure_runtime_root(repo_root, artifact_dir)
    runtime_data = runtime_root / "data"

    maybe_flush_redis(args.redis_url, enabled=args.flush_redis_db)

    common_env = os.environ.copy()
    common_env.update(
        {
            "ROOT_DIR": str(runtime_root),
            "DATA_DIR": str(runtime_data),
            "DATABASE_URL": f"sqlite:///{(runtime_data / 'app.db').as_posix()}",
            "APP_PROFILE": args.profile,
            "ANNOTATION_BACKEND": args.annotation_backend,
            "REDIS_URL": args.redis_url,
            "CORS_ALLOW_ORIGINS": json.dumps([f"http://localhost:{args.app_port}"]),
            "TASK_WORKER_CONCURRENCY": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )

    backend_env = dict(common_env)
    backend_env["TASK_EMBEDDED_WORKER"] = "false"

    worker_env = dict(common_env)
    worker_env["TASK_EMBEDDED_WORKER"] = "false"

    frontend_env = os.environ.copy()
    frontend_env.update(
        {
            "VITE_API_BASE_URL": f"http://127.0.0.1:{args.api_port}",
        }
    )

    python_exe = repo_root / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        raise RuntimeError(f"Python executable not found: {python_exe}")
    npm_exe = "npm.cmd" if os.name == "nt" else "npm"

    backend_process = worker_process = frontend_process = None
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
            env=backend_env,
            stdout_path=artifact_dir / "backend.out.log",
            stderr_path=artifact_dir / "backend.err.log",
        )
        opened_logs.extend([out_handle, err_handle])

        worker_process, out_handle, err_handle = start_process(
            command=[str(python_exe), "-m", "backend.task_worker_main"],
            cwd=repo_root,
            env=worker_env,
            stdout_path=artifact_dir / "worker.out.log",
            stderr_path=artifact_dir / "worker.err.log",
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

        browser_env = os.environ.copy()
        browser_env.update(
            {
                "APP_BASE_URL": f"http://localhost:{args.app_port}",
                "API_BASE_URL": f"http://127.0.0.1:{args.api_port}",
                "PLAYWRIGHT_ARTIFACT_DIR": str(artifact_dir),
            }
        )
        subprocess.run(  # noqa: S603
            ["node", str(repo_root / "scripts" / "e2e-m13.cjs")],
            cwd=str(repo_root),
            env=browser_env,
            check=True,
        )
        print(f"Verification completed. Result: {(artifact_dir / 'browser-result.json').as_posix()}")
        return 0
    finally:
        for process in (frontend_process, worker_process, backend_process):
            stop_process(process)
        for handle in opened_logs:
            try:
                handle.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
