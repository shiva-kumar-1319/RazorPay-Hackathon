"""Evaluated baseline strategies and RecoverX Agent for the benchmark framework."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.canonical_failure_taxonomy import CANONICAL_FAILURE_TAXONOMY, get_canonical_failure
from backend.app.models.recovery import ActionType
from backend.app.services.decision_engine import recovery_decision_engine
from backend.app.services.recovery_policy import evaluate_failure_policy
from benchmark.scenarios import ObservableFailureEvent


class BaseRecoveryStrategy(ABC):
    """Abstract base class for all recovery evaluation strategies."""

    name: str

    @abstractmethod
    def select_action(self, observable: ObservableFailureEvent) -> str:
        """Select a recovery action strictly from observable failure event features."""
        pass


class NoActionBaseline(BaseRecoveryStrategy):
    """Baseline 1: No recovery action attempted. Failed payments remain lost."""

    name = "No Action (Zero Recovery)"

    def select_action(self, observable: ObservableFailureEvent) -> str:
        return "STOP_RECOVERY"


class BlindImmediateRetry(BaseRecoveryStrategy):
    """Baseline 2: Blindly retries the same method for all failures without policy gates."""

    name = "Blind Immediate Retry"

    def select_action(self, observable: ObservableFailureEvent) -> str:
        return "RETRY_SAME_METHOD"


class RuleHeuristicBaseline(BaseRecoveryStrategy):
    """Baseline 3: Fixed heuristic if-else rules without ML prediction or cost-aware EV optimization."""

    name = "Rule-Based Heuristic"

    def select_action(self, observable: ObservableFailureEvent) -> str:
        cat = observable.failure_category.upper()
        if cat == "HARD_FAILURE":
            return "STOP_RECOVERY"
        if cat == "TEMPORARY":
            return "DELAYED_RETRY"
        if cat == "CUSTOMER_ACTION":
            return "PAYMENT_LINK"
        if cat == "PAYMENT_METHOD":
            return "SWITCH_TO_UPI"
        return "RETRY_SAME_METHOD"


class RecoverXAgent(BaseRecoveryStrategy):
    """RecoverX: Cost-Aware Expected-Value Maximization with Policy Gates & Calibrated ML."""

    name = "RecoverX (Cost-Aware EV Agent)"

    def select_action(self, observable: ObservableFailureEvent) -> str:
        # 1. Deterministic Policy Gate check
        policy = evaluate_failure_policy(observable.failure_code)
        if not policy.recoverable:
            return "STOP_RECOVERY"

        permitted = list(policy.permitted_actions)
        if not permitted:
            return "STOP_RECOVERY"

        # 2. Evaluate actions using observable customer history & failure features
        history = observable.customer_history or {}
        scored = recovery_decision_engine.evaluate_actions(
            failure_category=observable.failure_category,
            amount=observable.amount,
            candidate_action_types=permitted,
            hour_of_day=observable.hour_of_day,
            customer_success_rate=history.get("success_rate", 0.5),
            customer_recovery_rate=history.get("recovery_rate", 0.3),
            customer_risk_score=history.get("risk_score", 0.1),
            customer_failure_streak=history.get("failure_streak", 0),
            customer_avg_txn_value=history.get("avg_txn_value", 1000.0),
            customer_total_txns=history.get("total_txns", 5),
            behavioral_segment=history.get("behavioral_segment", "STANDARD"),
        )

        best = recovery_decision_engine.select_best_action(scored)
        if not best or best.expected_value <= 0:
            return "STOP_RECOVERY"

        return best.action_type.value
