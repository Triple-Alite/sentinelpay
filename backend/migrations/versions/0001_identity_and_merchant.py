"""Create merchant identity, settings, and refresh sessions.

Revision ID: 0001_identity
Revises:
Create Date: 2026-11-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_identity"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "merchants",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("business_name", sa.String(length=160), nullable=False),
        sa.Column("website", sa.String(length=2048), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("wallet_address", sa.String(length=42), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "merchant_settings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("merchant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("low_risk_threshold", sa.Integer(), nullable=False),
        sa.Column("high_risk_threshold", sa.Integer(), nullable=False),
        sa.Column("manual_review_enabled", sa.Boolean(), nullable=False),
        sa.Column("automatic_settlement_enabled", sa.Boolean(), nullable=False),
        sa.Column("maximum_auto_settlement", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("escrow_duration", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("refresh_jti_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_jti_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("merchant_settings")
    op.drop_table("merchants")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")