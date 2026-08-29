"""Unit tests for Recovery Decision Engine — Day 9."""

from decimal import Decimal

from backend.app.models.recovery import ActionType
from backend.app.services.decision_engine import (
    ACTION_COST_MODEL,
    ActionCostConfig,
    RecoveryDecisionEngine,
    ScoredAction,
    calculate_expected_value,
    recovery_decision_engine,
)


class TestExpectedValueCalculation:
    """Verify the EV formula components."""

    def test_basic_ev_calculation(self):
        config = ActionCostConfig(
            execution_cost=1.00,
            time_to_recovery_hours=0.0,
            customer_friction_score=0.0,
            channel="test",
        )
        net_ev, gross_ev, friction_cost, time_decay = calculate_expected_value(
            probability=0.80,
            amount=5000.0,
            cost_config=config,
        )
        assert gross_ev == 4000.0  # 0.80 * 5000
        assert friction_cost == 0.0  # no friction
        assert time_decay == 1.0  # e^0 = 1
        assert net_ev == 3999.0  # 4000 * 1.0 - 1.00 - 0.0

    def test_friction_penalty_reduces_ev(self):
        low_friction = ActionCostConfig(
            execution_cost=0.50, time_to_recovery_hours=0.0,
            customer_friction_score=0.05, channel="test",
        )
        high_friction = ActionCostConfig(
            execution_cost=0.50, time_to_recovery_hours=0.0,
            customer_friction_score=0.50, channel="test",
        )
        ev_low, _, _, _ = calculate_expected_value(0.7, 10000, low_friction)
        ev_high, _, _, _ = calculate_expected_value(0.7, 10000, high_friction)
        assert ev_low > ev_high, "Higher friction should reduce EV"

    def test_time_decay_penalises_slow_recovery(self):
        fast = ActionCostConfig(
            execution_cost=0.50, time_to_recovery_hours=0.1,
            customer_friction_score=0.1, channel="test",
        )
        slow = ActionCostConfig(
            execution_cost=0.50, time_to_recovery_hours=24.0,
            customer_friction_score=0.1, channel="test",
        )
        ev_fast, _, _, td_fast = calculate_expected_value(0.7, 5000, fast)
        ev_slow, _, _, td_slow = calculate_expected_value(0.7, 5000, slow)
        assert td_fast > td_slow, "Fast recovery should have higher time decay factor"
        assert ev_fast > ev_slow, "Faster recovery should have higher EV"

    def test_zero_probability_yields_negative_ev(self):
        config = ActionCostConfig(
            execution_cost=5.00, time_to_recovery_hours=12.0,
            customer_friction_score=0.50, channel="test",
        )
        net_ev, gross_ev, _, _ = calculate_expected_value(0.0, 5000, config)
        assert gross_ev == 0.0
        assert net_ev < 0, "Zero probability should yield negative EV due to costs"


class TestDecisionEngine:
    """Test action evaluation, ranking, and selection."""

    def test_evaluate_returns_ranked_actions(self):
        scored = recovery_decision_engine.evaluate_actions(
            failure_category="PAYMENT_METHOD",
            amount=5000.0,
            candidate_action_types=[ActionType.SWITCH_TO_UPI, ActionType.PAYMENT_LINK],
        )
        assert len(scored) == 2
        assert scored[0].rank == 1
        assert scored[1].rank == 2
        # First should be selected
        assert scored[0].selected is True
        assert scored[1].selected is False

    def test_best_action_has_highest_ev(self):
        scored = recovery_decision_engine.evaluate_actions(
            failure_category="TEMPORARY",
            amount=3000.0,
            candidate_action_types=[ActionType.DELAYED_RETRY, ActionType.RETRY_SAME_METHOD],
        )
        assert scored[0].expected_value >= scored[1].expected_value

    def test_hard_failure_stop_recovery(self):
        scored = recovery_decision_engine.evaluate_actions(
            failure_category="HARD_FAILURE",
            amount=10000.0,
            candidate_action_types=[ActionType.STOP_RECOVERY],
        )
        assert len(scored) == 1
        assert scored[0].action_type == ActionType.STOP_RECOVERY
        assert scored[0].expected_value <= 0

    def test_select_best_action(self):
        scored = recovery_decision_engine.evaluate_actions(
            failure_category="CUSTOMER_ACTION",
            amount=2500.0,
            candidate_action_types=[ActionType.CUSTOMER_NOTIFICATION, ActionType.PAYMENT_LINK],
        )
        best = recovery_decision_engine.select_best_action(scored)
        assert best is not None
        assert best.selected is True
        assert best.rank == 1

    def test_select_best_action_empty_list(self):
        best = recovery_decision_engine.select_best_action([])
        assert best is None

    def test_explain_decision_has_summary(self):
        scored = recovery_decision_engine.evaluate_actions(
            failure_category="PAYMENT_METHOD",
            amount=8000.0,
            candidate_action_types=[ActionType.SWITCH_TO_UPI, ActionType.PAYMENT_LINK],
        )
        explanation = recovery_decision_engine.explain_decision(scored)
        assert explanation.best_action != "NONE"
        assert len(explanation.summary) > 20
        assert len(explanation.comparison) == 2

    def test_explain_decision_empty(self):
        explanation = recovery_decision_engine.explain_decision([])
        assert explanation.best_action == "NONE"
        assert explanation.best_ev == 0.0

    def test_all_action_types_in_cost_model(self):
        for action in ActionType:
            assert action in ACTION_COST_MODEL, f"{action} missing from cost model"

    def test_cost_model_api(self):
        model = recovery_decision_engine.get_cost_model()
        for action in ActionType:
            assert action.value in model
            entry = model[action.value]
            assert "execution_cost" in entry
            assert "time_to_recovery_hours" in entry
            assert "customer_friction_score" in entry
            assert "channel" in entry

    def test_scored_action_contains_all_fields(self):
        scored = recovery_decision_engine.evaluate_actions(
            failure_category="TEMPORARY",
            amount=4000.0,
            candidate_action_types=[ActionType.DELAYED_RETRY],
        )
        sa = scored[0]
        assert sa.probability >= 0
        assert isinstance(sa.expected_value, float)
        assert isinstance(sa.gross_expected_value, float)
        assert isinstance(sa.execution_cost, float)
        assert isinstance(sa.friction_penalty, float)
        assert isinstance(sa.time_decay_factor, float)
        assert isinstance(sa.channel, str)
