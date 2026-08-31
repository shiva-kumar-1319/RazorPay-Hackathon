"""Pydantic schemas for Recovery Execution workflows, customer recovery links, and scheduling."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ExecuteActionRequest(BaseModel):
    """Request to execute a bounded recovery action."""

    transaction_id: str = Field(..., description="UUID of the failed transaction to execute recovery for")
    action_type: str | None = Field(
        None,
        description="Optional ActionType override (RETRY_SAME_METHOD, SWITCH_TO_UPI, DELAYED_RETRY, PAYMENT_LINK, etc.)",
    )
    recovery_action_id: str | None = Field(None, description="Optional specific RecoveryAction UUID to execute")
    recovery_plan_id: str | None = Field(None, description="Optional plan ID from Agent investigation")
    idempotency_key: str | None = Field(None, description="Optional caller idempotency key")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Action execution parameters (e.g. target_method)")
    force_outcome: str | None = Field(None, description="Optional deterministic test override ('SUCCESS' or 'FAIL')")


class ExecuteActionResponse(BaseModel):
    """Result of executing a recovery action workflow."""

    execution_id: str = Field(..., description="Unique execution attempt ID")
    transaction_id: str = Field(..., description="Transaction UUID")
    recovery_case_id: str = Field(..., description="Recovery Case UUID")
    recovery_action_id: str | None = Field(None, description="Recovery Action UUID")
    action_type: str = Field(..., description="ActionType executed")
    disposition: str = Field(..., description="Execution disposition (APPROVED, QUEUED, COMPLETED, REFUSED, BLOCKED)")
    status: str = Field(..., description="Execution outcome status (SUCCEEDED, SCHEDULED, FAILED, BLOCKED, REFUSED)")
    attempt_number: int | None = Field(None, description="New attempt number created on the transaction")
    new_payment_method: str | None = Field(None, description="Payment method used for this execution")
    execution_channel: str | None = Field(None, description="Channel used for recovery execution")
    scheduled_at: str | None = Field(None, description="ISO timestamp if scheduled for delayed execution")
    message: str = Field(..., description="Human-readable execution outcome summary")
    guard_checks: dict[str, bool] = Field(default_factory=dict, description="Validation results for all safety guards")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional workflow details, tokens, latencies")


class CustomerRecoveryLinkCreateRequest(BaseModel):
    """Request to create a customer payment recovery session and dispatch notification."""

    transaction_id: str = Field(..., description="Transaction UUID")
    recovery_action_id: str | None = Field(None, description="Optional recovery action ID")
    channel: str = Field("SMS", description="Notification delivery channel: SMS, WHATSAPP, EMAIL, IN_APP")
    expires_in_minutes: int = Field(30, ge=5, le=1440, description="Session TTL in minutes")
    custom_message: str | None = Field(None, description="Optional custom narrative override")


class CustomerRecoveryLinkResponse(BaseModel):
    """Customer payment link and notification dispatch confirmation."""

    session_id: str = Field(..., description="Customer Recovery Session UUID")
    token: str = Field(..., description="Crypto-secure public session token")
    checkout_url: str = Field(..., description="Hosted or API checkout URL")
    transaction_id: str = Field(..., description="Transaction UUID")
    amount: Decimal = Field(..., description="Transaction amount")
    currency: str = Field("INR", description="Currency")
    channel: str = Field(..., description="Dispatch channel")
    expires_at: str = Field(..., description="ISO expiration timestamp")
    status: str = Field(..., description="Session status (ACTIVE, COMPLETED, EXPIRED)")
    payment_method_options: list[str] = Field(default_factory=list, description="Available alternative payment methods")
    customer_message: str = Field(..., description="Tailored customer narrative message")


class CustomerCheckoutDetailResponse(BaseModel):
    """Public customer checkout detail view accessed via token."""

    token: str
    transaction_id: str
    merchant_id: str
    amount: Decimal
    currency: str
    status: str
    expires_at: str
    is_expired: bool
    failure_code: str | None
    customer_explanation: str
    payment_method_options: list[str]


class CustomerCheckoutSubmitRequest(BaseModel):
    """Customer payment submission via recovery link."""

    payment_method: str = Field(..., description="Selected payment method (e.g. UPI, CARD, NETBANKING)")
    instrument_details: dict[str, Any] = Field(default_factory=dict, description="Safe instrument parameters (e.g. vpa)")
    simulate_outcome: str | None = Field(None, description="Optional simulation outcome ('SUCCESS' or 'FAIL')")


class CustomerCheckoutSubmitResponse(BaseModel):
    """Result of customer interactive recovery payment."""

    success: bool
    transaction_id: str
    status: str
    payment_method: str
    message: str
    attempt_number: int
    recovered_at: str


class ProcessScheduledRetriesRequest(BaseModel):
    """Request to process due scheduled delayed retries."""

    limit: int = Field(50, ge=1, le=200, description="Max scheduled actions to process in this pass")
    force_now: bool = Field(False, description="If true, execute all scheduled actions regardless of scheduled_at")
    force_outcome: str | None = Field(None, description="Optional forced test simulation outcome ('SUCCESS' or 'FAIL')")


class ProcessScheduledRetriesResponse(BaseModel):
    """Result of scheduled retry processor batch pass."""

    processed_count: int
    succeeded_count: int
    failed_count: int
    executions: list[dict[str, Any]]


class ExecutionMetricsResponse(BaseModel):
    """Aggregated operational metrics for Recovery Execution engine."""

    total_executions: int
    successful_executions: int
    failed_executions: int
    scheduled_executions: int
    overall_recovery_rate: float
    total_recovered_amount: Decimal
    by_workflow: dict[str, dict[str, Any]]
