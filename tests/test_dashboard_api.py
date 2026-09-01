"""Integration tests for Dashboard API endpoints and web client routes."""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    ActionType,
    Customer,
    RecoveryAction,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.simulator import CreateSimulatedPaymentRequest
from backend.app.simulator.engine import PaymentSimulator


def test_dashboard_html_page_routes(client: TestClient):
    """Verify GET / and GET /dashboard render the HTML dashboard application."""
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "RecoverX" in res_root.text
    assert "Live Failed Payments" in res_root.text

    res_dash = client.get("/dashboard")
    assert res_dash.status_code == 200
    assert "RecoverX" in res_dash.text


def test_dashboard_overview_api(client: TestClient, db_session: Session):
    """Verify GET /api/v1/dashboard/overview returns structured KPIs."""
    merchant_id = f"merch_api_{uuid4().hex[:6]}"
    simulator = PaymentSimulator(db_session)
    
    # Simulate a failed payment
    simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id=merchant_id,
            amount=Decimal("4999.00"),
            currency="INR",
            payment_method="CARD",
            target_outcome="FAIL",
            target_failure_code="CARD_DECLINED",
        )
    )

    res = client.get(f"/api/v1/dashboard/overview?merchant_id={merchant_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["merchant_id"] == merchant_id
    assert data["currency"] == "INR"
    assert "total_failed_gmv" in data
    assert "total_recovered_gmv" in data
    assert "recovery_rate_pct" in data
    assert "hourly_trends" in data
    assert "action_breakdown" in data
    assert "category_breakdown" in data


def test_dashboard_funnel_api(client: TestClient, db_session: Session):
    """Verify GET /api/v1/dashboard/funnel returns 4-stage funnel and segmentation."""
    merchant_id = f"merch_funnel_api_{uuid4().hex[:6]}"
    simulator = PaymentSimulator(db_session)
    
    simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id=merchant_id,
            amount=Decimal("2500.00"),
            currency="INR",
            payment_method="UPI",
            target_outcome="FAIL",
            target_failure_code="TIMEOUT",
        )
    )

    res = client.get(f"/api/v1/dashboard/funnel?merchant_id={merchant_id}")
    assert res.status_code == 200
    data = res.json()
    assert len(data["stages"]) == 4
    assert "category_funnels" in data
    assert "method_conversion_matrix" in data


def test_dashboard_live_failed_payments_api(client: TestClient, db_session: Session):
    """Verify GET /api/v1/dashboard/live-failed-payments returns paginated feed."""
    merchant_id = f"merch_live_api_{uuid4().hex[:6]}"
    simulator = PaymentSimulator(db_session)

    simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id=merchant_id,
            amount=Decimal("7500.00"),
            currency="INR",
            payment_method="CARD",
            target_outcome="FAIL",
            target_failure_code="3DS_FAILURE",
        )
    )

    res = client.get(f"/api/v1/dashboard/live-failed-payments?merchant_id={merchant_id}&limit=10")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1
    item = data["items"][0]
    assert item["failure_code"] == "3DS_FAILURE"
    assert item["failure_category"] == "CUSTOMER_ACTION"


def test_dashboard_agent_decisions_api(client: TestClient, db_session: Session):
    """Verify GET /api/v1/dashboard/agent-decisions returns decision ledger."""
    merchant_id = f"merch_agent_api_{uuid4().hex[:6]}"
    simulator = PaymentSimulator(db_session)

    sim = simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id=merchant_id,
            amount=Decimal("3500.00"),
            currency="INR",
            payment_method="CARD",
            target_outcome="FAIL",
            target_failure_code="CARD_DECLINED",
        )
    )
    txn_id = sim.transaction_id

    case = RecoveryCase(
        transaction_id=txn_id,
        state=RecoveryState.RECOVERED,
        policy_version="v1.0",
    )
    db_session.add(case)
    db_session.flush()

    act = RecoveryAction(
        recovery_case_id=case.id,
        action_type=ActionType.SWITCH_TO_UPI,
        idempotency_key=f"idemp_api_{uuid4().hex}",
        selected=True,
        probability=Decimal("0.8800"),
        expected_value=Decimal("3080.00"),
        status="COMPLETED",
    )
    db_session.add(act)
    db_session.commit()

    res = client.get(f"/api/v1/dashboard/agent-decisions?merchant_id={merchant_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["selected_action"] == "SWITCH_TO_UPI"
    assert item["decision_status"] == "RECOVERED"


def test_dashboard_recovery_attempts_api(client: TestClient, db_session: Session):
    """Verify GET /api/v1/dashboard/recovery-attempts returns workflow executions."""
    merchant_id = f"merch_att_api_{uuid4().hex[:6]}"
    simulator = PaymentSimulator(db_session)

    sim = simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id=merchant_id,
            amount=Decimal("1200.00"),
            currency="INR",
            payment_method="UPI",
            target_outcome="FAIL",
            target_failure_code="TIMEOUT",
        )
    )
    txn_id = sim.transaction_id

    case = RecoveryCase(
        transaction_id=txn_id,
        state=RecoveryState.OPEN,
        policy_version="v1.0",
    )
    db_session.add(case)
    db_session.flush()

    act = RecoveryAction(
        recovery_case_id=case.id,
        action_type=ActionType.RETRY_SAME_METHOD,
        idempotency_key=f"idemp_retry_{uuid4().hex}",
        selected=True,
        probability=Decimal("0.6500"),
        expected_value=Decimal("780.00"),
        status="COMPLETED",
    )
    db_session.add(act)
    db_session.commit()

    res = client.get(f"/api/v1/dashboard/recovery-attempts?merchant_id={merchant_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert data["items"][0]["workflow_type"] == "IMMEDIATE_RETRY"


def test_dashboard_model_health_api(client: TestClient):
    """Verify GET /api/v1/dashboard/model-health returns ML diagnostics."""
    res = client.get("/api/v1/dashboard/model-health?merchant_id=merch_101")
    assert res.status_code == 200
    data = res.json()
    assert data["auc_roc"] > 0.8
    assert "feature_importances" in data
    assert "score_distribution" in data


def test_dashboard_simulate_live_batch_api(client: TestClient):
    """Verify POST /api/v1/dashboard/simulate-live-batch triggers live batch execution."""
    res = client.post(
        "/api/v1/dashboard/simulate-live-batch",
        json={
            "merchant_id": "merch_batch_test",
            "count": 3,
            "auto_investigate": True,
            "auto_execute": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["merchant_id"] == "merch_batch_test"
    assert data["generated_count"] == 3
    assert data["investigated_count"] == 3
    assert len(data["summary_messages"]) >= 3
