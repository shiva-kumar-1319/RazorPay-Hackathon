"""Deterministic policy gate used before any model or agent recommendation."""

from dataclasses import dataclass

from backend.app.models.recovery import ActionType


HARD_STOP_CODES = {
    "BLOCKED_CARD",
    "INVALID_ACCOUNT",
    "FRAUD_REJECTED",
    "EXPIRED_CARD",
    "LIMIT_EXCEEDED_HARD",
}

CUSTOMER_ACTION_CODES = {
    "OTP_TIMEOUT",
    "3DS_FAILURE",
    "INSUFFICIENT_FUNDS",
    "INCORRECT_PIN",
    "USER_CANCELLED",
}

PAYMENT_METHOD_CODES = {
    "CARD_DECLINED",
    "CARD_TYPE_NOT_SUPPORTED",
    "MANDATE_FAILED",
}

TEMPORARY_CODES = {
    "TIMEOUT",
    "NETWORK_ERROR",
    "UPI_FAILURE",
    "GATEWAY_ERROR",
    "BANK_SERVER_DOWN",
}


@dataclass(frozen=True)
class PolicyResult:
    category: str
    recoverable: bool
    permitted_actions: tuple[ActionType, ...]
    reason_codes: tuple[str, ...]


def evaluate_failure_policy(failure_code: str) -> PolicyResult:
    """Classify a normalized failure code into safe candidate actions."""
    normalized = failure_code.upper()
    if normalized in HARD_STOP_CODES:
        return PolicyResult("HARD_FAILURE", False, (ActionType.STOP_RECOVERY,), ("HARD_STOP", normalized))
    if normalized in CUSTOMER_ACTION_CODES:
        return PolicyResult(
            "CUSTOMER_ACTION",
            True,
            (ActionType.CUSTOMER_NOTIFICATION, ActionType.PAYMENT_LINK),
            ("CUSTOMER_ACTION_REQUIRED", normalized),
        )
    if normalized in PAYMENT_METHOD_CODES:
        return PolicyResult(
            "PAYMENT_METHOD",
            True,
            (ActionType.SWITCH_TO_UPI, ActionType.PAYMENT_LINK, ActionType.SWITCH_TO_NETBANKING),
            ("ALTERNATE_METHOD_PREFERRED", normalized),
        )
    if normalized in TEMPORARY_CODES:
        return PolicyResult(
            "TEMPORARY",
            True,
            (ActionType.DELAYED_RETRY, ActionType.RETRY_SAME_METHOD),
            ("TRANSIENT_FAILURE", normalized),
        )
    return PolicyResult(
        "UNKNOWN",
        False,
        (ActionType.STOP_RECOVERY,),
        ("UNCLASSIFIED_FAILURE", normalized),
    )
