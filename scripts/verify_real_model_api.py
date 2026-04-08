from __future__ import annotations

import argparse
import base64
import mimetypes
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


DEFAULT_IMAGE_URL = "http://images.cocodataset.org/val2017/000000039769.jpg"


@dataclass
class UploadedImage:
    image_id: int
    filename: str
    content: bytes
    media_type: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the real vLLM service and the backend auto-annotation flow end to end."
    )
    parser.add_argument("--backend-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--served-model-name", default="qwen3-vl-8b")
    parser.add_argument("--image-url", default=DEFAULT_IMAGE_URL)
    parser.add_argument("--image-path", default="")
    parser.add_argument("--task-timeout", type=float, default=300.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--request-timeout", type=float, default=600.0)
    parser.add_argument("--keep-project", action="store_true")
    parser.add_argument("--labels", nargs="+", default=["cat", "couch"])
    return parser.parse_args()


def unwrap_ok(response: httpx.Response) -> Any:
  body = response.json()
  if not isinstance(body, dict):
      raise RuntimeError(f"unexpected response payload: {body!r}")
  if body.get("code") != 200:
      raise RuntimeError(f"unexpected response code: {body!r}")
  return body.get("data")


def build_data_url(content: bytes, media_type: str) -> str:
    payload = base64.b64encode(content).decode("ascii")
    return f"data:{media_type};base64,{payload}"


def load_image(client: httpx.Client, args: argparse.Namespace) -> UploadedImage:
    if args.image_path:
        path = Path(args.image_path).expanduser().resolve()
        content = path.read_bytes()
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return UploadedImage(image_id=0, filename=path.name, content=content, media_type=media_type)

    response = client.get(args.image_url)
    response.raise_for_status()
    filename = args.image_url.rstrip("/").rsplit("/", 1)[-1] or "sample.jpg"
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip() or "image/jpeg"
    return UploadedImage(image_id=0, filename=filename, content=response.content, media_type=media_type)


def ensure_backend_health(client: httpx.Client, base_url: str) -> None:
    response = client.get(f"{base_url.rstrip('/')}/api/health")
    response.raise_for_status()
    payload = unwrap_ok(response)
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError(f"backend health check failed: {payload!r}")


def ensure_vllm_health(client: httpx.Client, base_url: str, model_name: str) -> None:
    response = client.get(f"{base_url.rstrip('/')}/v1/models")
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected vLLM models payload: {payload!r}")
    available = [str(item.get("id")) for item in data if isinstance(item, dict)]
    if model_name not in available:
        raise RuntimeError(f"served model {model_name!r} not found in {available!r}")


def run_direct_vllm_chat(client: httpx.Client, base_url: str, model_name: str, image: UploadedImage) -> str:
    response = client.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        json={
            "model": model_name,
            "temperature": 0,
            "max_tokens": 64,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image in one short sentence."},
                        {"type": "image_url", "image_url": {"url": build_data_url(image.content, image.media_type)}},
                    ],
                }
            ],
        },
    )
    response.raise_for_status()
    payload = response.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"unexpected vLLM chat payload: {payload!r}") from exc

    if isinstance(content, list):
        text = "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        ).strip()
    else:
        text = str(content).strip()
    if not text:
        raise RuntimeError(f"empty vLLM chat response: {payload!r}")
    return text


def patch_system_llm_model(client: httpx.Client, base_url: str, model_name: str) -> None:
    response = client.patch(
        f"{base_url.rstrip('/')}/api/system/settings",
        json={"llm": {"base_model": model_name, "max_tokens": 1024}},
    )
    response.raise_for_status()
    unwrap_ok(response)


def create_project(client: httpx.Client, base_url: str) -> int:
    response = client.post(
        f"{base_url.rstrip('/')}/api/projects",
        json={"name": f"real-model-smoke-{int(time.time())}", "task_type": "detection"},
    )
    response.raise_for_status()
    payload = unwrap_ok(response)
    project_id = int(payload["id"])
    return project_id


def patch_project_labels(client: httpx.Client, base_url: str, project_id: int, labels: list[str]) -> None:
    response = client.patch(
        f"{base_url.rstrip('/')}/api/projects/{project_id}/settings",
        json={"labels": labels},
    )
    response.raise_for_status()
    unwrap_ok(response)


