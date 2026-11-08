"""Add merchant payment requests.

Revision ID: 0002_payments
Revises: 0001_identity
Create Date: 2026-11-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_payments"
down_revision: Union[str, None] = "0001_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_requests",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("merchant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reference", sa.String(length=48), nullable=False),
        sa.Column("description", sa.String(length=240), nullable=False),
        sa.Column("amount", sa.Numeric(precision=36, scale=18), nullable=False),
        sa.Column("currency", sa.String(length=12), nullable=False),
        sa.Column("token_address", sa.String(length=42), nullable=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("success_url", sa.String(length=2048), nullable=True),
        sa.Column("cancel_url", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_requests_merchant_id", "payment_requests", ["merchant_id"], unique=False)
    op.create_index("ix_payment_requests_reference", "payment_requests", ["reference"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_payment_requests_reference", table_name="payment_requests")
    op.drop_index("ix_payment_requests_merchant_id", table_name="payment_requests")
    op.drop_table("payment_requests")