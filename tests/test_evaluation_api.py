"""REST API tests for Day 13 Evaluation & Business Proof endpoints."""

from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    Customer,
    FailureEvent,
    PaymentAttempt,
    Transaction,
    TransactionStatus,
)


def test_run_benchmark_api(client: TestClient):
    """Verify POST /api/v1/evaluation/run-benchmark endpoint."""
    payload = {
        "merchant_id": "merch_101",
        "num_transactions": 50,
        "seed": 42,
    }
    response = client.post("/api/v1/evaluation/run-benchmark", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["merchant_id"] == "merch_101"
    assert data["total_transactions"] == 50
    assert "strategies" in data
    assert "NO_ACTION" in data["strategies"]
    assert "BLIND_RETRY" in data["strategies"]
    assert "RULE_BASED_HEURISTIC" in data["strategies"]
    assert "RECOVERX_AI" in data["strategies"]

    ai_strat = data["strategies"]["RECOVERX_AI"]
    assert ai_strat["net_recovery_rate_pct"] > 60.0
    assert float(ai_strat["recovered_gmv"]) > 0
    assert float(data["incremental_gmv_vs_blind_retry"]) > 0
    assert float(data["recovery_rate_lift_pct_vs_blind"]) > 0
    assert len(data["category_breakdown"]) > 0


def test_get_business_proof_api(client: TestClient):
    """Verify GET /api/v1/evaluation/business-proof endpoint."""
    response = client.get("/api/v1/evaluation/business-proof?merchant_id=merch_101")
    assert response.status_code == 200
    data = response.json()

    assert data["merchant_id"] == "merch_101"
    assert float(data["recovered_gmv"]) > 0
    assert data["net_recovery_rate_pct"] > 50.0
    assert data["net_roi_multiplier"] > 5.0
    assert data["stopping_rules_compliance_pct"] == 100.0
    assert data["double_billing_prevention_rate_pct"] == 100.0
    assert len(data["key_findings"]) >= 3


def test_get_stopping_rules_api(client: TestClient):
    """Verify GET /api/v1/evaluation/stopping-rules endpoint."""
    response = client.get("/api/v1/evaluation/stopping-rules?merchant_id=merch_101")
    assert response.status_code == 200
    data = response.json()

    assert data["merchant_id"] == "merch_101"
    assert data["overall_compliance_pct"] == 100.0
    assert data["zero_violation_guarantee"] is True
    assert data["total_rules_audited"] == 6
    assert data["passed_rules_count"] == 6
    assert len(data["rules"]) == 6

    rule_codes = [r["rule_code"] for r in data["rules"]]
    assert "HARD_FAILURE_TERMINAL_STOP" in rule_codes
    assert "DOUBLE_BILLING_PREVENTION" in rule_codes
    assert "NEGATIVE_EV_ABORT" in rule_codes


def test_get_audit_trail_api(client: TestClient, db_session: Session):
    """Verify GET /api/v1/evaluation/audit-trail/{transaction_id} endpoint."""
    cust = Customer(
        external_customer_id="cust_ananya_001",
        name="Ananya Sharma",
        email="ananya.sharma@example.com",
        phone="+919876543211",
        merchant_id="merch_101",
    )
    db_session.add(cust)
    db_session.flush()

    txn = Transaction(
        external_transaction_id="txn_api_audit_test_001",
        merchant_id="merch_101",
        customer_id=cust.id,
        amount=Decimal("3499.00"),
        currency="INR",
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()

    att = PaymentAttempt(
        transaction_id=txn.id,
        attempt_number=1,
        payment_method="UPI",
        gateway="NPCI_UPI",
        failure_code="GATEWAY_TIMEOUT",
    )
    db_session.add(att)
    db_session.flush()

    fail = FailureEvent(
        source_event_id="evt_api_eval_audit_001",
        transaction_id=txn.id,
        attempt_id=att.id,
        category="TEMPORARY",
        failure_code="GATEWAY_TIMEOUT",
        recoverable=True,
    )
    db_session.add(fail)
    db_session.commit()

    response = client.get(f"/api/v1/evaluation/audit-trail/{txn.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["transaction_id"] == str(txn.id)
    assert data["external_transaction_id"] == "txn_api_audit_test_001"
    assert data["integrity_verified"] is True
    assert len(data["events"]) >= 3
    assert data["events"][0]["stage"] == "TRANSACTION_INGESTION"


def test_get_audit_trail_not_found(client: TestClient):
    """Verify GET /api/v1/evaluation/audit-trail/{transaction_id} returns 404 for unknown transaction."""
    response = client.get("/api/v1/evaluation/audit-trail/non_existent_uuid_404")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_batch_simulate_api(client: TestClient):
    """Verify POST /api/v1/evaluation/batch-simulate endpoint."""
    payload = {
        "merchant_id": "merch_101",
        "num_transactions": 25,
        "seed": 77,
    }
    response = client.post("/api/v1/evaluation/batch-simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["total_transactions"] == 25
    assert "RECOVERX_AI" in data["strategies"]
