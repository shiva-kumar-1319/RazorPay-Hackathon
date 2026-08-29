"""Recovery Decision Engine — expected-value maximisation for optimal action selection.

Day 9 deliverable: combines ML-predicted success probabilities with a cost model
(execution cost, customer friction, time decay) to compute the Expected Value of each
candidate recovery action and select the one that maximises net revenue recovery.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.app.models.recovery import ActionType, CustomerIntelligence
from backend.app.services.prediction_model import (
    RecoveryContext,
    RecoveryFeatureExtractor,
    recovery_prediction_model,
)

logger = logging.getLogger("recoverx.decision_engine")

# ============================================================================
# 1. ACTION COST MODEL
# ============================================================================


@dataclass(frozen=True)
class ActionCostConfig:
    """Operational cost parameters for a single recovery action type."""

    execution_cost: float  # ₹ direct cost to execute (gateway fees, SMS, etc.)
    time_to_recovery_hours: float  # average elapsed time to recovery completion
    customer_friction_score: float  # 0 = zero friction, 1 = max friction
    channel: str  # delivery mechanism


ACTION_COST_MODEL: dict[ActionType, ActionCostConfig] = {
    ActionType.RETRY_SAME_METHOD: ActionCostConfig(
        execution_cost=0.50,
        time_to_recovery_hours=0.1,
        customer_friction_score=0.05,
        channel="system",
    ),
    ActionType.SWITCH_TO_UPI: ActionCostConfig(
        execution_cost=1.00,
        time_to_recovery_hours=0.2,
        customer_friction_score=0.15,
        channel="checkout_redirect",
    ),
    ActionType.SWITCH_TO_CARD: ActionCostConfig(
        execution_cost=1.50,
        time_to_recovery_hours=0.3,
        customer_friction_score=0.20,
        channel="checkout_redirect",
    ),
    ActionType.SWITCH_TO_NETBANKING: ActionCostConfig(
        execution_cost=1.50,
        time_to_recovery_hours=0.5,
        customer_friction_score=0.25,
        channel="checkout_redirect",
    ),
    ActionType.DELAYED_RETRY: ActionCostConfig(
        execution_cost=0.50,
        time_to_recovery_hours=1.0,
        customer_friction_score=0.05,
        channel="system",
    ),
    ActionType.CUSTOMER_NOTIFICATION: ActionCostConfig(
        execution_cost=2.00,
        time_to_recovery_hours=2.0,
        customer_friction_score=0.30,
        channel="push_sms",
    ),
    ActionType.PAYMENT_LINK: ActionCostConfig(
        execution_cost=5.00,
        time_to_recovery_hours=12.0,
        customer_friction_score=0.50,
        channel="sms_email",
    ),
    ActionType.STOP_RECOVERY: ActionCostConfig(
        execution_cost=0.00,
        time_to_recovery_hours=0.0,
        customer_friction_score=0.0,
        channel="none",
    ),
}

# Global tuning knobs
FRICTION_PENALTY_RATE = 0.02  # 2% of amount per unit of customer friction
TIME_DECAY_RATE = 0.01  # exponential decay constant for time-to-recovery


# ============================================================================
# 2. SCORED ACTION DATA CLASS
# ============================================================================


@dataclass
class ScoredAction:
    """A candidate action fully scored with probability, EV, and cost breakdown."""

    action_type: ActionType
    probability: float
    expected_value: float
    gross_expected_value: float  # P × amount (before deductions)
    execution_cost: float
    friction_penalty: float
    time_decay_factor: float
    customer_friction_score: float
    time_to_recovery_hours: float
    channel: str
    rank: int = 0
    selected: bool = False
    reason: str = ""


@dataclass
class DecisionExplanation:
    """Human-readable explanation of why a particular action was selected."""

    best_action: str
    best_ev: float
    best_probability: float
    summary: str
    comparison: list[dict[str, Any]] = field(default_factory=list)


# ============================================================================
# 3. EXPECTED VALUE CALCULATOR
# ============================================================================


def calculate_expected_value(
    probability: float,
    amount: float,
    cost_config: ActionCostConfig,
) -> tuple[float, float, float, float]:
    """Compute net expected value with cost adjustments.

    Returns:
        (net_ev, gross_ev, friction_penalty, time_decay_factor)

    Formula:
        gross_ev       = P(success) × amount
        friction_cost  = FRICTION_PENALTY_RATE × amount × friction_score
        time_decay     = e^(-TIME_DECAY_RATE × time_to_recovery_hours)
        net_ev         = (gross_ev × time_decay) - execution_cost - friction_cost
    """
    gross_ev = probability * amount
    friction_cost = FRICTION_PENALTY_RATE * amount * cost_config.customer_friction_score
    time_decay = math.exp(-TIME_DECAY_RATE * cost_config.time_to_recovery_hours)
    net_ev = (gross_ev * time_decay) - cost_config.execution_cost - friction_cost

    return (
        round(net_ev, 2),
        round(gross_ev, 2),
        round(friction_cost, 2),
        round(time_decay, 6),
    )


# ============================================================================
# 4. DECISION ENGINE
# ============================================================================


class RecoveryDecisionEngine:
    """Evaluates all candidate actions, ranks by EV, and selects the optimal one."""

    def __init__(self) -> None:
        self._extractor = RecoveryFeatureExtractor()

    def evaluate_actions(
        self,
        failure_category: str,
        amount: float,
        candidate_action_types: list[ActionType],
        customer_intel: CustomerIntelligence | None = None,
        hour_of_day: int = 12,
    ) -> list[ScoredAction]:
        """Score every candidate action using ML prediction + EV calculation.

        Returns a list of ScoredAction sorted descending by expected_value.
        """
        scored: list[ScoredAction] = []

        for action_type in candidate_action_types:
            # Build prediction context
            ctx = RecoveryFeatureExtractor.from_recovery_data(
                amount=Decimal(str(amount)),
                failure_category=failure_category,
                action_type=action_type,
                customer_intel=customer_intel,
                hour_of_day=hour_of_day,
            )

            # Get ML prediction
            if recovery_prediction_model.is_trained:
                probability = recovery_prediction_model.predict_from_context(ctx)
            else:
                # Fallback: use heuristic base rate
                probability = 0.5

            # Compute expected value
            cost_config = ACTION_COST_MODEL[action_type]
            
            # Special logic for STOP_RECOVERY
            if action_type == ActionType.STOP_RECOVERY:
                net_ev = 0.0
                gross_ev = 0.0
                friction_cost = 0.0
                time_decay = 1.0
            else:
                net_ev, gross_ev, friction_cost, time_decay = calculate_expected_value(
                    probability=probability,
                    amount=amount,
                    cost_config=cost_config,
                )

            scored.append(
                ScoredAction(
                    action_type=action_type,
                    probability=probability,
                    expected_value=net_ev,
                    gross_expected_value=gross_ev,
                    execution_cost=cost_config.execution_cost,
                    friction_penalty=friction_cost,
                    time_decay_factor=time_decay,
                    customer_friction_score=cost_config.customer_friction_score,
                    time_to_recovery_hours=cost_config.time_to_recovery_hours,
                    channel=cost_config.channel,
                )
            )

        # Sort descending by EV, tie-break by probability (desc), then friction (asc)
        scored.sort(key=lambda s: (-s.expected_value, -s.probability, s.customer_friction_score))

        # Assign ranks and select best
        for i, sa in enumerate(scored):
            sa.rank = i + 1
            if i == 0:
                sa.selected = True
                sa.reason = f"Highest expected value (₹{sa.expected_value:.2f}) with {sa.probability:.1%} predicted success"

        return scored

    def select_best_action(self, scored_actions: list[ScoredAction]) -> ScoredAction | None:
        """Return the top-ranked scored action."""
        if not scored_actions:
            return None
        return scored_actions[0]

    def explain_decision(self, scored_actions: list[ScoredAction]) -> DecisionExplanation:
        """Generate a human-readable explanation of the decision."""
        if not scored_actions:
            return DecisionExplanation(
                best_action="NONE",
                best_ev=0.0,
                best_probability=0.0,
                summary="No candidate actions available for evaluation.",
            )

        best = scored_actions[0]
        comparison = []
        for sa in scored_actions:
            comparison.append({
                "rank": sa.rank,
                "action": sa.action_type.value,
                "probability": f"{sa.probability:.1%}",
                "expected_value": f"₹{sa.expected_value:.2f}",
                "execution_cost": f"₹{sa.execution_cost:.2f}",
                "friction": f"{sa.customer_friction_score:.0%}",
                "time_hours": f"{sa.time_to_recovery_hours:.1f}h",
                "selected": sa.selected,
            })

        # Build narrative summary
        runner_up_text = ""
        if len(scored_actions) > 1:
            second = scored_actions[1]
            ev_diff = best.expected_value - second.expected_value
            runner_up_text = (
                f" Runner-up {second.action_type.value} has EV ₹{second.expected_value:.2f}"
                f" (₹{ev_diff:.2f} lower)."
            )

        summary = (
            f"Selected {best.action_type.value} as the optimal recovery action. "
            f"ML model predicts {best.probability:.1%} success probability, yielding "
            f"expected value ₹{best.expected_value:.2f} after deducting ₹{best.execution_cost:.2f} "
            f"execution cost and ₹{best.friction_penalty:.2f} friction penalty."
            f"{runner_up_text}"
        )

        return DecisionExplanation(
            best_action=best.action_type.value,
            best_ev=best.expected_value,
            best_probability=best.probability,
            summary=summary,
            comparison=comparison,
        )

    def get_cost_model(self) -> dict[str, dict[str, Any]]:
        """Return the full cost model configuration as a serializable dict."""
        result = {}
        for action_type, config in ACTION_COST_MODEL.items():
            result[action_type.value] = {
                "execution_cost": config.execution_cost,
                "time_to_recovery_hours": config.time_to_recovery_hours,
                "customer_friction_score": config.customer_friction_score,
                "channel": config.channel,
            }
        return result


# Singleton
recovery_decision_engine = RecoveryDecisionEngine()
