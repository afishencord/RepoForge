"""Application configuration for RepoForge."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _path_from_env(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


@dataclass(frozen=True)
class Settings:
    app_name: str = "RepoForge"
    database_url: str = os.getenv("REPOFORGE_DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'storage' / 'repoforge.db'}")
    storage_root: Path = _path_from_env("REPOFORGE_STORAGE_ROOT", "storage")
    upload_root: Path = _path_from_env("REPOFORGE_UPLOAD_ROOT", "storage/uploads")
    workspace_root: Path = _path_from_env("REPOFORGE_WORKSPACE_ROOT", "storage/workspaces")
    artifact_root: Path = _path_from_env("REPOFORGE_ARTIFACT_ROOT", "storage/artifacts")
    key_root: Path = _path_from_env("REPOFORGE_KEY_ROOT", "storage/keys")
    max_upload_bytes: int = int(os.getenv("REPOFORGE_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
    require_system_tools_for_build: bool = os.getenv("REPOFORGE_REQUIRE_TOOLS", "1") not in {"0", "false", "False"}

    def ensure_directories(self) -> None:
        for path in (self.storage_root, self.upload_root, self.workspace_root, self.artifact_root, self.key_root):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()

