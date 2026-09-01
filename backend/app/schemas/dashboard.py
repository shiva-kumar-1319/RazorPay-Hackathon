"""Pydantic schemas for Day 12 Dashboard & Recovery Analytics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DashboardOverviewMetrics(BaseModel):
    """Aggregate KPIs for merchant recovery overview."""

    merchant_id: str
    currency: str = "INR"
    total_transactions_count: int = 0
    total_failed_count: int = 0
    total_failed_gmv: Decimal = Decimal("0.00")
    total_recovered_count: int = 0
    total_recovered_gmv: Decimal = Decimal("0.00")
    total_open_cases_count: int = 0
    total_scheduled_cases_count: int = 0
    total_stopped_cases_count: int = 0
    total_review_cases_count: int = 0
    eligible_failed_count: int = 0
    eligible_failed_gmv: Decimal = Decimal("0.00")
    recovery_rate_pct: Decimal = Decimal("0.00")
    gross_recovery_rate_pct: Decimal = Decimal("0.00")
    incremental_recovery_gmv: Decimal = Decimal("0.00")
    avg_recovery_time_seconds: float = 0.0
    avg_attempts_per_case: float = 0.0
    customer_friction_score: float = 0.0
    last_projected_at: datetime
    hourly_trends: list[dict[str, Any]] = Field(default_factory=list)
    action_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    category_breakdown: list[dict[str, Any]] = Field(default_factory=list)


class FunnelStageMetric(BaseModel):
    """Single stage in the recovery conversion funnel."""

    stage: str
    label: str
    count: int
    gmv: Decimal
    conversion_rate_from_prev_pct: Decimal
    conversion_rate_from_total_pct: Decimal


class DashboardFunnelResponse(BaseModel):
    """Recovery funnel analysis segmented by failure category and method."""

    merchant_id: str
    currency: str = "INR"
    stages: list[FunnelStageMetric]
    category_funnels: dict[str, list[FunnelStageMetric]] = Field(default_factory=dict)
    method_conversion_matrix: list[dict[str, Any]] = Field(default_factory=list)
    last_projected_at: datetime


class LiveFailedPaymentItem(BaseModel):
    """Single live failed transaction item for the dashboard feed."""

    transaction_id: UUID
    external_transaction_id: str
    merchant_id: str
    customer_id: UUID | None = None
    customer_name: str | None = None
    customer_email_masked: str | None = None
    amount: Decimal
    currency: str = "INR"
    payment_method: str
    gateway: str | None = None
    failure_code: str
    failure_category: str
    is_recoverable: bool
    status: str
    recovery_state: str | None = None
    attempt_count: int = 1
    latest_error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class LiveFailedPaymentsResponse(BaseModel):
    """Paginated list of live failed payments."""

    total: int
    items: list[LiveFailedPaymentItem]
    last_projected_at: datetime


class AgentDecisionFeedItem(BaseModel):
    """Feed item representing an autonomous recovery agent investigation & decision."""

    investigation_id: str
    transaction_id: UUID
    external_transaction_id: str
    merchant_id: str
    amount: Decimal
    currency: str = "INR"
    failure_code: str
    failure_category: str
    selected_action: str
    confidence_score: Decimal
    expected_value: Decimal
    decision_status: str  # APPROVED, REJECTED, STOPPED, NEEDS_REVIEW
    decision_reasoning: str
    customer_explanation: str | None = None
    tool_calls_executed: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    investigated_at: datetime


class AgentDecisionsResponse(BaseModel):
    """Feed response of agent decisions."""

    total: int
    items: list[AgentDecisionFeedItem]
    last_projected_at: datetime


class RecoveryAttemptItem(BaseModel):
    """Granular record of an executed or scheduled recovery workflow attempt."""

    action_id: UUID
    recovery_case_id: UUID
    transaction_id: UUID
    external_transaction_id: str
    merchant_id: str
    workflow_type: str  # IMMEDIATE_RETRY, METHOD_SWITCH, DELAYED_RETRY, PAYMENT_LINK, STOP_RECOVERY
    action_type: str
    status: str  # PENDING, SCHEDULED, IN_PROGRESS, COMPLETED, FAILED, BLOCKED
    amount: Decimal
    currency: str = "INR"
    attempt_number: int
    instrument_from: str | None = None
    instrument_to: str | None = None
    scheduled_at: datetime | None = None
    executed_at: datetime | None = None
    execution_channel: str | None = None
    session_token: str | None = None
    latency_ms: float | None = None
    success: bool | None = None
    error_message: str | None = None
    created_at: datetime


class RecoveryAttemptsResponse(BaseModel):
    """Feed response of recovery attempts."""

    total: int
    items: list[RecoveryAttemptItem]
    last_projected_at: datetime


class ModelHealthResponse(BaseModel):
    """Projections of recovery prediction model accuracy, distribution, and calibration."""

    model_version: str
    model_type: str
    auc_roc: float
    accuracy: float
    brier_score: float
    total_scored_candidates: int
    score_distribution: dict[str, int]
    action_probabilities_avg: dict[str, float]
    feature_importances: list[dict[str, Any]]
    calibration_curve: list[dict[str, Any]]
    last_trained_at: str | None = None
    last_projected_at: datetime


class SimulateBatchRequest(BaseModel):
    """Request payload for simulating a live stream of realistic payment failures and recoveries."""

    merchant_id: str = "merch_101"
    count: int = Field(default=8, ge=1, le=50)
    auto_investigate: bool = True
    auto_execute: bool = True


class SimulateBatchResponse(BaseModel):
    """Result of running a live simulation batch."""

    merchant_id: str
    generated_count: int
    investigated_count: int
    executed_count: int
    recovered_count: int
    recovered_gmv: Decimal
    summary_messages: list[str]