def upload_image(client: httpx.Client, base_url: str, project_id: int, image: UploadedImage) -> int:
    response = client.post(
        f"{base_url.rstrip('/')}/api/projects/{project_id}/images/upload",
        files=[("files", (image.filename, image.content, image.media_type))],
    )
    response.raise_for_status()
    payload = unwrap_ok(response)
    image_ids = payload.get("image_ids")
    if not isinstance(image_ids, list) or not image_ids:
        raise RuntimeError(f"upload did not return image_ids: {payload!r}")
    return int(image_ids[0])


def trigger_annotation(client: httpx.Client, base_url: str, project_id: int) -> str:
    response = client.post(
        f"{base_url.rstrip('/')}/api/projects/{project_id}/annotate",
        json={"only_pending": True},
    )
    response.raise_for_status()
    payload = unwrap_ok(response)
    task_id = str(payload["task_id"])
    return task_id


def wait_for_task_success(
    client: httpx.Client,
    base_url: str,
    task_id: str,
    *,
    timeout_seconds: float,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"{base_url.rstrip('/')}/api/tasks/{task_id}/status")
        response.raise_for_status()
        payload = unwrap_ok(response)
        if not isinstance(payload, dict):
            raise RuntimeError(f"unexpected task payload: {payload!r}")
        status = str(payload.get("status") or "")
        if status == "SUCCESS":
            return payload
        if status == "FAILURE":
            raise RuntimeError(f"annotation task failed: {payload!r}")
        time.sleep(poll_interval)
    raise RuntimeError(f"annotation task did not finish within {timeout_seconds:.1f}s")


def fetch_annotations(client: httpx.Client, base_url: str, image_id: int) -> list[dict[str, Any]]:
    response = client.get(f"{base_url.rstrip('/')}/api/images/{image_id}/annotations")
    response.raise_for_status()
    payload = unwrap_ok(response)
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected annotations payload: {payload!r}")
    return [item for item in payload if isinstance(item, dict)]


def delete_project(client: httpx.Client, base_url: str, project_id: int) -> None:
    response = client.delete(f"{base_url.rstrip('/')}/api/projects/{project_id}")
    response.raise_for_status()
    unwrap_ok(response)


def main() -> int:
    args = parse_args()
    backend_base_url = args.backend_base_url.rstrip("/")
    vllm_base_url = args.vllm_base_url.rstrip("/")
    timeout = httpx.Timeout(args.request_timeout, connect=min(args.request_timeout, 30.0))

    with httpx.Client(timeout=timeout) as client:
        ensure_backend_health(client, backend_base_url)
        image = load_image(client, args)
        ensure_vllm_health(client, vllm_base_url, args.served_model_name)
        direct_response = run_direct_vllm_chat(client, vllm_base_url, args.served_model_name, image)
        print(f"[verify-real-model] direct-vllm-chat: {direct_response}", flush=True)

        patch_system_llm_model(client, backend_base_url, args.served_model_name)
        project_id = create_project(client, backend_base_url)
        print(f"[verify-real-model] created project: {project_id}", flush=True)

        try:
            patch_project_labels(client, backend_base_url, project_id, args.labels)
            image_id = upload_image(client, backend_base_url, project_id, image)
            print(f"[verify-real-model] uploaded image: {image_id}", flush=True)

            task_id = trigger_annotation(client, backend_base_url, project_id)
            print(f"[verify-real-model] annotation task: {task_id}", flush=True)
            task_payload = wait_for_task_success(
                client,
                backend_base_url,
                task_id,
                timeout_seconds=args.task_timeout,
                poll_interval=args.poll_interval,
            )
            print(f"[verify-real-model] task success: {task_payload}", flush=True)

            annotations = fetch_annotations(client, backend_base_url, image_id)
            if not annotations:
                raise RuntimeError("no annotations were created")

            provider_mismatches: list[dict[str, Any]] = []
            for annotation in annotations:
                inference = annotation.get("inference")
                if not isinstance(inference, dict):
                    provider_mismatches.append(annotation)
                    continue
                if inference.get("provider") != "openai_compatible" or inference.get("fallback_used") is not False:
                    provider_mismatches.append(annotation)

            if provider_mismatches:
                raise RuntimeError(f"expected real openai_compatible annotations, got: {provider_mismatches!r}")

            labels = [str(annotation.get("label")) for annotation in annotations]
            print(f"[verify-real-model] annotations: count={len(annotations)} labels={labels}", flush=True)
        finally:
            if not args.keep_project:
                delete_project(client, backend_base_url, project_id)
                print(f"[verify-real-model] deleted project: {project_id}", flush=True)

    print("[verify-real-model] success", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
