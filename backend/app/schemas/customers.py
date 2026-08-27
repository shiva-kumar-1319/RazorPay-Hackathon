"""Pydantic schemas for Customer profile, payment behavior, and intelligence analytics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CustomerCreateRequest(BaseModel):
    external_customer_id: str = Field(..., max_length=128, description="Merchant-assigned unique customer identifier")
    merchant_id: str = Field(..., max_length=128, description="Merchant identifier")
    name: str | None = Field(default=None, max_length=128, description="Customer full name")
    email: str | None = Field(default=None, max_length=255, description="Customer email address")
    phone: str | None = Field(default=None, max_length=32, description="Customer phone number (E.164)")
    preferred_payment_method: str | None = Field(default=None, max_length=32, description="Customer preferred instrument (UPI, CARD, NETBANKING)")
    risk_segment: str = Field(default="STANDARD", max_length=32, description="Customer risk tier (VIP, STANDARD, HIGH_RISK, NEW)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Custom merchant-provided metadata")


class CustomerUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    preferred_payment_method: str | None = Field(default=None, max_length=32)
    risk_segment: str | None = Field(default=None, max_length=32)
    metadata: dict[str, Any] | None = None


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_customer_id: str
    merchant_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    preferred_payment_method: str | None = None
    risk_segment: str = "STANDARD"
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class CustomerSummaryItem(BaseModel):
    id: UUID
    external_customer_id: str
    merchant_id: str
    name: str | None = None
    email: str | None = None
    preferred_payment_method: str | None = None
    risk_segment: str = "STANDARD"
    behavioral_segment: str = "NEW_CUSTOMER"
    total_transactions: int = 0
    total_spent: Decimal = Decimal("0.00")
    success_rate: Decimal = Decimal("0.0000")
    recovered_count: int = 0
    recent_failure_streak: int = 0
    last_active_at: datetime | None = None
    created_at: datetime


class CustomerListResponse(BaseModel):
    items: list[CustomerSummaryItem]
    total: int
    limit: int
    offset: int


class PaymentMethodStat(BaseModel):
    method: str
    total_attempts: int
    successful_attempts: int
    failed_attempts: int
    success_rate: float
    total_volume: Decimal
    average_amount: Decimal
    last_used_at: datetime | None = None


class CustomerPaymentBehaviorResponse(BaseModel):
    customer_id: UUID
    external_customer_id: str
    merchant_id: str
    computed_at: datetime
    preferred_payment_method: str | None = None
    behavioral_segment: str
    risk_score: Decimal
    recent_failure_streak: int
    average_transaction_value: Decimal
    last_successful_method: str | None = None
    last_failure_code: str | None = None
    methods: list[PaymentMethodStat]
    hourly_distribution: dict[str, int] = Field(default_factory=dict, description="Transaction attempt count by hour of day (0-23)")
    retry_tolerance_score: float = Field(default=0.5, description="Estimate of how willingly customer retries after failure (0.0 - 1.0)")
    channel_affinity: dict[str, float] = Field(default_factory=dict, description="Historical conversion probabilities by channel")


class CustomerRecoveryHistoryItem(BaseModel):
    recovery_case_id: UUID
    transaction_id: UUID
    external_transaction_id: str
    amount: Decimal
    currency: str
    state: str
    failure_code: str
    actions_count: int
    recommended_action: str | None = None
    created_at: datetime
    updated_at: datetime


class CustomerRecoveryHistoryResponse(BaseModel):
    customer_id: UUID
    external_customer_id: str
    total_recovery_cases: int
    recovered_cases: int
    stopped_cases: int
    open_cases: int
    recovery_conversion_rate: float
    total_recovered_amount: Decimal
    cases: list[CustomerRecoveryHistoryItem]


class CustomerFeaturesSnapshot(BaseModel):
    customer_id: UUID
    external_customer_id: str
    merchant_id: str
    snapshot_time: datetime
    feature_version: str = "v1"
    features: dict[str, Any]
    feature_vector: list[float] = Field(
        default_factory=list,
        description="Standardized numerical array ready for ML scoring [tx_count, success_rate, recency_days, upi_affinity, card_affinity, avg_amount_log, failure_streak, recovery_rate, risk_score]",
    )


class CustomerIntelligenceDetail(BaseModel):
    total_transactions: int = 0
    successful_transactions: int = 0
    failed_transactions: int = 0
    recovered_transactions: int = 0
    total_spent: Decimal = Decimal("0.00")
    total_recovered_amount: Decimal = Decimal("0.00")
    success_rate: Decimal = Decimal("0.0000")
    recovery_rate: Decimal = Decimal("0.0000")
    preferred_payment_method: str | None = None
    method_success_rates: dict[str, Any] = Field(default_factory=dict)
    method_usage_counts: dict[str, Any] = Field(default_factory=dict)
    recent_failure_streak: int = 0
    average_transaction_value: Decimal = Decimal("0.00")
    last_active_at: datetime | None = None
    last_successful_method: str | None = None
    last_failure_code: str | None = None
    risk_score: Decimal = Decimal("0.1000")
    behavioral_segment: str = "NEW_CUSTOMER"
    computed_at: datetime


class CustomerDetailResponse(BaseModel):
    id: UUID
    external_customer_id: str
    merchant_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    preferred_payment_method: str | None = None
    risk_segment: str = "STANDARD"
    metadata: dict[str, Any] = Field(default_factory=dict)
    intelligence: CustomerIntelligenceDetail
    recent_transactions_count: int = 0
    created_at: datetime
    updated_at: datetime
