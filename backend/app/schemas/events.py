"""Validated HTTP/event contracts and domain event envelopes for RecoverX."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class PaymentFailedEvent(BaseModel):
    """Upstream payload accepted by the payment failure ingestion API."""

    event_id: UUID = Field(default_factory=uuid4)
    correlation_id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    external_transaction_id: str = Field(min_length=1, max_length=128)
    merchant_id: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    attempt_number: int = Field(ge=1)
    payment_method: str = Field(min_length=1, max_length=32)
    gateway: str | None = Field(default=None, max_length=64)
    failure_code: str = Field(min_length=1, max_length=64)

    @field_validator("currency", "failure_code")
    @classmethod
    def uppercase_codes(cls, value: str) -> str:
        return value.upper()


class DomainEventEnvelope(BaseModel):
    """Standardized event envelope adhering to RecoverX event-flow specification."""

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=1, max_length=96)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_type: str = Field(min_length=1, max_length=64)
    aggregate_id: str = Field(min_length=1, max_length=64)
    correlation_id: UUID = Field(default_factory=uuid4)
    causation_id: UUID | None = None
    schema_version: int = Field(default=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class PaymentFailedPayload(BaseModel):
    """Payload contained inside payment.failed.v1 domain events."""

    event_id: str
    correlation_id: str
    transaction_id: str
    external_transaction_id: str | None = None
    merchant_id: str | None = None
    amount: float | None = None
    currency: str = "INR"
    attempt_number: int = 1
    payment_method: str | None = None
    gateway: str | None = None
    failure_event_id: str
    failure_code: str
    category: str
    recoverable: bool = True


class FailureClassifiedPayload(BaseModel):
    """Payload for failure.classified.v1 events."""

    transaction_id: str
    failure_code: str
    category: str
    recoverable: bool
    reason_codes: list[str] = Field(default_factory=list)
    classified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecoveryCaseOpenedPayload(BaseModel):
    """Payload for recovery.case_opened.v1 events."""

    recovery_case_id: str
    transaction_id: str
    merchant_id: str
    state: str
    policy_version: str
    candidate_actions: list[str] = Field(default_factory=list)
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IngestionResponse(BaseModel):
    accepted: bool
    duplicate: bool
    transaction_id: UUID
    failure_event_id: UUID
    policy_category: str
    recoverable: bool
