"""Pydantic schemas for Day 13 Evaluation + Business Proof.

Covers Baseline vs RecoverX benchmarks, financial ROI calculations,
stopping rules verification, and immutable audit trail reconstruction.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkStrategy(str, Enum):
    """Evaluation strategy models for comparative benchmarks."""
    NO_ACTION = "NO_ACTION"
    BLIND_RETRY = "BLIND_RETRY"
    RULE_BASED_HEURISTIC = "RULE_BASED_HEURISTIC"
    RECOVERX_AI = "RECOVERX_AI"


class BenchmarkRunRequest(BaseModel):
    """Request payload to initiate a comparative evaluation benchmark."""
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(default="merch_101", description="Merchant ID context")
    num_transactions: int = Field(default=100, ge=5, le=1000, description="Total transactions in the simulation batch")
    scenarios: list[str] | None = Field(
        default=None,
        description="Optional specific failure scenarios (e.g. ['CARD_DECLINED', 'INSUFFICIENT_FUNDS', 'NETWORK_TIMEOUT', 'OTP_TIMEOUT', 'BANK_OUTAGE', 'FRAUD_REJECTED'])",
    )
    seed: int = Field(default=42, description="Random seed for deterministic reproducibility")


class StrategyMetrics(BaseModel):
    """Performance & financial ROI metrics for a single recovery strategy."""
    strategy: BenchmarkStrategy
    strategy_name: str
    description: str
    total_failed_txns: int
    total_failed_gmv: Decimal
    recovered_txns: int
    recovered_gmv: Decimal
    net_recovery_rate_pct: float
    gross_recovery_rate_pct: float
    execution_cost: Decimal
    friction_penalty: Decimal
    net_financial_gain: Decimal
    roi_multiplier: float
    hard_failures_blocked: int
    unnecessary_retries: int
    avg_turnaround_seconds: float


class CategoryBreakdownItem(BaseModel):
    """Recovery rate breakdown by canonical failure category."""
    failure_category: str
    total_count: int
    no_action_recovered: int
    blind_retry_recovered: int
    heuristic_recovered: int
    recoverx_recovered: int
    recoverx_recovery_rate_pct: float


class BenchmarkComparisonResponse(BaseModel):
    """Comparative benchmark results across all 4 recovery strategies."""
    benchmark_id: str
    merchant_id: str
    evaluated_at: datetime
    total_transactions: int
    total_failed_gmv: Decimal
    strategies: dict[str, StrategyMetrics]
    incremental_gmv_vs_no_action: Decimal
    incremental_gmv_vs_blind_retry: Decimal
    incremental_gmv_vs_heuristic: Decimal
    recovery_rate_lift_pct_vs_blind: float
    recovery_rate_lift_pct_vs_heuristic: float
    net_profit_gain_vs_blind: Decimal
    category_breakdown: list[CategoryBreakdownItem]


class BusinessProofSummaryResponse(BaseModel):
    """Executive summary of business proof, ROI, and financial lift."""
    merchant_id: str
    total_failed_gmv: Decimal
    recovered_gmv: Decimal
    net_recovery_rate_pct: float
    incremental_revenue_gain: Decimal
    net_roi_multiplier: float
    cost_to_recover_ratio_pct: float
    customer_friction_reduction_pct: float
    hard_failures_safely_blocked: int
    double_billing_prevention_rate_pct: float
    stopping_rules_compliance_pct: float
    key_findings: list[str]


class StoppingRuleAuditItem(BaseModel):
    """Audit verification item for a safety stopping rule."""
    rule_code: str
    rule_name: str
    description: str
    test_scenario: str
    guard_type: str
    compliance_status: str  # "COMPLIANT" | "VERIFIED"
    total_checks: int
    violations_count: int
    sample_audit_reason: str


class StoppingRulesResponse(BaseModel):
    """Comprehensive stopping rules compliance & safety audit report."""
    merchant_id: str
    audited_at: datetime
    overall_compliance_pct: float
    total_rules_audited: int
    passed_rules_count: int
    zero_violation_guarantee: bool
    rules: list[StoppingRuleAuditItem]


class AuditTimelineEvent(BaseModel):
    """Individual event in a transaction's immutable audit trail."""
    step_number: int
    timestamp: datetime
    stage: str
    actor: str  # "SYSTEM" | "AGENT_RECOVERX" | "EXECUTION_ENGINE" | "CUSTOMER_PORTAL"
    action: str
    description: str
    policy_version: str | None = None
    before_state: str | None = None
    after_state: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    checksum_hash: str


class AuditTrailResponse(BaseModel):
    """Complete chronological audit trail for a transaction."""
    transaction_id: str
    external_transaction_id: str
    merchant_id: str
    total_events: int
    status: str
    recovery_state: str | None
    amount: Decimal
    currency: str
    customer_email_masked: str | None
    integrity_verified: bool
    events: list[AuditTimelineEvent]
