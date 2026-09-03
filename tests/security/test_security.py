"""Dedicated Security Test Suite for Authentication, Tenant Isolation, PII Redaction, and CORS."""

from decimal import Decimal
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.api.auth import get_current_merchant, verify_merchant_ownership
from backend.app.main import app
from backend.app.models.recovery import Customer, Transaction, TransactionStatus
from backend.app.services.agent_tools import _mask_email, _mask_phone, agent_tool_registry


def test_pii_masking_primitives():
    """Verify Email and Phone masking functions eliminate sensitive identifiers."""
    # Email
    assert _mask_email("johndoe@example.com") == "j*****e@example.com"
    assert _mask_email("a@b.com") == "a*@b.com"
    assert _mask_email(None) is None

    # Phone
    assert _mask_phone("+919876543210") == "+91 ******3210"
    assert _mask_phone(None) is None



def test_agent_tool_context_redacts_pii(db_session: Session):
    """Verify agent inspect_failure / get_transaction_context tool strictly redacts PII."""
    cust = Customer(
        external_customer_id=f"cust_sec_{uuid4().hex[:6]}",
        merchant_id="merch_acme",
        email="compliance_officer@fintech.org",
        phone="+919876543210",
        name="John Doe",
    )
    db_session.add(cust)
    db_session.flush()


    txn = Transaction(
        external_transaction_id=f"txn_sec_{uuid4().hex[:8]}",
        merchant_id="merch_acme",
        customer_id=cust.id,
        amount=Decimal("4500.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.commit()

    res = agent_tool_registry.execute_tool(
        session=db_session,
        tool_name="get_transaction_context",
        arguments={"transaction_id": str(txn.id)},
    )
    assert res.success is True
    output = res.data

    assert "compliance_officer@fintech.org" not in str(output)
    assert "+919876543210" not in str(output)
    assert output["customer"]["masked_email"] is not None
    assert output["customer"]["masked_phone"] == "+91 ******3210"





def test_tenant_isolation_ownership_enforcement():
    """Verify verify_merchant_ownership raises 403 Forbidden on tenant mismatch."""
    from fastapi import HTTPException

    # Same merchant succeeds
    verify_merchant_ownership("merch_101", "merch_101")

    # Mismatched merchant raises 403
    with pytest.raises(HTTPException) as exc_info:
        verify_merchant_ownership("merch_attacker", "merch_victim")
    assert exc_info.value.status_code == 403
    assert "Forbidden" in exc_info.value.detail


def test_force_outcome_blocked_in_production(client: TestClient, db_session: Session):
    """Verify force_outcome parameter is rejected with 403 in non-test environments."""
    old_env = os.environ.get("APP_ENV")
    try:
        os.environ["APP_ENV"] = "production"

        txn = Transaction(
            external_transaction_id=f"txn_prod_{uuid4().hex[:8]}",
            merchant_id="merchant_101",
            amount=Decimal("1999.00"),
            status=TransactionStatus.FAILED,
        )
        db_session.add(txn)
        db_session.commit()

        resp = client.post(
            "/api/v1/execution/actions/execute",
            headers={"X-API-Key": "merchant_101"},
            json={
                "transaction_id": str(txn.id),
                "action_type": "RETRY_SAME_METHOD",
                "force_outcome": "SUCCESS",
            },
        )
        assert resp.status_code == 403
        assert "force_outcome parameter is forbidden" in resp.json()["detail"]
    finally:
        if old_env:
            os.environ["APP_ENV"] = old_env
        else:
            os.environ["APP_ENV"] = "test"


def test_no_hardcoded_secrets_in_tracked_code():
    """Permanent regression guard: assert no .py file in repo contains literal API key patterns."""
    from pathlib import Path
    import re

    repo_root = Path(__file__).resolve().parent.parent.parent
    key_patterns = [
        re.compile(r"rzp_live_[a-zA-Z0-9]{14,}"),
        re.compile(r"rzp_test_[a-zA-Z0-9]{14,}"),
        re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
        re.compile(r"sk-[a-zA-Z0-9]{24,}"),
    ]

    py_files = list(repo_root.glob("**/*.py"))
    filtered = [
        p for p in py_files
        if ".venv" not in p.parts and ".tools" not in p.parts and ".git" not in p.parts
    ]

    violations = []
    current_file = Path(__file__).resolve()
    for file_path in filtered:
        if file_path == current_file:
            continue
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        for pat in key_patterns:
            matches = pat.findall(content)
            if matches:
                violations.append(f"{file_path.relative_to(repo_root)}: {matches}")

    assert not violations, f"Hardcoded API keys detected in tracked source code: {violations}"


def test_secrets_startup_validation_fails_fast():
    """Verify application startup fails fast with clear errors when required credentials are missing."""
    from backend.app.config import Settings
    from backend.app.main import validate_startup_secrets

    # 1. Live gateway missing keys
    bad_gw_settings = Settings(use_live_gateway=True, razorpay_key_id=None, razorpay_key_secret=None)
    with pytest.raises(RuntimeError) as exc:
        validate_startup_secrets(bad_gw_settings)
    assert "USE_LIVE_GATEWAY=true requires RAZORPAY_KEY_ID" in str(exc.value)

    # 2. LLM explanations enabled without Gemini key
    bad_llm_settings = Settings(use_llm_explanations=True, gemini_api_key=None)
    with pytest.raises(RuntimeError) as exc:
        validate_startup_secrets(bad_llm_settings)
    assert "USE_LLM_EXPLANATIONS=true requires GEMINI_API_KEY" in str(exc.value)

    # 3. Production environment without merchant API keys
    bad_prod_settings = Settings(app_env="production", merchant_api_keys={})
    with pytest.raises(RuntimeError) as exc:
        validate_startup_secrets(bad_prod_settings)
    assert "Production environment requires MERCHANT_API_KEYS" in str(exc.value)


