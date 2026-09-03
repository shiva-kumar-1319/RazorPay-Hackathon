"""Re-export canonical failure taxonomy for backward compatibility."""

from backend.app.canonical_failure_taxonomy import (
    CANONICAL_FAILURE_TAXONOMY,
    GATEWAY_CODE_MAP,
    CanonicalCategory,
    FailureDefinition,
    get_canonical_failure,
    get_permitted_actions,
    is_recoverable,
)

__all__ = [
    "CANONICAL_FAILURE_TAXONOMY",
    "GATEWAY_CODE_MAP",
    "CanonicalCategory",
    "FailureDefinition",
    "get_canonical_failure",
    "get_permitted_actions",
    "is_recoverable",
]
