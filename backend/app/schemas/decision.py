"""Pydantic schemas for Recovery Decision Engine API endpoints."""

from typing import Any

from pydantic import BaseModel, Field


class ScoredActionResponse(BaseModel):
    """A single scored candidate action."""

    action_type: str
    probability: float
    expected_value: float
    gross_expected_value: float
    execution_cost: float
    friction_penalty: float
    time_decay_factor: float
    customer_friction_score: float
    time_to_recovery_hours: float
    channel: str
    rank: int
    selected: bool
    reason: str = ""


class DecisionRequest(BaseModel):
    """Request to evaluate and rank recovery actions for a failure scenario."""

    failure_category: str = Field(description="TEMPORARY, PAYMENT_METHOD, CUSTOMER_ACTION, or HARD_FAILURE")
    amount: float = Field(gt=0, description="Transaction amount in INR")
    hour_of_day: int = Field(default=12, ge=0, le=23)
    # Optional customer intelligence
    customer_success_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    customer_recovery_rate: float = Field(default=0.3, ge=0.0, le=1.0)
    customer_risk_score: float = Field(default=0.1, ge=0.0, le=1.0)
    customer_failure_streak: int = Field(default=0, ge=0)
    customer_avg_txn_value: float = Field(default=1000.0, ge=0.0)
    customer_total_txns: int = Field(default=5, ge=0)
    behavioral_segment: str = Field(default="STANDARD")


class DecisionExplanationResponse(BaseModel):
    """Human-readable explanation of the decision."""

    best_action: str
    best_ev: float
    best_probability: float
    summary: str
    comparison: list[dict[str, Any]] = Field(default_factory=list)


class DecisionResponse(BaseModel):
    """Full decision response with ranked actions and explanation."""

    failure_category: str
    amount: float
    best_action: ScoredActionResponse
    all_actions: list[ScoredActionResponse]
    explanation: DecisionExplanationResponse


class RecommendationResponse(BaseModel):
    """Simplified recommendation — just the best action and why."""

    failure_category: str
    amount: float
    recommended_action: str
    predicted_probability: float
    expected_value: float
    explanation: str


class CostModelResponse(BaseModel):
    """The full action cost model configuration."""

    cost_model: dict[str, dict[str, Any]]
    friction_penalty_rate: float
    time_decay_rate: float
