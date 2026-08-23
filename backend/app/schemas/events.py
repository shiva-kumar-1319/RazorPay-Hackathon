"""Validated HTTP/event contracts for payment failure ingestion."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class PaymentFailedEvent(BaseModel):
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


class IngestionResponse(BaseModel):
    accepted: bool
    duplicate: bool
    transaction_id: UUID
    failure_event_id: UUID
    policy_category: str
    recoverable: bool
