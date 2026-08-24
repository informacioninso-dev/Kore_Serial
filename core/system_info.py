"""Runtime release metadata shown by Kore and used as audit evidence."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from django.conf import settings


@dataclass(frozen=True)
class SystemReleaseInfo:
    version: str
    release_id: str
    commit: str
    deployed_at: datetime | None
    environment: str
    tag: str
    generated_by_deploy: bool

    @property
    def display_version(self) -> str:
        return self.version if self.version.startswith("v") else f"v{self.version}"

    @property
    def short_commit(self) -> str:
        return self.commit[:7] if self.commit and self.commit != "PENDIENTE" else "PENDIENTE"


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as source:
            return tomllib.load(source)
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return {}


def _read_runtime_info(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@lru_cache(maxsize=1)
def get_system_release_info() -> SystemReleaseInfo:
    base_dir = Path(settings.BASE_DIR)
    project = _read_toml(base_dir / "pyproject.toml").get("project", {})
    planned = _read_toml(base_dir / "release.toml").get("release", {})
    runtime_path = Path(settings.KORE_RELEASE_INFO_FILE)
    runtime = _read_runtime_info(runtime_path)

    return SystemReleaseInfo(
        version=str(runtime.get("version") or project.get("version") or "0.0.0"),
        release_id=str(runtime.get("release_id") or planned.get("id") or "PENDIENTE"),
        commit=str(runtime.get("commit") or "PENDIENTE"),
        deployed_at=_parse_datetime(runtime.get("deployed_at")),
        environment=str(runtime.get("environment") or settings.KORE_ENVIRONMENT),
        tag=str(runtime.get("tag") or ""),
        generated_by_deploy=bool(runtime),
    )
