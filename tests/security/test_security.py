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

