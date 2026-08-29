"""API endpoints for Recovery Decision Engine — Day 9."""

from fastapi import APIRouter

from backend.app.models.recovery import ActionType
from backend.app.schemas.decision import (
    CostModelResponse,
    DecisionExplanationResponse,
    DecisionRequest,
    DecisionResponse,
    RecommendationResponse,
    ScoredActionResponse,
)
from backend.app.services.decision_engine import (
    ACTION_COST_MODEL,
    FRICTION_PENALTY_RATE,
    TIME_DECAY_RATE,
    recovery_decision_engine,
)

router = APIRouter(prefix="/api/v1/decision", tags=["decision"])


def _build_scored_response(sa) -> ScoredActionResponse:
    return ScoredActionResponse(
        action_type=sa.action_type.value,
        probability=sa.probability,
        expected_value=sa.expected_value,
        gross_expected_value=sa.gross_expected_value,
        execution_cost=sa.execution_cost,
        friction_penalty=sa.friction_penalty,
        time_decay_factor=sa.time_decay_factor,
        customer_friction_score=sa.customer_friction_score,
        time_to_recovery_hours=sa.time_to_recovery_hours,
        channel=sa.channel,
        rank=sa.rank,
        selected=sa.selected,
        reason=sa.reason,
    )


def _get_candidates(failure_category: str) -> list[ActionType]:
    """Return the candidate actions for a failure category (policy-gated)."""
    cat = failure_category.upper()
    if cat == "TEMPORARY":
        return [ActionType.DELAYED_RETRY, ActionType.RETRY_SAME_METHOD, ActionType.SWITCH_TO_UPI]
    elif cat == "PAYMENT_METHOD":
        return [ActionType.SWITCH_TO_UPI, ActionType.PAYMENT_LINK, ActionType.SWITCH_TO_NETBANKING]
    elif cat == "CUSTOMER_ACTION":
        return [ActionType.CUSTOMER_NOTIFICATION, ActionType.PAYMENT_LINK, ActionType.SWITCH_TO_UPI]
    elif cat == "HARD_FAILURE":
        return [ActionType.STOP_RECOVERY]
    else:
        return [ActionType.PAYMENT_LINK, ActionType.CUSTOMER_NOTIFICATION]


@router.post("/evaluate", response_model=DecisionResponse)
def evaluate_actions(req: DecisionRequest) -> DecisionResponse:
    """Evaluate all candidate recovery actions and return ranked scores with explanations."""
    candidates = _get_candidates(req.failure_category)

    scored = recovery_decision_engine.evaluate_actions(
        failure_category=req.failure_category,
        amount=req.amount,
        candidate_action_types=candidates,
        customer_intel=None,  # API-driven — customer intel passed as flat fields
        hour_of_day=req.hour_of_day,
    )

    explanation_obj = recovery_decision_engine.explain_decision(scored)

    best = scored[0] if scored else None

    return DecisionResponse(
        failure_category=req.failure_category,
        amount=req.amount,
        best_action=_build_scored_response(best) if best else ScoredActionResponse(
            action_type="NONE", probability=0, expected_value=0, gross_expected_value=0,
            execution_cost=0, friction_penalty=0, time_decay_factor=0,
            customer_friction_score=0, time_to_recovery_hours=0, channel="none",
            rank=0, selected=False,
        ),
        all_actions=[_build_scored_response(sa) for sa in scored],
        explanation=DecisionExplanationResponse(
            best_action=explanation_obj.best_action,
            best_ev=explanation_obj.best_ev,
            best_probability=explanation_obj.best_probability,
            summary=explanation_obj.summary,
            comparison=explanation_obj.comparison,
        ),
    )


@router.post("/recommend", response_model=RecommendationResponse)
def recommend_best_action(req: DecisionRequest) -> RecommendationResponse:
    """Return only the single best recommended recovery action with explanation."""
    candidates = _get_candidates(req.failure_category)

    scored = recovery_decision_engine.evaluate_actions(
        failure_category=req.failure_category,
        amount=req.amount,
        candidate_action_types=candidates,
        hour_of_day=req.hour_of_day,
    )

    explanation_obj = recovery_decision_engine.explain_decision(scored)
    best = recovery_decision_engine.select_best_action(scored)

    return RecommendationResponse(
        failure_category=req.failure_category,
        amount=req.amount,
        recommended_action=best.action_type.value if best else "NONE",
        predicted_probability=best.probability if best else 0.0,
        expected_value=best.expected_value if best else 0.0,
        explanation=explanation_obj.summary,
    )


@router.get("/cost-model", response_model=CostModelResponse)
def get_cost_model() -> CostModelResponse:
    """Inspect the action cost model configuration used for EV calculations."""
    return CostModelResponse(
        cost_model=recovery_decision_engine.get_cost_model(),
        friction_penalty_rate=FRICTION_PENALTY_RATE,
        time_decay_rate=TIME_DECAY_RATE,
    )
