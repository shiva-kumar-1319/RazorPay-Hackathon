"""API endpoints for Recovery Prediction Model — Day 8."""

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.models.recovery import ActionType
from backend.app.schemas.prediction import (
    FeatureImportanceResponse,
    ModelMetricsResponse,
    PredictionComparisonItem,
    PredictionComparisonRequest,
    PredictionComparisonResponse,
    PredictionRequest,
    PredictionResponse,
    RetrainResponse,
)
from backend.app.services.prediction_model import (
    FEATURE_NAMES,
    RecoveryContext,
    recovery_prediction_model,
)

router = APIRouter(prefix="/api/v1/prediction", tags=["prediction"])


@router.post("/predict", response_model=PredictionResponse)
def predict_recovery_probability(req: PredictionRequest) -> PredictionResponse:
    """Predict recovery success probability for a specific failure × action combination."""
    # Validate action_type
    try:
        action = ActionType(req.action_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action_type: {req.action_type}. Must be one of {[a.value for a in ActionType]}",
        )

    if not recovery_prediction_model.is_trained:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prediction model is not trained yet.",
        )

    ctx = RecoveryContext(
        amount=req.amount,
        failure_category=req.failure_category,
        action_type=action,
        hour_of_day=req.hour_of_day,
        customer_success_rate=req.customer_success_rate,
        customer_recovery_rate=req.customer_recovery_rate,
        customer_risk_score=req.customer_risk_score,
        customer_failure_streak=req.customer_failure_streak,
        customer_avg_txn_value=req.customer_avg_txn_value,
        customer_total_txns=req.customer_total_txns,
        behavioral_segment=req.behavioral_segment,
    )

    probability = recovery_prediction_model.predict_from_context(ctx)

    # Qualitative confidence label
    if probability >= 0.7:
        confidence = "HIGH"
    elif probability >= 0.4:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # Top feature importances
    importances = recovery_prediction_model.get_feature_importance()
    top_features = dict(list(importances.items())[:5])

    return PredictionResponse(
        failure_category=req.failure_category,
        action_type=req.action_type,
        amount=req.amount,
        predicted_probability=probability,
        confidence=confidence,
        top_features=top_features,
    )


@router.post("/compare", response_model=PredictionComparisonResponse)
def compare_action_predictions(req: PredictionComparisonRequest) -> PredictionComparisonResponse:
    """Compare predicted probabilities across all action types for a failure scenario."""
    if not recovery_prediction_model.is_trained:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prediction model is not trained yet.",
        )

    results: list[tuple[str, float]] = []
    for action in ActionType:
        ctx = RecoveryContext(
            amount=req.amount,
            failure_category=req.failure_category,
            action_type=action,
            hour_of_day=req.hour_of_day,
            customer_success_rate=req.customer_success_rate,
            customer_recovery_rate=req.customer_recovery_rate,
            customer_risk_score=req.customer_risk_score,
            customer_failure_streak=req.customer_failure_streak,
            customer_avg_txn_value=req.customer_avg_txn_value,
            customer_total_txns=req.customer_total_txns,
            behavioral_segment=req.behavioral_segment,
        )
        prob = recovery_prediction_model.predict_from_context(ctx)
        results.append((action.value, prob))

    # Sort by probability descending
    results.sort(key=lambda x: x[1], reverse=True)

    predictions = [
        PredictionComparisonItem(action_type=name, predicted_probability=prob, rank=i + 1)
        for i, (name, prob) in enumerate(results)
    ]

    return PredictionComparisonResponse(
        failure_category=req.failure_category,
        amount=req.amount,
        predictions=predictions,
        best_action=results[0][0],
        best_probability=results[0][1],
    )


@router.get("/model/metrics", response_model=ModelMetricsResponse)
def get_model_metrics() -> ModelMetricsResponse:
    """Return model training and evaluation metrics."""
    metrics = recovery_prediction_model.get_model_metrics()
    return ModelMetricsResponse(**metrics)


@router.get("/model/features", response_model=FeatureImportanceResponse)
def get_feature_importances() -> FeatureImportanceResponse:
    """Return ranked feature importances from the trained GBM."""
    importances = recovery_prediction_model.get_feature_importance()
    top_10 = [
        {"feature": name, "importance": imp}
        for name, imp in list(importances.items())[:10]
    ]
    return FeatureImportanceResponse(importances=importances, top_10=top_10)


@router.post("/model/retrain", response_model=RetrainResponse)
def retrain_model(
    n_samples: int = Query(5000, ge=1000, le=50000),
    seed: int = Query(42),
) -> RetrainResponse:
    """Trigger model retraining with fresh synthetic data."""
    metrics = recovery_prediction_model.train(n_samples=n_samples, seed=seed)
    return RetrainResponse(status="retrained", metrics=metrics)
