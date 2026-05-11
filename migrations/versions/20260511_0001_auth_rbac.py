"""add authentication and rbac tables

Revision ID: 20260511_0001
Revises:
Create Date: 2026-05-11 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260511_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("password_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("auth_source", sa.String(length=40), nullable=False, server_default="local"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=False)

    op.create_table(
        "auth_providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("secret_config_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_auth_providers_provider_type"), "auth_providers", ["provider_type"], unique=False)

    op.create_table(
        "external_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=240), nullable=False),
        sa.Column("username", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("email", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("claims_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["auth_providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_external_identities_provider_id"), "external_identities", ["provider_id"], unique=False)
    op.create_index(op.f("ix_external_identities_subject"), "external_identities", ["subject"], unique=False)
    op.create_index(op.f("ix_external_identities_user_id"), "external_identities", ["user_id"], unique=False)

    op.create_table(
        "role_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("external_group", sa.String(length=240), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["auth_providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_role_mappings_provider_id"), "role_mappings", ["provider_id"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("target", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_role_mappings_provider_id"), table_name="role_mappings")
    op.drop_table("role_mappings")
    op.drop_index(op.f("ix_external_identities_user_id"), table_name="external_identities")
    op.drop_index(op.f("ix_external_identities_subject"), table_name="external_identities")
    op.drop_index(op.f("ix_external_identities_provider_id"), table_name="external_identities")
    op.drop_table("external_identities")
    op.drop_index(op.f("ix_auth_providers_provider_type"), table_name="auth_providers")
    op.drop_table("auth_providers")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
