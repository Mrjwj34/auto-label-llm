from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _write_env_file(path: Path, values: dict[str, Any], *, header: str) -> None:
    lines: list[str] = []
    if header:
        lines.append(f"# {header}")
    for key, value in values.items():
        lines.append(f"{key}={value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_profile(profile_path: Path) -> dict[str, Any]:
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid profile payload: {profile_path}")
    return payload


def list_profiles(repo_root: Path) -> list[str]:
    profile_dir = repo_root / "configs" / "profiles"
    if not profile_dir.exists():
        return []
    return sorted(path.stem for path in profile_dir.glob("*.json"))


def apply_profile(repo_root: Path, profile_name: str) -> tuple[Path, Path]:
    profile_path = repo_root / "configs" / "profiles" / f"{profile_name}.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile definition not found: {profile_path}")

    profile = _load_profile(profile_path)
    backend_values = profile.get("backend")
    frontend_values = profile.get("frontend")
    if not isinstance(backend_values, dict) or not isinstance(frontend_values, dict):
        raise ValueError("Invalid profile payload: missing backend/frontend sections.")

    backend_env_path = repo_root / ".env.active"
    frontend_env_path = repo_root / "frontend" / ".env.local"
    header = f"Generated from profile: {profile_name}"
    _write_env_file(backend_env_path, backend_values, header=header)
    _write_env_file(frontend_env_path, frontend_values, header=header)
    return backend_env_path, frontend_env_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply backend/frontend env files from a named profile.")
    parser.add_argument("--profile", help="Profile name from configs/profiles/*.json")
    parser.add_argument("--repo-root", help="Repository root. Defaults to the parent of this script.")
    parser.add_argument("--list", action="store_true", help="List available profile names and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]

    if args.list:
        for profile_name in list_profiles(repo_root):
            print(profile_name)
        return 0

    if not args.profile:
        parser.error("--profile is required unless --list is used.")

    backend_env_path, frontend_env_path = apply_profile(repo_root, args.profile)
    print(f"Activated profile: {args.profile}")
    print(f"Backend env : {backend_env_path}")
    print(f"Frontend env: {frontend_env_path}")
    print("Restart frontend if Vite env values changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
