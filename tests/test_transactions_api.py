"""Integration tests for transaction query and lifecycle API endpoints."""

from uuid import uuid4

from backend.app.schemas.simulator import CreateSimulatedPaymentRequest
from backend.app.simulator.engine import PaymentSimulator


def test_transactions_list_and_filter_api(client, db_session) -> None:
    simulator = PaymentSimulator(db_session)

    # Seed 3 transactions
    simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id="merchant_list_test",
            payment_method="UPI",
            target_outcome="SUCCESS",
        )
    )
    simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id="merchant_list_test",
            payment_method="CARD",
            target_outcome="FAIL",
            target_failure_code="CARD_DECLINED",
        )
    )
    simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id="merchant_other",
            payment_method="UPI",
            target_outcome="SUCCESS",
        )
    )

    # Test list without filters
    resp = client.get("/api/v1/transactions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3
    assert len(data["items"]) >= 3

    # Test merchant filter
    resp_filtered = client.get("/api/v1/transactions?merchant_id=merchant_list_test")
    assert resp_filtered.status_code == 200
    filtered_data = resp_filtered.json()
    assert filtered_data["total"] == 2
    assert all(item["merchant_id"] == "merchant_list_test" for item in filtered_data["items"])

    # Test status filter
    resp_failed = client.get("/api/v1/transactions?status=FAILED")
    assert resp_failed.status_code == 200
    failed_data = resp_failed.json()
    assert all(item["status"] == "FAILED" for item in failed_data["items"])


def test_transaction_detail_api(client, db_session) -> None:
    simulator = PaymentSimulator(db_session)
    res = simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id="merch_detail_test",
            payment_method="CARD",
            target_outcome="FAIL",
            target_failure_code="OTP_TIMEOUT",
        )
    )

    resp = client.get(f"/api/v1/transactions/{res.transaction_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(res.transaction_id)
    assert data["merchant_id"] == "merch_detail_test"
    assert data["status"] == "FAILED"
    assert data["attempts_count"] == 1
    assert len(data["attempts"]) == 1
    assert data["attempts"][0]["failure_code"] == "OTP_TIMEOUT"
    assert len(data["attempts"][0]["failures"]) == 1
    assert data["attempts"][0]["failures"][0]["category"] == "CUSTOMER_ACTION"


def test_transaction_detail_404(client) -> None:
    random_id = uuid4()
    resp = client.get(f"/api/v1/transactions/{random_id}")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()
