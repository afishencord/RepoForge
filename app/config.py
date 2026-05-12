"""Application configuration for RepoForge."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys


def _project_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = _project_root()
DEFAULT_STORAGE_ROOT = "/var/lib/repoforge"


def _path_from_env(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _optional_path_from_env(name: str) -> Path | None:
    value = os.getenv(name)
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _tls_files_exist() -> bool:
    cert_file = _optional_path_from_env("REPOFORGE_TLS_CERT_FILE")
    key_file = _optional_path_from_env("REPOFORGE_TLS_KEY_FILE")
    return bool(cert_file and key_file and cert_file.is_file() and key_file.is_file())


def _tls_expected() -> bool:
    return _tls_files_exist() or _bool_from_env("REPOFORGE_TLS_AUTO_GENERATE", False)


@dataclass(frozen=True)
class Settings:
    app_name: str = "RepoForge"
    database_url: str = os.getenv("REPOFORGE_DATABASE_URL", f"sqlite:///{DEFAULT_STORAGE_ROOT}/repoforge.db")
    secret_key: str = os.getenv("REPOFORGE_SECRET_KEY", "repoforge-dev-secret-change-me")
    auth_secret_key: str = os.getenv("REPOFORGE_AUTH_SECRET_KEY", os.getenv("REPOFORGE_SECRET_KEY", "repoforge-dev-secret-change-me"))
    storage_root: Path = _path_from_env("REPOFORGE_STORAGE_ROOT", DEFAULT_STORAGE_ROOT)
    upload_root: Path = _path_from_env("REPOFORGE_UPLOAD_ROOT", f"{DEFAULT_STORAGE_ROOT}/uploads")
    workspace_root: Path = _path_from_env("REPOFORGE_WORKSPACE_ROOT", f"{DEFAULT_STORAGE_ROOT}/workspaces")
    artifact_root: Path = _path_from_env("REPOFORGE_ARTIFACT_ROOT", f"{DEFAULT_STORAGE_ROOT}/artifacts")
    key_root: Path = _path_from_env("REPOFORGE_KEY_ROOT", f"{DEFAULT_STORAGE_ROOT}/keys")
    auto_migrate: bool = _bool_from_env("REPOFORGE_AUTO_MIGRATE", True)
    max_upload_bytes: int = int(os.getenv("REPOFORGE_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
    require_system_tools_for_build: bool = os.getenv("REPOFORGE_REQUIRE_TOOLS", "1") not in {"0", "false", "False"}
    server_host: str = os.getenv("REPOFORGE_HOST", "0.0.0.0")
    http_port: int = int(os.getenv("REPOFORGE_HTTP_PORT", "80"))
    https_port: int = int(os.getenv("REPOFORGE_HTTPS_PORT", "443"))
    enable_http: bool = _bool_from_env("REPOFORGE_ENABLE_HTTP", True)
    tls_cert_file: Path | None = _optional_path_from_env("REPOFORGE_TLS_CERT_FILE")
    tls_key_file: Path | None = _optional_path_from_env("REPOFORGE_TLS_KEY_FILE")
    tls_auto_generate: bool = _bool_from_env("REPOFORGE_TLS_AUTO_GENERATE", False)
    tls_subject_alt_names: str = os.getenv("REPOFORGE_TLS_SUBJECT_ALT_NAMES", "localhost,127.0.0.1")
    session_https_only: bool = _bool_from_env("REPOFORGE_SESSION_HTTPS_ONLY", _tls_expected())

    def ensure_directories(self) -> None:
        for path in (self.storage_root, self.upload_root, self.workspace_root, self.artifact_root, self.key_root):
            path.mkdir(parents=True, exist_ok=True)

    def tls_files_available(self) -> bool:
        return bool(self.tls_cert_file and self.tls_key_file and self.tls_cert_file.is_file() and self.tls_key_file.is_file())


settings = Settings()
