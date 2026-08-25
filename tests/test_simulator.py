"""Unit and integration tests for the Payment Simulator."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.app.models.recovery import (
    AuditLog,
    FailureEvent,
    OutboxEvent,
    PaymentAttempt,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.simulator import (
    CreateSimulatedPaymentRequest,
    SimulateAttemptRequest,
    SimulateBatchRequest,
)
from backend.app.simulator.constants import SimulationScenario
from backend.app.simulator.engine import PaymentSimulator


def test_deterministic_successful_payment_simulation(db_session) -> None:
    simulator = PaymentSimulator(db_session)
    request = CreateSimulatedPaymentRequest(
        amount=Decimal("1499.00"),
        merchant_id="merch_test_101",
        payment_method="UPI",
        gateway="RAZORPAY",
        target_outcome="SUCCESS",
    )

    result = simulator.simulate_payment(request)

    assert result.outcome == "SUCCESS"
    assert result.status == "SUCCEEDED"
    assert result.amount == Decimal("1499.00")
    assert result.payment_method == "UPI"
    assert result.gateway == "RAZORPAY"
    assert result.attempt_number == 1
    assert result.failure_code is None
    assert result.outbox_event_id is not None

    # Verify DB persistence
    txn = db_session.scalar(select(Transaction).where(Transaction.id == result.transaction_id))
    assert txn is not None
    assert txn.status == TransactionStatus.SUCCEEDED
    assert txn.amount == Decimal("1499.00")

    attempt = db_session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.transaction_id == txn.id)
    )
    assert attempt is not None
    assert attempt.attempt_number == 1
    assert attempt.payment_method == "UPI"

    # Verify audit log & outbox event
    audit = db_session.scalar(select(AuditLog).where(AuditLog.transaction_id == txn.id))
    assert audit is not None
    assert audit.event_type == "payment.succeeded.v1"
    assert audit.actor == "payment_simulator"

    outbox = db_session.scalar(select(OutboxEvent).where(OutboxEvent.id == result.outbox_event_id))
    assert outbox is not None
    assert outbox.event_type == "payment.succeeded.v1"


def test_deterministic_failure_payment_simulation(db_session) -> None:
    simulator = PaymentSimulator(db_session)
    request = CreateSimulatedPaymentRequest(
        amount=Decimal("4999.00"),
        merchant_id="merch_test_card",
        payment_method="CARD",
        gateway="HDFC_SMARTHUB",
        target_outcome="FAIL",
        target_failure_code="CARD_DECLINED",
    )

    result = simulator.simulate_payment(request)

    assert result.outcome == "FAIL"
    assert result.status == "FAILED"
    assert result.failure_code == "CARD_DECLINED"
    assert result.failure_category == "PAYMENT_METHOD"
    assert result.recoverable is True
    assert result.error_message is not None

    # Verify FailureEvent in DB
    failure = db_session.scalar(
        select(FailureEvent).where(FailureEvent.transaction_id == result.transaction_id)
    )
    assert failure is not None
    assert failure.failure_code == "CARD_DECLINED"
    assert failure.category == "PAYMENT_METHOD"
    assert failure.recoverable is True

    # Verify AuditLog & OutboxEvent
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.transaction_id == result.transaction_id)
    )
    assert audit is not None
    assert audit.event_type == "payment.failed.v1"
    assert "ALTERNATE_METHOD_PREFERRED" in audit.reason_codes

    outbox = db_session.scalar(
        select(OutboxEvent).where(OutboxEvent.id == result.outbox_event_id)
    )
    assert outbox is not None
    assert outbox.event_type == "payment.failed.v1"
    assert outbox.payload["failure_code"] == "CARD_DECLINED"


def test_hard_failure_simulation(db_session) -> None:
    simulator = PaymentSimulator(db_session)
    request = CreateSimulatedPaymentRequest(
        amount=Decimal("999.00"),
        target_failure_code="BLOCKED_CARD",
    )

    result = simulator.simulate_payment(request)

    assert result.outcome == "FAIL"
    assert result.failure_code == "BLOCKED_CARD"
    assert result.failure_category == "HARD_FAILURE"
    assert result.recoverable is False


def test_multi_attempt_lifecycle_retry_to_success(db_session) -> None:
    simulator = PaymentSimulator(db_session)

    # Attempt 1: Fails with CARD_DECLINED
    req1 = CreateSimulatedPaymentRequest(
        amount=Decimal("2499.00"),
        payment_method="CARD",
        target_failure_code="CARD_DECLINED",
    )
    res1 = simulator.simulate_payment(req1)
    assert res1.status == "FAILED"
    assert res1.attempt_number == 1

    # Attempt 2: Switch to UPI and succeed
    req2 = SimulateAttemptRequest(
        payment_method="UPI",
        target_outcome="SUCCESS",
    )
    res2 = simulator.simulate_attempt(res1.transaction_id, req2)

    assert res2.outcome == "SUCCESS"
    assert res2.status == "SUCCEEDED"
    assert res2.attempt_number == 2
    assert res2.payment_method == "UPI"

    # Verify transaction now SUCCEEDED in DB with 2 attempts
    txn = db_session.scalar(select(Transaction).where(Transaction.id == res1.transaction_id))
    assert txn.status == TransactionStatus.SUCCEEDED
    assert len(txn.attempts) == 2
    assert txn.attempts[0].payment_method == "CARD"
    assert txn.attempts[0].failure_code == "CARD_DECLINED"
    assert txn.attempts[1].payment_method == "UPI"
    assert txn.attempts[1].failure_code is None


def test_cannot_attempt_already_succeeded_transaction(db_session) -> None:
    simulator = PaymentSimulator(db_session)
    req = CreateSimulatedPaymentRequest(target_outcome="SUCCESS")
    res = simulator.simulate_payment(req)

    with pytest.raises(ValueError, match="already SUCCEEDED"):
        simulator.simulate_attempt(res.transaction_id, SimulateAttemptRequest(target_outcome="SUCCESS"))


def test_batch_simulation(db_session) -> None:
    simulator = PaymentSimulator(db_session)
    req = SimulateBatchRequest(
        count=15,
        scenario=SimulationScenario.NORMAL_BALANCED,
        success_rate_override=0.60,
    )
    res = simulator.simulate_batch(req)

    assert res.total_simulated == 15
    assert res.success_count + res.failure_count == 15
    assert len(res.transactions) == 15
    assert res.total_amount > Decimal("0.00")
    if res.failure_count > 0:
        assert len(res.failure_code_breakdown) > 0


def test_simulator_api_endpoints(client) -> None:
    # 1. Create simulated payment
    resp = client.post(
        "/api/v1/simulator/payments",
        json={
            "amount": "1250.00",
            "merchant_id": "merch_api_test",
            "payment_method": "CARD",
            "target_outcome": "FAIL",
            "target_failure_code": "OTP_TIMEOUT",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "FAILED"
    assert data["failure_code"] == "OTP_TIMEOUT"
    assert data["failure_category"] == "CUSTOMER_ACTION"
    txn_id = data["transaction_id"]

    # 2. Simulate second attempt
    resp_attempt = client.post(
        f"/api/v1/simulator/payments/{txn_id}/attempts",
        json={
            "payment_method": "UPI",
            "target_outcome": "SUCCESS",
        },
    )
    assert resp_attempt.status_code == 200
    attempt_data = resp_attempt.json()
    assert attempt_data["status"] == "SUCCEEDED"
    assert attempt_data["attempt_number"] == 2

    # 3. Simulate batch
    resp_batch = client.post(
        "/api/v1/simulator/batch",
        json={
            "count": 5,
            "scenario": "UPI_OUTAGE",
        },
    )
    assert resp_batch.status_code == 201
    batch_data = resp_batch.json()
    assert batch_data["total_simulated"] == 5

    # 4. Get scenarios info
    resp_scenarios = client.get("/api/v1/simulator/scenarios")
    assert resp_scenarios.status_code == 200
    scenarios_data = resp_scenarios.json()
    assert len(scenarios_data["scenarios"]) >= 6
    assert len(scenarios_data["failure_codes"]) >= 10
    assert "UPI" in scenarios_data["payment_methods"]
    assert "RAZORPAY" in scenarios_data["gateways"]
