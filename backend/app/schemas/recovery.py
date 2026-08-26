"""Pydantic schemas for Recovery Case APIs and real-time pipeline status."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RecoveryActionRead(BaseModel):
    id: UUID
    recovery_case_id: UUID
    action_type: str
    idempotency_key: str
    selected: bool
    probability: Decimal | None = None
    expected_value: Decimal | None = None
    reason_codes: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RecoveryCaseRead(BaseModel):
    id: UUID
    transaction_id: UUID
    merchant_id: str | None = None
    external_transaction_id: str | None = None
    amount: Decimal | None = None
    currency: str = "INR"
    state: str
    policy_version: str
    version: int
    created_at: datetime
    updated_at: datetime
    actions: list[RecoveryActionRead] = Field(default_factory=list)


class RecoveryCaseDetail(RecoveryCaseRead):
    transaction_status: str | None = None
    latest_failure_code: str | None = None
    latest_failure_category: str | None = None
    latest_attempt_number: int | None = None
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)


class RecoveryCaseListResponse(BaseModel):
    total: int
    items: list[RecoveryCaseRead]


class OutboxPublishResponse(BaseModel):
    published_count: int
    failed_count: int
    message: str


class PipelineProcessResponse(BaseModel):
    outbox_published: int
    events_dispatched: int
    cases_opened: int
    cases_stopped: int
    errors: list[str] = Field(default_factory=list)


class PipelineStatusResponse(BaseModel):
    outbox_pending_count: int
    outbox_published_count: int
    processed_events_count: int
    quarantine_events_count: int
    total_recovery_cases: int
    open_recovery_cases: int
    stopped_recovery_cases: int
    pipeline_healthy: bool
