"""Unit and integration tests for PaymentRecoveryAgent autonomous investigation."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    Customer,
    CustomerIntelligence,
    OutboxEvent,
    PaymentAttempt,
    Transaction,
    TransactionStatus,
)
from backend.app.services.recovery_agent import payment_recovery_agent


def test_agent_investigate_card_decline_flow(db_session: Session) -> None:
    """Test full multi-step investigation on a recoverable CARD_DECLINED failure."""
    customer = Customer(
        external_customer_id=f"cust_agent_{uuid4().hex[:6]}",
        merchant_id="merch_101",
        name="Ananya Roy",
        email="ananya.roy@example.com",
        phone="+919876543210",
        preferred_payment_method="UPI",
        risk_segment="STANDARD",
    )
    db_session.add(customer)
    db_session.flush()

    txn = Transaction(
        external_transaction_id=f"txn_agent_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        customer_id=customer.id,
        amount=Decimal("4999.00"),
        currency="INR",
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()

    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            gateway="RAZORPAY",
            failure_code="CARD_DECLINED",
        )
    )
    db_session.commit()

    resp = payment_recovery_agent.investigate_transaction(
        session=db_session,
        transaction_id=txn.id,
    )

    assert resp.status == "COMPLETED"
    assert resp.failure_category == "PAYMENT_METHOD"
    assert resp.failure_code == "CARD_DECLINED"
    assert resp.chosen_action in ("SWITCH_TO_UPI", "PAYMENT_LINK", "SWITCH_TO_NETBANKING")
    assert resp.expected_value > 0.0
    assert resp.predicted_probability > 0.0
    assert resp.execution_disposition in ("APPROVED", "QUEUED")
    assert resp.recovery_plan is not None
    assert resp.recovery_plan.chosen_action == resp.chosen_action
    assert len(resp.steps) >= 5
    assert len(resp.audit_records) >= 1
    assert resp.total_duration_ms > 0.0

    # Verify Outbox Event was emitted
    outbox = db_session.scalars(
        select(OutboxEvent).where(
            OutboxEvent.event_type == "recovery.agent_investigated.v1",
            OutboxEvent.aggregate_id == str(txn.id),
        )
    ).first()
    assert outbox is not None
    assert outbox.payload["chosen_action"] == resp.chosen_action


def test_agent_investigate_hard_failure_terminal_stop(db_session: Session) -> None:
    """Test agent investigation enforces immediate STOP_RECOVERY on HARD_FAILURE."""
    txn = Transaction(
        external_transaction_id=f"txn_fraud_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        amount=Decimal("12000.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()

    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            failure_code="FRAUD_REJECTED",
        )
    )
    db_session.commit()

    resp = payment_recovery_agent.investigate_transaction(
        session=db_session,
        transaction_id=txn.id,
    )

    assert resp.status == "STOPPED"
    assert resp.failure_category == "HARD_FAILURE"
    assert resp.failure_code == "FRAUD_REJECTED"
    assert resp.chosen_action == "STOP_RECOVERY"
    assert resp.expected_value == 0.0
    assert resp.predicted_probability == 0.0
    assert resp.execution_disposition == "APPROVED"
    assert "compliance" in (resp.compliance_notes or "").lower() or "stop" in (resp.compliance_notes or "").lower()


def test_agent_investigate_temporary_network_timeout(db_session: Session) -> None:
    """Test agent investigation schedules backoff on TEMPORARY TIMEOUT failure."""
    txn = Transaction(
        external_transaction_id=f"txn_timeout_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        amount=Decimal("1800.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()

    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="UPI",
            failure_code="TIMEOUT",
        )
    )
    db_session.commit()

    resp = payment_recovery_agent.investigate_transaction(
        session=db_session,
        transaction_id=txn.id,
    )

    assert resp.status == "COMPLETED"
    assert resp.failure_category == "TEMPORARY"
    assert resp.chosen_action in ("DELAYED_RETRY", "SWITCH_TO_UPI", "RETRY_SAME_METHOD")
    assert resp.expected_value > 0.0


def test_agent_investigate_customer_action_otp_timeout(db_session: Session) -> None:
    """Test agent investigation on CUSTOMER_ACTION OTP_TIMEOUT selects notification or link."""
    txn = Transaction(
        external_transaction_id=f"txn_otp_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        amount=Decimal("3200.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()

    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            failure_code="OTP_TIMEOUT",
        )
    )
    db_session.commit()

    resp = payment_recovery_agent.investigate_transaction(
        session=db_session,
        transaction_id=txn.id,
    )

    assert resp.status == "COMPLETED"
    assert resp.failure_category == "CUSTOMER_ACTION"
    assert resp.chosen_action in ("CUSTOMER_NOTIFICATION", "PAYMENT_LINK", "SWITCH_TO_UPI")
    assert resp.expected_value > 0.0


def test_agent_investigate_non_existent_transaction_returns_needs_review(db_session: Session) -> None:
    """Test agent safely handles missing transaction by returning NEEDS_REVIEW."""
    fake_id = uuid4()
    resp = payment_recovery_agent.investigate_transaction(
        session=db_session,
        transaction_id=fake_id,
    )

    assert resp.status == "NEEDS_REVIEW"
    assert resp.chosen_action == "STOP_RECOVERY"
    assert "not found" in resp.merchant_explanation or "unavailable" in resp.merchant_explanation
