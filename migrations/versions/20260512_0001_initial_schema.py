"""create core repoforge schema

Revision ID: 20260512_0001
Revises:
Create Date: 2026-05-12 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260512_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bundles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_os", sa.String(length=64), nullable=False, server_default="rhel"),
        sa.Column("target_os_version", sa.String(length=64), nullable=False, server_default="9"),
        sa.Column("architecture", sa.String(length=32), nullable=False, server_default="x86_64"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("signing_mode", sa.String(length=64), nullable=False, server_default="metadata"),
        sa.Column("package_include", sa.Text(), nullable=False, server_default=""),
        sa.Column("package_exclude", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolve_dependencies", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("resolve_custom_rpm_dependencies", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fail_on_unresolved_dependencies", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("iso_label", sa.String(length=32), nullable=False, server_default="REPOFORGE"),
        sa.Column("artifact_prefix", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("include_validation_scripts", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("include_install_scripts", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("builder_mode", sa.String(length=40), nullable=False, server_default="container"),
        sa.Column("last_built_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("iso_artifact_path", sa.Text(), nullable=True),
        sa.Column("manifest_path", sa.Text(), nullable=True),
        sa.Column("checksum_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bundles_name"), "bundles", ["name"], unique=False)

    op.create_table(
        "repo_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="generic_yum"),
        sa.Column("base_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("mirrorlist", sa.Text(), nullable=False, server_default=""),
        sa.Column("repo_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("gpgcheck", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("repo_gpgcheck", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gpg_key_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("requires_auth", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("username", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("password_secret_ref", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("subscription_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sync_policy", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("verify_ssl", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="not_checked"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_repo_sources_name"), "repo_sources", ["name"], unique=False)

    op.create_table(
        "gpg_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=240), nullable=False),
        sa.Column("fingerprint", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("public_key_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("private_key_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("associated_repo", sa.String(length=160), nullable=False, server_default="repoforge-custom"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "bundle_repo_sources",
        sa.Column("bundle_id", sa.Integer(), nullable=False),
        sa.Column("repo_source_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_source_id"], ["repo_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("bundle_id", "repo_source_id"),
    )

    op.create_table(
        "package_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bundle_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("version_constraint", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("architecture", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("source_preference", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("include_dependencies", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="requested"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_package_requests_bundle_id"), "package_requests", ["bundle_id"], unique=False)

    op.create_table(
        "uploaded_rpms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bundle_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=240), nullable=False),
        sa.Column("original_filename", sa.String(length=240), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("version", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("release", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("architecture", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolve_dependencies", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dependency_status", sa.String(length=32), nullable=False, server_default="not_checked"),
        sa.Column("requires_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("provides_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("unresolved_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_uploaded_rpms_bundle_id"), "uploaded_rpms", ["bundle_id"], unique=False)

    op.create_table(
        "build_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bundle_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("name", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("stage", sa.String(length=80), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("log_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="local"),
        sa.Column("builder_mode", sa.String(length=40), nullable=False, server_default="container"),
        sa.Column("worker", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("warnings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_build_jobs_bundle_id"), "build_jobs", ["bundle_id"], unique=False)

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bundle_id", sa.Integer(), nullable=False),
        sa.Column("build_job_id", sa.Integer(), nullable=True),
        sa.Column("artifact_type", sa.String(length=32), nullable=False, server_default="iso"),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["build_job_id"], ["build_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artifacts_bundle_id"), "artifacts", ["bundle_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_artifacts_bundle_id"), table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index(op.f("ix_build_jobs_bundle_id"), table_name="build_jobs")
    op.drop_table("build_jobs")
    op.drop_index(op.f("ix_uploaded_rpms_bundle_id"), table_name="uploaded_rpms")
    op.drop_table("uploaded_rpms")
    op.drop_index(op.f("ix_package_requests_bundle_id"), table_name="package_requests")
    op.drop_table("package_requests")
    op.drop_table("bundle_repo_sources")
    op.drop_table("settings")
    op.drop_table("gpg_keys")
    op.drop_index(op.f("ix_repo_sources_name"), table_name="repo_sources")
    op.drop_table("repo_sources")
    op.drop_index(op.f("ix_bundles_name"), table_name="bundles")
    op.drop_table("bundles")
