from __future__ import annotations

import json
from typing import Any

from backend.config import DEFAULT_PROJECT_SETTINGS, deep_merge
from backend.models.project import Project


def load_stored_project_settings(project: Project | None) -> dict[str, Any]:
    stored: dict[str, Any] = {}
    if project is not None and project.config:
        try:
            loaded = json.loads(project.config)
            if isinstance(loaded, dict):
                stored = loaded
        except Exception:
            stored = {}
    return stored


def resolve_project_profile_name(project: Project | None, stored: dict[str, Any] | None = None) -> str:
    from backend.services.system_profiles import AVAILABLE_PROFILES, detect_active_profile

    source = stored if stored is not None else load_stored_project_settings(project)
    requested = str(source.get("model_profile") or DEFAULT_PROJECT_SETTINGS["model_profile"]).strip()
    if requested == "auto":
        return detect_active_profile()
    if requested in AVAILABLE_PROFILES:
        return requested
    return detect_active_profile()


def merge_project_settings(stored: dict[str, Any] | None, project: Project | None = None) -> dict[str, Any]:
    from backend.services.system_profiles import read_system_profile

    stored_payload = stored or {}

    resolved = dict(DEFAULT_PROJECT_SETTINGS)
    requested_profile = str(stored_payload.get("model_profile") or DEFAULT_PROJECT_SETTINGS["model_profile"]).strip()
    if requested_profile != "fixed":
        try:
            profile = read_system_profile(resolve_project_profile_name(project, stored=stored_payload))
            profile_defaults = profile.get("project_defaults")
            if isinstance(profile_defaults, dict):
                resolved = deep_merge(resolved, profile_defaults)
        except Exception:
            # Keep defaults if profile files are unavailable; callers still get a valid settings payload.
            resolved = dict(DEFAULT_PROJECT_SETTINGS)

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
