"""Deterministic policy gate using the Failure Intelligence engine before any model or agent recommendation."""

from dataclasses import dataclass

from backend.app.models.recovery import ActionType
from backend.app.schemas.failure import FailureClassificationRequest
from backend.app.services.failure_intelligence import (
    HARD_STOP_CODES,
    CUSTOMER_ACTION_CODES,
    PAYMENT_METHOD_CODES,
    TEMPORARY_CODES,
    TAXONOMY_CATALOG,
    failure_intelligence_service,
)


@dataclass(frozen=True)
class PolicyResult:
    category: str
    recoverable: bool
    permitted_actions: tuple[ActionType, ...]
    reason_codes: tuple[str, ...]


def evaluate_failure_policy(failure_code: str) -> PolicyResult:
    """Classify a failure code into safe candidate actions using Failure Intelligence."""
    normalized = failure_code.strip().upper() if failure_code else "UNKNOWN"
    
    # 1. Direct codebook fast-path for exact canonical matches
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

    # 2. Check full Failure Intelligence service (for gateway codes, regex, or extended codes)
    detail = failure_intelligence_service.classify_failure(FailureClassificationRequest(failure_code=failure_code))
    
    permitted_enum_actions = []
    for act_str in detail.permitted_actions:
        try:
            permitted_enum_actions.append(ActionType(act_str))
        except ValueError:
            pass

    if not permitted_enum_actions:
        permitted_enum_actions = [ActionType.STOP_RECOVERY]

    reason_code_prefix = {
        "HARD_FAILURE": "HARD_STOP",
        "CUSTOMER_ACTION": "CUSTOMER_ACTION_REQUIRED",
        "PAYMENT_METHOD": "ALTERNATE_METHOD_PREFERRED",
        "TEMPORARY": "TRANSIENT_FAILURE",
    }.get(detail.category.value, "UNCLASSIFIED_FAILURE")

    return PolicyResult(
        category=detail.category.value,
        recoverable=detail.recoverable,
        permitted_actions=tuple(permitted_enum_actions),
        reason_codes=(reason_code_prefix, detail.normalized_code),
    )
