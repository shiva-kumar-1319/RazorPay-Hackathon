from backend.app.models.recovery import ActionType
from backend.app.services.recovery_policy import evaluate_failure_policy


def test_hard_failure_is_stopped_before_any_recovery_action() -> None:
    result = evaluate_failure_policy("FRAUD_REJECTED")

    assert result.recoverable is False
    assert result.permitted_actions == (ActionType.STOP_RECOVERY,)
    assert "HARD_STOP" in result.reason_codes


def test_card_decline_prefers_safe_alternate_method() -> None:
    result = evaluate_failure_policy("card_declined")

    assert result.recoverable is True
    assert ActionType.SWITCH_TO_UPI in result.permitted_actions
    assert ActionType.RETRY_SAME_METHOD not in result.permitted_actions
