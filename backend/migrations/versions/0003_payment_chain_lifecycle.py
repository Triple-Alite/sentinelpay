"""Persist escrow identifiers, transaction submissions, and contract events.

Revision ID: 0003_chain_lifecycle
Revises: 0002_payments
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_chain_lifecycle"
down_revision: Union[str, None] = "0002_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payment_requests", sa.Column("onchain_payment_id", sa.String(length=66), nullable=True))
    op.add_column("payment_requests", sa.Column("onchain_reference_hash", sa.String(length=66), nullable=True))
    op.add_column(
        "payment_requests",
        sa.Column("onchain_state", sa.String(length=24), server_default="NOT_CREATED", nullable=False),
    )
    op.create_unique_constraint(
        "uq_payment_requests_onchain_payment_id", "payment_requests", ["onchain_payment_id"]
    )

    op.create_table(
        "payment_chain_transactions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("payment_request_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=24), nullable=False),
        sa.Column("transaction_hash", sa.String(length=66), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="PENDING", nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("block_hash", sa.String(length=66), nullable=True),
        sa.Column("confirmations", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_reason", sa.String(length=512), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payment_request_id"], ["payment_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chain_id", "transaction_hash", name="uq_chain_transaction_hash"),
    )
    op.create_index(
        "ix_payment_chain_transactions_payment_request_id",
        "payment_chain_transactions",
        ["payment_request_id"],
    )

    op.create_table(
        "payment_chain_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("payment_request_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("transaction_hash", sa.String(length=66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_hash", sa.String(length=66), nullable=False),
        sa.Column("event_name", sa.String(length=64), nullable=False),
        sa.Column("event_data", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["payment_request_id"], ["payment_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chain_id", "transaction_hash", "log_index", name="uq_chain_event_log"),
    )
    op.create_index(
        "ix_payment_chain_events_payment_request_id",
        "payment_chain_events",
        ["payment_request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_chain_events_payment_request_id", table_name="payment_chain_events")
    op.drop_table("payment_chain_events")
    op.drop_index("ix_payment_chain_transactions_payment_request_id", table_name="payment_chain_transactions")
    op.drop_table("payment_chain_transactions")
    op.drop_constraint("uq_payment_requests_onchain_payment_id", "payment_requests", type_="unique")
    op.drop_column("payment_requests", "onchain_state")
    op.drop_column("payment_requests", "onchain_reference_hash")
    op.drop_column("payment_requests", "onchain_payment_id")