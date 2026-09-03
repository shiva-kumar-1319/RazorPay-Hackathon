"""Payment Environment Simulator — evaluates recovery action outcomes against hidden ground truth."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

from backend.app.models.recovery import ActionType
from backend.app.services.decision_engine import ACTION_COST_MODEL, FRICTION_PENALTY_RATE
from benchmark.scenarios import BenchmarkScenarioItem, HiddenGroundTruth, ObservableFailureEvent


@dataclass(frozen=True)
class SimulationStepResult:
    """Outcome of an attempted recovery action in the simulated payment environment."""

    action_type: str
    recovered: bool
    amount: float
    recovered_amount: float
    execution_cost: float
    friction_cost: float
    net_revenue_recovered: float
    latency_ms: int
    hard_stop_violation: bool
    status: str
    details: dict[str, Any]


class PaymentEnvironmentSimulator:
    """Simulates real payment rail and customer responses based on hidden ground truth physics."""

    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)

    def evaluate_action(
        self,
        scenario: BenchmarkScenarioItem,
        chosen_action: str,
    ) -> SimulationStepResult:
        """Step the environment forward given the chosen recovery action and hidden ground truth."""
        norm_action = chosen_action.strip().upper()
        hidden: HiddenGroundTruth = scenario.hidden_truth
        obs: ObservableFailureEvent = scenario.observable

        # 1. Terminal / Hard Failure Invariant Check
        if hidden.is_terminal_fraud_or_hotlisted:
            if norm_action != "STOP_RECOVERY":
                # Severe compliance violation: merchant attempted recovery on hotlisted or fraudulent card
                cost = 5.00  # Gateway decline penalty fee
                friction = obs.amount * 0.10  # Risk score downgrade impact
                return SimulationStepResult(
                    action_type=norm_action,
                    recovered=False,
                    amount=obs.amount,
                    recovered_amount=0.0,
                    execution_cost=cost,
                    friction_cost=friction,
                    net_revenue_recovered=-(cost + friction),
                    latency_ms=self.rng.randint(350, 900),
                    hard_stop_violation=True,
                    status="COMPLIANCE_VIOLATION",
                    details={"reason": "Attempted recovery on terminal hotlisted/fraud decline."},
                )
            else:
                return SimulationStepResult(
                    action_type="STOP_RECOVERY",
                    recovered=False,
                    amount=obs.amount,
                    recovered_amount=0.0,
                    execution_cost=0.0,
                    friction_cost=0.0,
                    net_revenue_recovered=0.0,
                    latency_ms=10,
                    hard_stop_violation=False,
                    status="STOPPED_SAFELY",
                    details={"reason": "Correct terminal stop executed."},
                )

        if norm_action == "STOP_RECOVERY":
            return SimulationStepResult(
                action_type="STOP_RECOVERY",
                recovered=False,
                amount=obs.amount,
                recovered_amount=0.0,
                execution_cost=0.0,
                friction_cost=0.0,
                net_revenue_recovered=0.0,
                latency_ms=10,
                hard_stop_violation=False,
                status="NO_ACTION",
                details={"reason": "Recovery deliberately withheld."},
            )

        # 2. Lookup standard action costs and friction
        try:
            act_enum = ActionType(norm_action)
            cost_cfg = ACTION_COST_MODEL[act_enum]
            exec_cost = cost_cfg.execution_cost
            friction_cost = round(FRICTION_PENALTY_RATE * obs.amount * cost_cfg.customer_friction_score, 2)
        except (ValueError, KeyError):
            exec_cost = 2.00
            friction_cost = round(obs.amount * 0.02, 2)

        # 3. Simulate outcome grounded in payment rail physics & customer willingness
        roll = self.rng.random()
        recovered = False

        if norm_action == "RETRY_SAME_METHOD":
            if obs.failure_category == "TEMPORARY":
                # Success depends on switch load recovering
                p_success = max(0.10, (1.0 - hidden.system_transient_degradation) * 0.90)
                recovered = roll < p_success
            else:
                # Immediate retry on a card decline, invalid PIN, or lack of funds has near-zero success
                recovered = roll < 0.04

        elif norm_action == "DELAYED_RETRY":
            if obs.failure_category == "TEMPORARY":
                # By delaying, network congestion or bank CBS maintenance window has passed
                recovered = roll < 0.86
            elif obs.failure_code == "INSUFFICIENT_FUNDS":
                # Customer might have topped up or salary credited
                recovered = hidden.has_sufficient_balance and (roll < 0.35)
            else:
                recovered = roll < 0.12

        elif norm_action in ("SWITCH_TO_UPI", "SWITCH_TO_NETBANKING", "SWITCH_TO_CARD"):
            if hidden.has_active_alternate_instrument and hidden.has_sufficient_balance:
                recovered = roll < 0.88
            else:
                recovered = roll < 0.15

        elif norm_action in ("CUSTOMER_NOTIFICATION", "PAYMENT_LINK"):
            if hidden.has_sufficient_balance:
                p_compliance = hidden.customer_willingness_to_retry * 0.92
                recovered = roll < p_compliance
            else:
                recovered = False
        else:
            recovered = False

        recovered_amt = obs.amount if recovered else 0.0
        net_rev = recovered_amt - exec_cost - friction_cost
        latency = self.rng.randint(200, 750) if recovered else self.rng.randint(300, 1200)

        return SimulationStepResult(
            action_type=norm_action,
            recovered=recovered,
            amount=obs.amount,
            recovered_amount=round(recovered_amt, 2),
            execution_cost=round(exec_cost, 2),
            friction_cost=round(friction_cost, 2),
            net_revenue_recovered=round(net_rev, 2),
            latency_ms=latency,
            hard_stop_violation=False,
            status="SUCCEEDED" if recovered else "FAILED",
            details={
                "category": obs.failure_category,
                "code": obs.failure_code,
            },
        )
