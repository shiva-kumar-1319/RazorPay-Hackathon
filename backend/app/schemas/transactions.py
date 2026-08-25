"""Schemas for transaction lifecycle queries, attempt timelines, and history."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class FailureEventSummary(BaseModel):
    id: UUID
    source_event_id: str
    failure_code: str
    category: str
    recoverable: bool
    payload: dict[str, Any]
    created_at: datetime


class PaymentAttemptSummary(BaseModel):
    id: UUID
    attempt_number: int
    payment_method: str
    gateway: str | None
    failure_code: str | None
    created_at: datetime
    failures: list[FailureEventSummary] = Field(default_factory=list)


class CustomerSummary(BaseModel):
    id: UUID
    external_customer_id: str
    merchant_id: str
    preferred_payment_method: str | None


class RecoveryActionSummary(BaseModel):
    id: UUID
    action_type: str
    idempotency_key: str
    selected: bool
    probability: Decimal | None
    expected_value: Decimal | None
    reason_codes: list[str]
    created_at: datetime


class RecoveryCaseSummary(BaseModel):
    id: UUID
    state: str
    policy_version: str
    version: int
    actions: list[RecoveryActionSummary] = Field(default_factory=list)
    created_at: datetime


class TransactionDetailResponse(BaseModel):
    id: UUID
    external_transaction_id: str
    merchant_id: str
    customer_id: UUID | None
    customer: CustomerSummary | None = None
    amount: Decimal
    currency: str
    status: str
    version: int
    attempts_count: int
    attempts: list[PaymentAttemptSummary] = Field(default_factory=list)
    recovery_cases: list[RecoveryCaseSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TransactionListItem(BaseModel):
    id: UUID
    external_transaction_id: str
    merchant_id: str
    customer_id: UUID | None
    amount: Decimal
    currency: str
    status: str
    version: int
    attempts_count: int
    latest_failure_code: str | None = None
    latest_payment_method: str | None = None
    created_at: datetime
    updated_at: datetime


class TransactionListResponse(BaseModel):
    items: list[TransactionListItem]
    total: int
    limit: int
    offset: int
