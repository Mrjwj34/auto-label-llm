from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_use_profile_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "use_profile.py"
    spec = importlib.util.spec_from_file_location("scripts_use_profile", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_apply_profile_writes_backend_and_frontend_env_files(tmp_path):
    module = _load_use_profile_module()
    profile_dir = tmp_path / "configs" / "profiles"
    frontend_dir = tmp_path / "frontend"
    profile_dir.mkdir(parents=True, exist_ok=True)
    frontend_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "test_real_stack.json").write_text(
        json.dumps(
            {
                "backend": {"APP_PROFILE": "test_real_stack", "ANNOTATION_BACKEND": "openai_compatible"},
                "frontend": {"VITE_APP_PROFILE": "test_real_stack", "VITE_API_BASE_URL": "http://127.0.0.1:8000"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    backend_env_path, frontend_env_path = module.apply_profile(tmp_path, "test_real_stack")

    assert backend_env_path.read_text(encoding="utf-8") == (
        "# Generated from profile: test_real_stack\n"
        "APP_PROFILE=test_real_stack\n"
        "ANNOTATION_BACKEND=openai_compatible\n"
    )
    assert frontend_env_path.read_text(encoding="utf-8") == (
        "# Generated from profile: test_real_stack\n"
        "VITE_APP_PROFILE=test_real_stack\n"
        "VITE_API_BASE_URL=http://127.0.0.1:8000\n"
    )


def test_apply_profile_rejects_missing_sections(tmp_path):
    module = _load_use_profile_module()
    profile_dir = tmp_path / "configs" / "profiles"
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "broken.json").write_text(json.dumps({"backend": {"APP_PROFILE": "broken"}}), encoding="utf-8")

    try:
        module.apply_profile(tmp_path, "broken")
        assert False, "expected a ValueError when frontend section is missing"
    except ValueError as exc:
        assert "backend/frontend" in str(exc)
