from decimal import Decimal
from datetime import datetime
import uuid

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, model_validator


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    business_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    country: str = Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    website: HttpUrl | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    role: str
    email_verified: bool

    model_config = ConfigDict(from_attributes=True)


class MerchantResponse(BaseModel):
    id: uuid.UUID
    business_name: str
    website: str | None
    country: str
    wallet_address: str | None
    status: str

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    user: UserResponse
    merchant: MerchantResponse


class MerchantUpdateRequest(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=160)
    website: HttpUrl | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")

    model_config = ConfigDict(extra="forbid")


class MerchantSettingsUpdateRequest(BaseModel):
    low_risk_threshold: int | None = Field(default=None, ge=10, le=40)
    high_risk_threshold: int | None = Field(default=None, ge=60, le=90)
    manual_review_enabled: bool | None = None
    automatic_settlement_enabled: bool | None = None
    maximum_auto_settlement: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=8)
    escrow_duration: int | None = Field(default=None, ge=3600, le=604800)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def thresholds_are_ordered(self) -> "MerchantSettingsUpdateRequest":
        if (
            self.low_risk_threshold is not None
            and self.high_risk_threshold is not None
            and self.low_risk_threshold >= self.high_risk_threshold
        ):
            raise ValueError("low_risk_threshold must be less than high_risk_threshold")
        return self


class MerchantSettingsResponse(BaseModel):
    low_risk_threshold: int
    high_risk_threshold: int
    manual_review_enabled: bool
    automatic_settlement_enabled: bool
    maximum_auto_settlement: Decimal
    escrow_duration: int

    model_config = ConfigDict(from_attributes=True)


class PaymentCreateRequest(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=36, decimal_places=18)
    currency: Literal["ETH"] = "ETH"
    description: str = Field(min_length=1, max_length=240)
    chain_id: int = Field(gt=0)
    expires_in_minutes: int = Field(default=60, ge=15, le=10080)
    success_url: HttpUrl | None = None
    cancel_url: HttpUrl | None = None

    model_config = ConfigDict(extra="forbid")


class PaymentResponse(BaseModel):
    id: uuid.UUID
    reference: str
    description: str
    amount: Decimal
    currency: str
    token_address: str | None
    chain_id: int
    onchain_payment_id: str | None
    onchain_reference_hash: str | None
    merchant_wallet_address: str | None
    customer_wallet_address: str | None
    onchain_state: str
    status: str
    expires_at: datetime
    created_at: datetime
    checkout_url: str


class CheckoutResponse(BaseModel):
    reference: str
    merchant_name: str
    description: str
    amount: Decimal
    currency: str
    chain_id: int
    onchain_payment_id: str | None
    onchain_reference_hash: str | None
    merchant_wallet_address: str | None
    customer_wallet_address: str | None
    onchain_state: str
    status: str
    expires_at: datetime


class ChainTransactionRequest(BaseModel):
    operation: Literal["CREATE_PAYMENT", "DEPOSIT", "RELEASE", "REFUND"]
    transaction_hash: str = Field(pattern=r"^0x[a-fA-F0-9]{64}$")

    model_config = ConfigDict(extra="forbid")


class ChainTransactionResponse(BaseModel):
    id: uuid.UUID
    payment_request_id: uuid.UUID
    chain_id: int
    operation: str
    transaction_hash: str
    status: str
    block_number: int | None
    block_hash: str | None
    confirmations: int
    failure_reason: str | None
    submitted_at: datetime
    confirmed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ChainEventResponse(BaseModel):
    id: uuid.UUID
    payment_request_id: uuid.UUID
    chain_id: int
    transaction_hash: str
    log_index: int
    block_number: int
    block_hash: str
    event_name: str
    event_data: dict[str, object]
    observed_at: datetime
    processed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class RiskAssessmentRequest(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    wallet_age_days: int = Field(ge=0, le=36500)
    transaction_amount: float = Field(ge=0, le=1_000_000_000)
    transaction_frequency: int = Field(ge=0, le=10000)
    failed_tx_count: int = Field(ge=0, le=10000)
    historical_volume: float = Field(ge=0, le=1_000_000_000)
    time_since_previous_tx_hours: float = Field(ge=0, le=87600)
    new_wallet: bool
    known_malicious_address: bool
    suspicious_contract_interaction: bool
    amount_deviation_ratio: float = Field(ge=0, le=1000)
    wallet_reputation_score: int = Field(ge=0, le=100)
    payment_velocity: int = Field(ge=0, le=1000)
    merchant_anomaly_score: int = Field(ge=0, le=100)

    model_config = ConfigDict(extra="forbid")


class RiskAssessmentExplanation(BaseModel):
    factor: str
    impact: int
    observation: str


class RiskAssessmentResponse(BaseModel):
    transaction_id: str
    risk_score: int
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    decision: Literal["ALLOW", "REVIEW", "BLOCK"]
    model_version: str
    explanations: list[RiskAssessmentExplanation]
    created_at: datetime