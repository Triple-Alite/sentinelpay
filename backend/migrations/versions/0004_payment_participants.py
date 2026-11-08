"""Persist escrow merchant and customer wallet addresses.

Revision ID: 0004_payment_participants
Revises: 0003_chain_lifecycle
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_payment_participants"
down_revision: Union[str, None] = "0003_chain_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payment_requests", sa.Column("merchant_wallet_address", sa.String(length=42), nullable=True))
    op.add_column("payment_requests", sa.Column("customer_wallet_address", sa.String(length=42), nullable=True))


def downgrade() -> None:
    op.drop_column("payment_requests", "customer_wallet_address")
    op.drop_column("payment_requests", "merchant_wallet_address")