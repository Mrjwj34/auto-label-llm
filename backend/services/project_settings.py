from __future__ import annotations

import json
from typing import Any

from backend.config import DEFAULT_PROJECT_SETTINGS, deep_merge
from backend.models.project import Project


def load_project_settings(project: Project | None) -> dict[str, Any]:
    stored: dict[str, Any] = {}
    if project is not None and project.config:
        try:
            loaded = json.loads(project.config)
            if isinstance(loaded, dict):
                stored = loaded
        except Exception:
            stored = {}

    return deep_merge(DEFAULT_PROJECT_SETTINGS, stored)


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

