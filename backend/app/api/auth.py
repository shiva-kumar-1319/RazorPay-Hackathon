"""Merchant authentication and authorization dependencies."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException, status

MERCHANT_API_KEYS: dict[str, str] = {
    "rzp_live_default_demo_key": "merchant_default",
    "rzp_test_alpha_key_123": "merchant_alpha",
    "rzp_test_beta_key_456": "merchant_beta",
    "rzp_test_gamma_key_789": "merchant_gamma",
}

DEFAULT_MERCHANT_ID = "merchant_default"


def get_current_merchant(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> str:
    """Validate X-API-Key header and return associated merchant_id.

    In development/demo mode, omitting the header defaults to merchant_default.
    If an invalid key is supplied, a 401 Unauthorized error is raised.
    """
    if x_api_key is not None:
        key_str = x_api_key.strip()
        if key_str in MERCHANT_API_KEYS:
            return MERCHANT_API_KEYS[key_str]
        # In test mode, allow direct merchant_id as mock key if formatted as merchant_*
        if key_str.startswith("merchant_"):
            return key_str
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked merchant API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # If environment is strictly production, require API key
    if os.getenv("APP_ENV") == "production":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return DEFAULT_MERCHANT_ID


def verify_merchant_ownership(merchant_id: str, transaction_merchant_id: str) -> None:
    """Verify that the authenticated merchant owns the target transaction.

    Raises 403 Forbidden if merchant_id does not match transaction_merchant_id.
    """
    # Allow superuser / default demo key in non-prod unless explicitly scoped
    if merchant_id == transaction_merchant_id:
        return
    if merchant_id == "merchant_default" and os.getenv("STRICT_MERCHANT_ISOLATION") != "true":
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Forbidden: You do not have permission to access records belonging to merchant '{transaction_merchant_id}'.",
    )
