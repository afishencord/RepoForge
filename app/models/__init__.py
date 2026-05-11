"""Database models for RepoForge."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


bundle_repo_sources = Table(
    "bundle_repo_sources",
    Base.metadata,
    Column("bundle_id", ForeignKey("bundles.id", ondelete="CASCADE"), primary_key=True),
    Column("repo_source_id", ForeignKey("repo_sources.id", ondelete="CASCADE"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class Bundle(TimestampMixin, Base):
    __tablename__ = "bundles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    target_os: Mapped[str] = mapped_column(String(64), default="rhel", nullable=False)
    target_os_version: Mapped[str] = mapped_column(String(64), default="9", nullable=False)
    architecture: Mapped[str] = mapped_column(String(32), default="x86_64", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    signing_mode: Mapped[str] = mapped_column(String(64), default="metadata", nullable=False)
    package_include: Mapped[str] = mapped_column(Text, default="", nullable=False)
    package_exclude: Mapped[str] = mapped_column(Text, default="", nullable=False)
    resolve_dependencies: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    resolve_custom_rpm_dependencies: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fail_on_unresolved_dependencies: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    iso_label: Mapped[str] = mapped_column(String(32), default="REPOFORGE", nullable=False)
    artifact_prefix: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    include_validation_scripts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_install_scripts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    builder_mode: Mapped[str] = mapped_column(String(40), default="container", nullable=False)
    last_built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    iso_artifact_path: Mapped[str | None] = mapped_column(Text)
    manifest_path: Mapped[str | None] = mapped_column(Text)
    checksum_path: Mapped[str | None] = mapped_column(Text)

    repo_sources: Mapped[list["RepoSource"]] = relationship(
        secondary=bundle_repo_sources,
        back_populates="bundles",
        lazy="selectin",
    )
    uploaded_rpms: Mapped[list["UploadedRPM"]] = relationship(back_populates="bundle", cascade="all, delete-orphan", lazy="selectin")
    build_jobs: Mapped[list["BuildJob"]] = relationship(back_populates="bundle", cascade="all, delete-orphan", lazy="selectin")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="bundle", cascade="all, delete-orphan", lazy="selectin")

    @property
    def repo_source_count(self) -> int:
        return len(self.repo_sources or [])

    @property
    def last_build_at(self) -> str | None:
        return format_datetime(self.last_built_at)

    @property
    def package_names(self) -> list[str]:
        return parse_lines(self.package_include)


class RepoSource(TimestampMixin, Base):
    __tablename__ = "repo_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="generic_yum", nullable=False)
    base_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mirrorlist: Mapped[str] = mapped_column(Text, default="", nullable=False)
    repo_id: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    gpgcheck: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    repo_gpgcheck: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gpg_key_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    requires_auth: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    username: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    password_secret_ref: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    subscription_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sync_policy: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="not_checked", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    bundles: Mapped[list[Bundle]] = relationship(secondary=bundle_repo_sources, back_populates="repo_sources")


class PackageRequest(TimestampMixin, Base):
    __tablename__ = "package_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    version_constraint: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    architecture: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    source_preference: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    include_dependencies: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="requested", nullable=False)


class UploadedRPM(Base):
    __tablename__ = "uploaded_rpms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(240), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    version: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    release: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    architecture: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resolve_dependencies: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dependency_status: Mapped[str] = mapped_column(String(32), default="not_checked", nullable=False)
    requires_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    provides_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    unresolved_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    bundle: Mapped[Bundle] = relationship(back_populates="uploaded_rpms")

    @property
    def size(self) -> str:
        return human_bytes(self.size_bytes)

    @property
    def requires(self) -> list[str]:
        return json_list(self.requires_json)

    @property
    def provides(self) -> list[str]:
        return json_list(self.provides_json)


class GPGKey(Base):
    __tablename__ = "gpg_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(240), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    public_key_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    private_key_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    associated_repo: Mapped[str] = mapped_column(String(160), default="repoforge-custom", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    @property
    def scope(self) -> str:
        return self.associated_repo


class BuildJob(Base):
    __tablename__ = "build_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    stage: Mapped[str] = mapped_column(String(80), default="queued", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    log_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), default="local", nullable=False)
    builder_mode: Mapped[str] = mapped_column(String(40), default="container", nullable=False)
    worker: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    bundle: Mapped[Bundle] = relationship(back_populates="build_jobs")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="build_job", cascade="all, delete-orphan", lazy="selectin")

    @property
    def bundle_name(self) -> str:
        return self.bundle.name if self.bundle else "-"

    @property
    def artifact_id(self) -> int | None:
        return self.artifacts[0].id if self.artifacts else None

    @property
    def duration(self) -> str:
        if not self.started_at:
            return "-"
        end = self.finished_at or utc_now()
        seconds = max(0, int((end - self.started_at).total_seconds()))
        return f"{seconds}s"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(240), default="", nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, default="", nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    auth_source: Mapped[str] = mapped_column(String(40), default="local", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    identities: Mapped[list["ExternalIdentity"]] = relationship(back_populates="user", cascade="all, delete-orphan", lazy="selectin")

    @property
    def name(self) -> str:
        return self.display_name or self.username


class AuthProvider(TimestampMixin, Base):
    __tablename__ = "auth_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    secret_config_json: Mapped[str] = mapped_column(Text, default="", nullable=False)

    identities: Mapped[list["ExternalIdentity"]] = relationship(back_populates="provider", cascade="all, delete-orphan", lazy="selectin")
    role_mappings: Mapped[list["RoleMapping"]] = relationship(back_populates="provider", cascade="all, delete-orphan", lazy="selectin")

    @property
    def config(self) -> dict[str, Any]:
        return json_dict(self.config_json)


class ExternalIdentity(TimestampMixin, Base):
    __tablename__ = "external_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("auth_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    claims_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    user: Mapped[User] = relationship(back_populates="identities")
    provider: Mapped[AuthProvider] = relationship(back_populates="identities")


class RoleMapping(TimestampMixin, Base):
    __tablename__ = "role_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("auth_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    external_group: Mapped[str] = mapped_column(String(240), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)

    provider: Mapped[AuthProvider] = relationship(back_populates="role_mappings")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id", ondelete="CASCADE"), nullable=False, index=True)
    build_job_id: Mapped[int | None] = mapped_column(ForeignKey("build_jobs.id", ondelete="SET NULL"))
    artifact_type: Mapped[str] = mapped_column(String(32), default="iso", nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    bundle: Mapped[Bundle] = relationship(back_populates="artifacts")
    build_job: Mapped[BuildJob | None] = relationship(back_populates="artifacts")

    @property
    def bundle_name(self) -> str:
        return self.bundle.name if self.bundle else "-"

    @property
    def type(self) -> str:
        return self.artifact_type

    @property
    def size(self) -> str:
        return human_bytes(self.size_bytes)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)


def parse_lines(value: str | None) -> list[str]:
    if not value:
        return []
    return [line.strip() for line in value.splitlines() if line.strip() and not line.strip().startswith("#")]


def json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def format_datetime(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.strftime("%Y-%m-%d %H:%M")


def human_bytes(value: int | None) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024


def path_name(path: str) -> str:
    return Path(path).name
