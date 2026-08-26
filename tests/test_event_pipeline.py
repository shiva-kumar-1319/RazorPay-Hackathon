"""Integration tests for Day 5 Real-Time Event Pipeline & Recovery APIs."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.recovery import OutboxEvent, RecoveryCase, RecoveryState
from backend.app.services.outbox_publisher import outbox_publisher
from backend.app.services.recovery_service import recovery_orchestrator
from backend.app.worker import run_worker_pass


def test_full_pipeline_simulator_to_recovery_case(client: TestClient, db_session: Session):
    # 1. Simulate a payment failure via Simulator API
    sim_res = client.post(
        "/api/v1/simulator/payments",
        json={
            "merchant_id": "merch_pipeline_test",
            "amount": 4999.00,
            "currency": "INR",
            "payment_method": "CARD",
            "gateway": "RAZORPAY",
            "target_outcome": "FAIL",
            "target_failure_code": "CARD_DECLINED",
        },
    )
    assert sim_res.status_code == 201
    sim_data = sim_res.json()
    txn_id = sim_data["transaction_id"]

    # 2. Verify outbox event was generated and is pending
    status_res = client.get("/api/v1/recovery/pipeline/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["outbox_pending_count"] >= 1

    # 3. Trigger outbox processing
    proc_res = client.post("/api/v1/recovery/pipeline/process")
    assert proc_res.status_code == 200
    proc_data = proc_res.json()
    assert proc_data["outbox_published"] >= 1

    # 4. Query recovery cases API
    cases_res = client.get("/api/v1/recovery/cases", params={"merchant_id": "merch_pipeline_test"})
    assert cases_res.status_code == 200
    cases_data = cases_res.json()
    assert cases_data["total"] >= 1

    found_case = next((c for c in cases_data["items"] if c["transaction_id"] == txn_id), None)
    assert found_case is not None
    assert found_case["state"] == "OPEN"
    assert len(found_case["actions"]) >= 1

    # 5. Query detailed single recovery case API
    case_id = found_case["id"]
    detail_res = client.get(f"/api/v1/recovery/cases/{case_id}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["id"] == case_id
    assert detail_data["transaction_status"] == "FAILED"
    assert detail_data["latest_failure_code"] == "CARD_DECLINED"
    assert len(detail_data["audit_trail"]) >= 1


def test_pipeline_publish_endpoint(client: TestClient, db_session: Session):
    # Simulate payment failure
    client.post(
        "/api/v1/simulator/payments",
        json={
            "merchant_id": "merch_pub_test",
            "amount": 2500.00,
            "currency": "INR",
            "payment_method": "UPI",
            "gateway": "PHONEPE",
            "target_outcome": "FAIL",
            "target_failure_code": "OTP_TIMEOUT",
        },
    )

    # Publish via dedicated endpoint
    res = client.post("/api/v1/recovery/pipeline/publish", params={"limit": 50})
    assert res.status_code == 200
    data = res.json()
    assert data["published_count"] >= 1
    assert data["failed_count"] == 0


def test_worker_run_pass(db_session: Session):
    published, failed = run_worker_pass(limit=10)
    assert failed == 0


def test_pipeline_status_endpoint(client: TestClient):
    res = client.get("/api/v1/recovery/pipeline/status")
    assert res.status_code == 200
    data = res.json()
    assert "outbox_pending_count" in data
    assert "outbox_published_count" in data
    assert "processed_events_count" in data
    assert "quarantine_events_count" in data
    assert "pipeline_healthy" in data


def test_recovery_case_filters(client: TestClient, db_session: Session):
    # Simulate a hard failure and process it
    client.post(
        "/api/v1/simulator/payments",
        json={
            "merchant_id": "merch_filter_test",
            "amount": 10000.00,
            "currency": "INR",
            "payment_method": "CARD",
            "gateway": "RAZORPAY",
            "target_outcome": "FAIL",
            "target_failure_code": "FRAUD_REJECTED",
        },
    )
    client.post("/api/v1/recovery/pipeline/process")

    # Filter by state=STOPPED
    res = client.get("/api/v1/recovery/cases", params={"state": "STOPPED"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    for item in data["items"]:
        assert item["state"] == "STOPPED"


def test_recovery_case_404(client: TestClient):
    res = client.get("/api/v1/recovery/cases/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404
