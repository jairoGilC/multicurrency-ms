from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from src.enums import (
    Currency,
    FeeType,
    PaymentMethod,
    RefundPolicy,
    RefundStatus,
    RiskLevel,
    TransactionStatus,
    TransactionType,
)


def _new_id() -> str:
    return str(uuid4())


class ExchangeRate(BaseModel):
    source_currency: Currency
    target_currency: Currency
    rate: Decimal
    timestamp: datetime

    @field_validator("rate")
    @classmethod
    def rate_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Exchange rate must be positive")
        return v


class Transaction(BaseModel):
    id: str = Field(default_factory=_new_id)
    customer_id: str
    amount: Decimal
    currency: Currency
    supplier_currency: Currency
    supplier_amount: Decimal
    exchange_rate_used: Decimal
    transaction_type: TransactionType
    payment_method: PaymentMethod
    timestamp: datetime
    status: TransactionStatus = TransactionStatus.SUCCESS
    total_refunded: Decimal = Decimal("0")

    @field_validator("amount", "supplier_amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

    @property
    def refundable_amount(self) -> Decimal:
        return self.amount - self.total_refunded


class Fee(BaseModel):
    type: FeeType
    value: Decimal
    currency: Currency | None = None
    description: str = ""

    @field_validator("value")
    @classmethod
    def value_must_be_non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("Fee value must be non-negative")
        return v


class RefundRequest(BaseModel):
    id: str = Field(default_factory=_new_id)
    transaction_id: str
    requested_amount: Decimal | None = None
    destination_currency: Currency | None = None
    policy: RefundPolicy = RefundPolicy.ORIGINAL_RATE
    fees: list[Fee] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("requested_amount")
    @classmethod
    def amount_must_be_positive_if_set(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("Requested amount must be positive")
        return v


class AuditEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    action: str
    details: str
    data: dict = Field(default_factory=dict)


class RiskFlag(BaseModel):
    level: RiskLevel
    reason: str
    details: dict = Field(default_factory=dict)


class AppliedFee(BaseModel):
    description: str
    type: FeeType
    original_value: Decimal
    deducted_amount: Decimal
    currency: Currency


class RefundResult(BaseModel):
    id: str = Field(default_factory=_new_id)
    request_id: str
    transaction_id: str
    original_amount: Decimal
    original_currency: Currency
    refund_amount_before_fees: Decimal
    fees_applied: list[AppliedFee] = Field(default_factory=list)
    total_fees: Decimal = Decimal("0")
    refund_amount_after_fees: Decimal = Decimal("0")
    destination_currency: Currency
    destination_amount: Decimal = Decimal("0")
    original_rate: Decimal
    current_rate: Decimal
    rate_used: Decimal
    policy_applied: RefundPolicy
    status: RefundStatus = RefundStatus.CALCULATED
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    audit_entries: list[AuditEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rejection_reason: str | None = None


class ValidationError(BaseModel):
    code: str
    message: str


class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[ValidationError] = Field(default_factory=list)


class BatchResult(BaseModel):
    total_processed: int = 0
    total_approved: int = 0
    total_flagged: int = 0
    total_rejected: int = 0
    by_currency: dict[str, Decimal] = Field(default_factory=dict)
    results: list[RefundResult] = Field(default_factory=list)


class RiskConfig(BaseModel):
    exchange_rate_drift_threshold: Decimal = Decimal("0.10")
    large_refund_threshold_usd: Decimal = Decimal("2000")
    max_refunds_per_transaction: int = 3
    old_transaction_days: int = 30
