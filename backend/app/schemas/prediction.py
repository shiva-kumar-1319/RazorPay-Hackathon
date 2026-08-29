"""Pydantic schemas for Recovery Prediction Model API endpoints."""

from typing import Any

from pydantic import BaseModel, Field


class PredictionRequest(BaseModel):
    """Request to predict recovery success probability for a specific action."""

    failure_code: str = Field(description="Failure code or category (e.g. CARD_DECLINED, TIMEOUT)")
    failure_category: str = Field(description="Canonical category: TEMPORARY, PAYMENT_METHOD, CUSTOMER_ACTION, HARD_FAILURE")
    action_type: str = Field(description="Recovery action type (e.g. SWITCH_TO_UPI, DELAYED_RETRY)")
    amount: float = Field(gt=0, description="Transaction amount in INR")
    hour_of_day: int = Field(default=12, ge=0, le=23, description="Hour of day (0-23)")
    # Optional customer intelligence overrides
    customer_success_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    customer_recovery_rate: float = Field(default=0.3, ge=0.0, le=1.0)
    customer_risk_score: float = Field(default=0.1, ge=0.0, le=1.0)
    customer_failure_streak: int = Field(default=0, ge=0)
    customer_avg_txn_value: float = Field(default=1000.0, ge=0.0)
    customer_total_txns: int = Field(default=5, ge=0)
    behavioral_segment: str = Field(default="STANDARD")


class PredictionResponse(BaseModel):
    """Response with predicted recovery success probability."""

    failure_category: str
    action_type: str
    amount: float
    predicted_probability: float = Field(description="Calibrated P(success) in [0, 1]")
    confidence: str = Field(description="Qualitative confidence label (HIGH/MEDIUM/LOW)")
    top_features: dict[str, float] = Field(
        default_factory=dict,
        description="Top contributing features for this prediction",
    )


class PredictionComparisonItem(BaseModel):
    """A single action in the comparison response."""

    action_type: str
    predicted_probability: float
    rank: int


class PredictionComparisonRequest(BaseModel):
    """Request to compare predictions across all candidate actions for a failure scenario."""

    failure_category: str
    amount: float = Field(gt=0)
    hour_of_day: int = Field(default=12, ge=0, le=23)
    customer_success_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    customer_recovery_rate: float = Field(default=0.3, ge=0.0, le=1.0)
    customer_risk_score: float = Field(default=0.1, ge=0.0, le=1.0)
    customer_failure_streak: int = Field(default=0, ge=0)
    customer_avg_txn_value: float = Field(default=1000.0, ge=0.0)
    customer_total_txns: int = Field(default=5, ge=0)
    behavioral_segment: str = Field(default="STANDARD")


class PredictionComparisonResponse(BaseModel):
    """Compare predicted probabilities for all action types."""

    failure_category: str
    amount: float
    predictions: list[PredictionComparisonItem]
    best_action: str
    best_probability: float


class ModelMetricsResponse(BaseModel):
    """Model training and evaluation metrics."""

    is_trained: bool
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    auc: float = 0.0
    train_samples: int = 0
    test_samples: int = 0
    feature_count: int = 0
    feature_names: list[str] = Field(default_factory=list)


class FeatureImportanceResponse(BaseModel):
    """Feature importance rankings from the trained model."""

    importances: dict[str, float]
    top_10: list[dict[str, Any]]


class RetrainResponse(BaseModel):
    """Response from retraining the model."""

    status: str
    metrics: dict[str, float]
