import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db_base import Base
from app.db_types import ExactNumeric


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="merchant")
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    merchant: Mapped["Merchant"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    business_name: Mapped[str] = mapped_column(String(160), nullable=False)
    website: Mapped[str | None] = mapped_column(String(2048))
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    wallet_address: Mapped[str | None] = mapped_column(String(42))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="merchant")
    settings: Mapped["MerchantSettings"] = relationship(
        back_populates="merchant", cascade="all, delete-orphan", uselist=False
    )
    payment_requests: Mapped[list["PaymentRequest"]] = relationship(back_populates="merchant")


class MerchantSettings(Base):
    __tablename__ = "merchant_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    low_risk_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    high_risk_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=70)
    manual_review_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    automatic_settlement_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    maximum_auto_settlement: Mapped[Decimal] = mapped_column(ExactNumeric(20, 8), nullable=False, default=Decimal("0"))
    escrow_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=86400)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    merchant: Mapped[Merchant] = relationship(back_populates="settings")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    refresh_jti_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")


class PaymentRequest(Base):
    __tablename__ = "payment_requests"
    __table_args__ = (
        UniqueConstraint("onchain_payment_id", name="uq_payment_requests_onchain_payment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reference: Mapped[str] = mapped_column(String(48), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    amount: Mapped[Decimal] = mapped_column(ExactNumeric(36, 18), nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="ETH")
    token_address: Mapped[str | None] = mapped_column(String(42))
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    onchain_payment_id: Mapped[str | None] = mapped_column(String(66))
    onchain_reference_hash: Mapped[str | None] = mapped_column(String(66))
    merchant_wallet_address: Mapped[str | None] = mapped_column(String(42))
    customer_wallet_address: Mapped[str | None] = mapped_column(String(42))
    onchain_state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="NOT_CREATED", server_default="NOT_CREATED"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    success_url: Mapped[str | None] = mapped_column(String(2048))
    cancel_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    merchant: Mapped[Merchant] = relationship(back_populates="payment_requests")
    chain_transactions: Mapped[list["PaymentChainTransaction"]] = relationship(
        back_populates="payment_request", cascade="all, delete-orphan"
    )
    chain_events: Mapped[list["PaymentChainEvent"]] = relationship(
        back_populates="payment_request", cascade="all, delete-orphan"
    )


class PaymentChainTransaction(Base):
    __tablename__ = "payment_chain_transactions"
    __table_args__ = (UniqueConstraint("chain_id", "transaction_hash", name="uq_chain_transaction_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("payment_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(24), nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING")
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    block_hash: Mapped[str | None] = mapped_column(String(66))
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(String(512))
    submitted_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    confirmed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    payment_request: Mapped[PaymentRequest] = relationship(back_populates="chain_transactions")


class PaymentChainEvent(Base):
    __tablename__ = "payment_chain_events"
    __table_args__ = (
        UniqueConstraint("chain_id", "transaction_hash", "log_index", name="uq_chain_event_log"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("payment_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    event_name: Mapped[str] = mapped_column(String(64), nullable=False)
    event_data: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    payment_request: Mapped[PaymentRequest] = relationship(back_populates="chain_events")