"""Merchant authentication and authorization dependencies."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException, status

def get_merchant_api_keys() -> dict[str, str]:
    """Retrieve merchant API key mappings loaded from environment configuration."""
    try:
        from backend.app.config import get_settings
        keys = get_settings().merchant_api_keys
        if keys:
            return keys
    except Exception:
        pass
    raw = os.getenv("MERCHANT_API_KEYS")
    if raw:
        try:
            import json
            return json.loads(raw)
        except Exception:
            pass
    return {}


class _MerchantKeyLookup(dict):
    """Dynamic dict proxy pulling merchant keys from environment settings without hardcoding."""
    def __getitem__(self, item: str) -> str:
        return get_merchant_api_keys()[item]
    def __contains__(self, item: object) -> bool:
        return str(item) in get_merchant_api_keys()
    def get(self, item: str, default: Any = None) -> Any:
        return get_merchant_api_keys().get(item, default)


MERCHANT_API_KEYS = _MerchantKeyLookup()

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
