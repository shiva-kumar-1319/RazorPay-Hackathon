"""API integration tests for /api/v1/execution endpoints."""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.schemas.simulator import CreateSimulatedPaymentRequest
from backend.app.simulator.engine import PaymentSimulator


@pytest.fixture
def seeded_failed_txn_id(db_session: Session) -> str:
    """Fixture to seed a failed transaction in the test DB and return its UUID."""
    sim = PaymentSimulator(db_session)
    req = CreateSimulatedPaymentRequest(
        amount=Decimal("3499.00"),
        payment_method="CARD",
        target_outcome="FAIL",
        target_failure_code="CARD_DECLINED",
    )
    res = sim.simulate_payment(req)
    return str(res.transaction_id)


def test_api_execute_action_switch_upi(client: TestClient, seeded_failed_txn_id: str):
    """Test POST /api/v1/execution/actions/execute with SWITCH_TO_UPI."""
    payload = {
        "transaction_id": seeded_failed_txn_id,
        "action_type": "SWITCH_TO_UPI",
        "force_outcome": "SUCCESS",
    }
    response = client.post("/api/v1/execution/actions/execute", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "SUCCEEDED"
    assert data["disposition"] == "COMPLETED"
    assert data["action_type"] == "SWITCH_TO_UPI"
    assert data["new_payment_method"] == "UPI"
    assert data["attempt_number"] == 2


def test_api_execute_action_double_recovery_refused(client: TestClient, seeded_failed_txn_id: str):
    """Test executing recovery on already-succeeded transaction returns REFUSED."""
    # First execution succeeds
    client.post(
        "/api/v1/execution/actions/execute",
        json={"transaction_id": seeded_failed_txn_id, "action_type": "SWITCH_TO_UPI", "force_outcome": "SUCCESS"},
    )

    # Second execution is refused
    res2 = client.post(
        "/api/v1/execution/actions/execute",
        json={"transaction_id": seeded_failed_txn_id, "action_type": "RETRY_SAME_METHOD"},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["disposition"] == "REFUSED"
    assert data2["status"] == "REFUSED"
    assert "already SUCCEEDED" in data2["message"]


def test_api_scheduler_run_due(client: TestClient, seeded_failed_txn_id: str):
    """Test POST /api/v1/execution/scheduler/run-due."""
    # Schedule a delayed retry
    client.post(
        "/api/v1/execution/actions/execute",
        json={"transaction_id": seeded_failed_txn_id, "action_type": "DELAYED_RETRY", "parameters": {"delay_seconds": 5}},
    )

    # Run due scheduler
    sched_resp = client.post(
        "/api/v1/execution/scheduler/run-due",
        json={"limit": 10, "force_now": True},
    )
    assert sched_resp.status_code == 200
    sched_data = sched_resp.json()
    assert "processed_count" in sched_data
    assert "executions" in sched_data


def test_api_customer_link_flow(client: TestClient, seeded_failed_txn_id: str):
    """Test customer payment link creation, public checkout view, and payment completion."""
    # 1. Create Link
    create_resp = client.post(
        "/api/v1/execution/customer/create-link",
        json={
            "transaction_id": seeded_failed_txn_id,
            "channel": "WHATSAPP",
            "expires_in_minutes": 30,
        },
    )
    assert create_resp.status_code == 200
    link_data = create_resp.json()
    token = link_data["token"]
    assert token.startswith("rec_")
    assert link_data["channel"] == "WHATSAPP"

    # 2. View Checkout
    view_resp = client.get(f"/api/v1/execution/customer/link/{token}")
    assert view_resp.status_code == 200
    view_data = view_resp.json()
    assert view_data["token"] == token
    assert float(view_data["amount"]) == 3499.00
    assert view_data["is_expired"] is False

    # 3. Pay Checkout
    pay_resp = client.post(
        f"/api/v1/execution/customer/link/{token}/pay",
        json={
            "payment_method": "UPI",
            "simulate_outcome": "SUCCESS",
        },
    )
    assert pay_resp.status_code == 200
    pay_data = pay_resp.json()
    assert pay_data["success"] is True
    assert pay_data["status"] == "SUCCEEDED"
    assert pay_data["payment_method"] == "UPI"


def test_api_customer_checkout_not_found(client: TestClient):
    """Test non-existent recovery link token returns 404."""
    resp = client.get("/api/v1/execution/customer/link/rec_invalid_token_12345")
    assert resp.status_code == 404


def test_api_execution_metrics(client: TestClient, seeded_failed_txn_id: str):
    """Test GET /api/v1/execution/metrics returns aggregate KPI response."""
    # Execute an action first
    client.post(
        "/api/v1/execution/actions/execute",
        json={"transaction_id": seeded_failed_txn_id, "action_type": "SWITCH_TO_UPI", "force_outcome": "SUCCESS"},
    )

    resp = client.get("/api/v1/execution/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_executions" in data
    assert "successful_executions" in data
    assert "overall_recovery_rate" in data
    assert "by_workflow" in data
