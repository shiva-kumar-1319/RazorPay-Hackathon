"""Pydantic schemas for Failure Intelligence classification, taxonomy, and analytics."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FailureCategory(str, Enum):
    TEMPORARY = "TEMPORARY"
    PAYMENT_METHOD = "PAYMENT_METHOD"
    CUSTOMER_ACTION = "CUSTOMER_ACTION"
    HARD_FAILURE = "HARD_FAILURE"
    UNKNOWN = "UNKNOWN"


class FailureClassificationRequest(BaseModel):
    failure_code: str | None = Field(None, description="Standardized or raw failure code, e.g. 'CARD_DECLINED', 'OTP_TIMEOUT'")
    raw_message: str | None = Field(None, description="Unstructured gateway/bank error message, e.g. 'Payer has insufficient funds'")
    gateway: str | None = Field(None, description="Gateway name, e.g. 'RAZORPAY', 'STRIPE', 'PAYU', 'NPCI'")
    gateway_code: str | None = Field(None, description="Gateway-specific error code, e.g. 'BAD_REQUEST_PAYMENT_DECLINED_BY_BANK', 'do_not_honor', 'U69'")
    payment_method: str | None = Field(None, description="Payment method used, e.g. 'CARD', 'UPI', 'NETBANKING'")
    amount: Decimal | None = Field(None, description="Transaction amount for contextual analysis")


class FailureIntelligenceDetail(BaseModel):
    normalized_code: str
    category: FailureCategory
    recoverable: bool
    confidence: Decimal = Field(..., description="Classification confidence from 0.00 to 1.00")
    match_source: str = Field(..., description="Source of classification: 'EXACT_CODE', 'GATEWAY_MAPPER', 'SEMANTIC_PARSER', or 'FALLBACK'")
    suggested_action: str
    permitted_actions: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    retry_delay_seconds: int = Field(default=0, description="Recommended cool-off delay before retry")
    max_retries_permitted: int = Field(default=0, description="Safe maximum retry ceiling")
    customer_explanation: str = Field(..., description="Plain-language explanation for end-customer")
    merchant_explanation: str = Field(..., description="Technical explanation and root cause for merchant dashboard")
    alternative_payment_methods: list[str] = Field(default_factory=list, description="Ranked alternative payment instruments")
    compliance_notes: list[str] = Field(default_factory=list, description="Regulatory, RBI, and safety compliance advisories")


class BatchFailureClassificationRequest(BaseModel):
    items: list[FailureClassificationRequest] = Field(..., min_length=1, max_length=100)


class BatchFailureClassificationResponse(BaseModel):
    total_processed: int
    results: list[FailureIntelligenceDetail]


class FailureTaxonomyItem(BaseModel):
    failure_code: str
    category: FailureCategory
    recoverable: bool
    description: str
    typical_gateways: list[str]
    suggested_action: str
    max_retries: int
    default_delay_seconds: int
    alternative_methods: list[str]


class FailureTaxonomyResponse(BaseModel):
    version: str = "taxonomy.v1"
    categories: list[FailureCategory]
    codes_count: int
    taxonomy: list[FailureTaxonomyItem]
    gateway_mappings: dict[str, dict[str, str]]


class CategoryMetric(BaseModel):
    category: FailureCategory
    count: int
    percentage: Decimal
    recovery_rate: Decimal
    top_failure_code: str | None = None


class FailureAnomalyAlert(BaseModel):
    alert_type: str
    severity: str
    category: FailureCategory | None = None
    gateway: str | None = None
    failure_code: str | None = None
    message: str
    recommended_action: str


class FailureAnalyticsResponse(BaseModel):
    total_failures_recorded: int
    category_breakdown: list[CategoryMetric]
    top_failure_codes: list[dict[str, Any]]
    gateway_failure_rates: list[dict[str, Any]]
    method_failure_rates: list[dict[str, Any]]
    anomalies_detected: list[FailureAnomalyAlert]
