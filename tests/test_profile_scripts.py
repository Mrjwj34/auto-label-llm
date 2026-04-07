from __future__ import annotations

import json

from backend.services.system_profiles import activate_system_profile

def test_activate_system_profile_writes_backend_and_frontend_env_files(tmp_path):
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

    result = activate_system_profile("test_real_stack", root_dir=tmp_path)
    backend_env_path = tmp_path / ".env.active"
    frontend_env_path = tmp_path / "frontend" / ".env.local"

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
    assert result["active_profile"] == "test_real_stack"


def test_activate_system_profile_rejects_missing_sections(tmp_path):
    profile_dir = tmp_path / "configs" / "profiles"
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "dev_low_resource.json").write_text(
        json.dumps({"backend": {"APP_PROFILE": "dev_low_resource"}}),
        encoding="utf-8",
    )

    try:
        activate_system_profile("dev_low_resource", root_dir=tmp_path)
        assert False, "expected a ValueError when frontend section is missing"
    except Exception as exc:  # noqa: BLE001
        assert "profile sections missing" in str(exc)
