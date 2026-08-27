"""Schemas for payment simulation requests, responses, and scenario definitions."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.simulator.constants import SimulationScenario


class CreateSimulatedPaymentRequest(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    merchant_id: str | None = Field(default=None, max_length=128)
    external_customer_id: str | None = Field(default=None, max_length=128)
    customer_preferred_method: str | None = Field(default=None, max_length=32)
    payment_method: str | None = Field(default=None, max_length=32)
    gateway: str | None = Field(default=None, max_length=64)
    target_outcome: Literal["SUCCESS", "FAIL"] | None = None
    target_failure_code: str | None = Field(default=None, max_length=64)
    scenario: SimulationScenario = SimulationScenario.NORMAL_BALANCED
    success_rate_override: float | None = Field(default=None, ge=0.0, le=1.0)


class SimulateAttemptRequest(BaseModel):
    payment_method: str | None = Field(default=None, max_length=32)
    gateway: str | None = Field(default=None, max_length=64)
    target_outcome: Literal["SUCCESS", "FAIL"] | None = None
    target_failure_code: str | None = Field(default=None, max_length=64)


class SimulateBatchRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=500)
    merchant_id: str | None = Field(default=None, max_length=128)
    scenario: SimulationScenario = SimulationScenario.NORMAL_BALANCED
    success_rate_override: float | None = Field(default=None, ge=0.0, le=1.0)


class PaymentSimulationResponse(BaseModel):
    transaction_id: UUID
    external_transaction_id: str
    merchant_id: str
    customer_id: UUID | None
    amount: Decimal
    currency: str
    status: str
    attempt_number: int
    payment_method: str
    gateway: str | None
    outcome: Literal["SUCCESS", "FAIL"]
    failure_code: str | None = None
    failure_category: str | None = None
    recoverable: bool | None = None
    error_message: str | None = None
    outbox_event_id: UUID | None = None
    correlation_id: UUID
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class BatchSimulationResponse(BaseModel):
    total_simulated: int
    success_count: int
    failure_count: int
    success_rate: float
    total_amount: Decimal
    recoverable_failure_count: int
    hard_failure_count: int
    failure_code_breakdown: dict[str, int]
    category_breakdown: dict[str, int]
    transactions: list[PaymentSimulationResponse]


class FailureCodeMetadata(BaseModel):
    code: str
    category: str
    description: str
    recoverable: bool
    typical_methods: list[str]
    default_error_message: str


class ScenarioMetadata(BaseModel):
    name: str
    description: str
    default_success_rate: float
    method_weights: dict[str, float]
    failure_weights: dict[str, float]


class ScenarioInfoResponse(BaseModel):
    scenarios: list[ScenarioMetadata]
    failure_codes: list[FailureCodeMetadata]
    payment_methods: list[str]
    gateways: list[str]


class SeedCustomersResponse(BaseModel):
    seeded_customers: int
    seeded_transactions: int
    seeded_attempts: int
    customer_ids: list[str]
    personas: list[str]
    message: str

