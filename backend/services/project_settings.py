from __future__ import annotations

import json
from typing import Any

from backend.config import DEFAULT_PROJECT_SETTINGS, deep_merge
from backend.models.project import Project

PROJECT_SETTINGS_KEYS = ("labels", "active_model_tag")


def load_stored_project_settings(project: Project | None) -> dict[str, Any]:
    stored: dict[str, Any] = {}
    if project is not None and project.config:
        try:
            loaded = json.loads(project.config)
            if isinstance(loaded, dict):
                stored = {key: loaded[key] for key in PROJECT_SETTINGS_KEYS if key in loaded}
        except Exception:
            stored = {}
    return stored


def resolve_project_profile_name(project: Project | None, stored: dict[str, Any] | None = None) -> str:
    from backend.services.system_runtime_settings import resolve_system_runtime_profile_name

    return resolve_system_runtime_profile_name()


def merge_project_settings(stored: dict[str, Any] | None, project: Project | None = None) -> dict[str, Any]:
    from backend.services.system_runtime_settings import load_system_runtime_settings

    stored_payload = stored or {}

    resolved = dict(DEFAULT_PROJECT_SETTINGS)
    resolved = deep_merge(resolved, load_system_runtime_settings())

    return deep_merge(resolved, stored_payload)


def load_project_settings(project: Project | None) -> dict[str, Any]:
    stored = load_stored_project_settings(project)
    return merge_project_settings(stored, project=project)


def get_project_labels(project: Project | None) -> list[str]:
    settings = load_project_settings(project)
    raw_labels = settings.get("labels")
    if not isinstance(raw_labels, list):
        return []

    labels: list[str] = []
    seen: set[str] = set()
    for item in raw_labels:
        if not isinstance(item, str):
            continue
        label = item.strip()
        if not label or label in seen:
            continue
        labels.append(label)
        seen.add(label)

    return labels
