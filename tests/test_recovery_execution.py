"""Unit and integration tests for Day 11 Recovery Execution Engine."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    ActionType,
    AuditLog,
    Customer,
    CustomerRecoverySession,
    OutboxEvent,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.simulator import CreateSimulatedPaymentRequest
from backend.app.services.recovery_execution import recovery_execution_engine
from backend.app.simulator.engine import PaymentSimulator


def _seed_failed_txn(
    db_session: Session,
    failure_code: str = "CARD_DECLINED",
    method: str = "CARD",
    amount: Decimal = Decimal("2999.00"),
) -> Transaction:
    """Helper to seed a simulated failed payment transaction."""
    sim = PaymentSimulator(db_session)
    req = CreateSimulatedPaymentRequest(
        amount=amount,
        payment_method=method,
        target_outcome="FAIL",
        target_failure_code=failure_code,
    )
    res = sim.simulate_payment(req)
    return db_session.scalar(select(Transaction).where(Transaction.id == res.transaction_id))


def test_execute_immediate_retry_success(db_session: Session):
    """Test RETRY_SAME_METHOD workflow recovers transient network failures."""
    txn = _seed_failed_txn(db_session, failure_code="NETWORK_ERROR", method="UPI", amount=Decimal("1500.00"))

    res = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="RETRY_SAME_METHOD",
        force_outcome="SUCCESS",
    )

    assert res.status == "SUCCEEDED"
    assert res.disposition == "COMPLETED"
    assert res.attempt_number == 2
    assert res.new_payment_method == "UPI"
    assert res.guard_checks["not_already_succeeded"] is True

    # DB state checks
    db_session.refresh(txn)
    assert txn.status == TransactionStatus.SUCCEEDED
    assert len(txn.attempts) == 2

    recovery_case = db_session.scalar(select(RecoveryCase).where(RecoveryCase.transaction_id == txn.id))
    assert recovery_case is not None
    assert recovery_case.state == RecoveryState.RECOVERED

    # Audit log check
    audit = db_session.scalar(
        select(AuditLog)
        .where(AuditLog.transaction_id == txn.id, AuditLog.event_type == "recovery.executed.v1")
    )
    assert audit is not None
    assert "IMMEDIATE_RETRY_SUCCESS" in audit.reason_codes


def test_execute_immediate_retry_failure(db_session: Session):
    """Test RETRY_SAME_METHOD handles attempt failure and updates attempt count."""
    txn = _seed_failed_txn(db_session, failure_code="TIMEOUT", method="CARD", amount=Decimal("999.00"))

    res = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="RETRY_SAME_METHOD",
        force_outcome="FAIL",
    )

    assert res.status == "FAILED"
    assert res.attempt_number == 2
    assert res.disposition == "COMPLETED"

    db_session.refresh(txn)
    assert txn.status == TransactionStatus.FAILED
    assert len(txn.attempts) == 2


def test_execute_switch_to_upi_success(db_session: Session):
    """Test SWITCH_TO_UPI workflow bypasses card decline and recovers with UPI."""
    txn = _seed_failed_txn(db_session, failure_code="CARD_DECLINED", method="CARD", amount=Decimal("4999.00"))

    res = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="SWITCH_TO_UPI",
        force_outcome="SUCCESS",
        parameters={"vpa": "priya@okhdfcbank"},
    )

    assert res.status == "SUCCEEDED"
    assert res.action_type == "SWITCH_TO_UPI"
    assert res.new_payment_method == "UPI"
    assert res.attempt_number == 2

    db_session.refresh(txn)
    assert txn.status == TransactionStatus.SUCCEEDED
    assert txn.attempts[1].payment_method == "UPI"

    recovery_case = db_session.scalar(select(RecoveryCase).where(RecoveryCase.transaction_id == txn.id))
    assert recovery_case.state == RecoveryState.RECOVERED


def test_execute_switch_to_netbanking(db_session: Session):
    """Test SWITCH_TO_NETBANKING creates netbanking attempt and recovers."""
    txn = _seed_failed_txn(db_session, failure_code="CARD_DECLINED", method="CARD", amount=Decimal("7500.00"))

    res = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="SWITCH_TO_NETBANKING",
        force_outcome="SUCCESS",
    )

    assert res.status == "SUCCEEDED"
    assert res.new_payment_method == "NETBANKING"
    assert res.attempt_number == 2


def test_schedule_delayed_retry_and_due_execution(db_session: Session):
    """Test DELAYED_RETRY schedules backoff and executes when due."""
    txn = _seed_failed_txn(db_session, failure_code="BANK_SERVER_DOWN", method="UPI", amount=Decimal("3200.00"))

    # 1. Schedule delayed retry
    sched_res = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="DELAYED_RETRY",
        parameters={"delay_seconds": 10},
    )

    assert sched_res.status == "SCHEDULED"
    assert sched_res.disposition == "QUEUED"
    assert sched_res.scheduled_at is not None

    db_session.refresh(txn)
    recovery_case = db_session.scalar(select(RecoveryCase).where(RecoveryCase.transaction_id == txn.id))
    assert recovery_case.state == RecoveryState.SCHEDULED

    action = db_session.scalar(
        select(RecoveryAction).where(RecoveryAction.recovery_case_id == recovery_case.id)
    )
    assert action.status == "SCHEDULED"

    # 2. Execute due scheduled retries with force_now=True and force_outcome="SUCCESS"
    due_res = recovery_execution_engine.process_due_scheduled_retries(
        session=db_session,
        limit=10,
        force_now=True,
        force_outcome="SUCCESS",
    )

    assert due_res.processed_count >= 1
    assert due_res.succeeded_count >= 1

    db_session.refresh(txn)
    assert txn.status == TransactionStatus.SUCCEEDED


def test_customer_recovery_link_creation_and_completion(db_session: Session):
    """Test interactive customer recovery payment link workflow end-to-end."""
    txn = _seed_failed_txn(db_session, failure_code="OTP_TIMEOUT", method="CARD", amount=Decimal("1999.00"))

    # 1. Create Payment Link
    link_res = recovery_execution_engine.create_customer_recovery_link(
        session=db_session,
        transaction_id=txn.id,
        channel="SMS",
        expires_in_minutes=20,
    )

    assert link_res.status == "ACTIVE"
    assert link_res.token.startswith("rec_")
    assert "https://pay.recoverx.io/pay/" in link_res.checkout_url
    assert link_res.amount == Decimal("1999.00")
    assert "UPI" in link_res.payment_method_options

    # 2. Customer views checkout
    checkout_view = recovery_execution_engine.get_customer_checkout_details(
        session=db_session,
        token=link_res.token,
    )
    assert checkout_view.token == link_res.token
    assert checkout_view.amount == Decimal("1999.00")
    assert checkout_view.is_expired is False

    # 3. Customer submits payment
    pay_res = recovery_execution_engine.complete_customer_checkout(
        session=db_session,
        token=link_res.token,
        payment_method="UPI",
        simulate_outcome="SUCCESS",
    )

    assert pay_res.success is True
    assert pay_res.status == "SUCCEEDED"
    assert pay_res.payment_method == "UPI"

    db_session.refresh(txn)
    assert txn.status == TransactionStatus.SUCCEEDED

    # Verify session marked COMPLETED
    session_record = db_session.scalar(
        select(CustomerRecoverySession).where(CustomerRecoverySession.token == link_res.token)
    )
    assert session_record.status == "COMPLETED"
    assert session_record.completed_at is not None


def test_customer_recovery_link_expired_rejection(db_session: Session):
    """Test expired customer recovery tokens cannot be used to pay."""
    txn = _seed_failed_txn(db_session, failure_code="INSUFFICIENT_FUNDS", method="CARD", amount=Decimal("500.00"))

    link_res = recovery_execution_engine.create_customer_recovery_link(
        session=db_session,
        transaction_id=txn.id,
        expires_in_minutes=10,
    )

    # Manually expire the session
    session_record = db_session.scalar(
        select(CustomerRecoverySession).where(CustomerRecoverySession.token == link_res.token)
    )
    session_record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()

    with pytest.raises(ValueError, match="expired"):
        recovery_execution_engine.complete_customer_checkout(
            session=db_session,
            token=link_res.token,
            payment_method="UPI",
        )


def test_double_recovery_prevention_guard(db_session: Session):
    """Test double-billing guard refuses execution if transaction is already SUCCEEDED."""
    txn = _seed_failed_txn(db_session, failure_code="CARD_DECLINED", method="CARD", amount=Decimal("2000.00"))
    txn.status = TransactionStatus.SUCCEEDED
    db_session.commit()

    res = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="SWITCH_TO_UPI",
    )

    assert res.disposition == "REFUSED"
    assert res.status == "REFUSED"
    assert "already SUCCEEDED" in res.message
    assert res.guard_checks["not_already_succeeded"] is False


def test_hard_failure_terminal_stop_guard(db_session: Session):
    """Test hard failures like FRAUD_REJECTED are blocked immediately."""
    txn = _seed_failed_txn(db_session, failure_code="FRAUD_REJECTED", method="CARD", amount=Decimal("12000.00"))

    res = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="RETRY_SAME_METHOD",
    )

    assert res.disposition == "BLOCKED"
    assert res.status == "BLOCKED"
    assert "Terminal stop" in res.message


def test_max_retries_exceeded_guard(db_session: Session):
    """Test execution is blocked if attempts exceed allowed category limit."""
    txn = _seed_failed_txn(db_session, failure_code="CARD_DECLINED", method="CARD", amount=Decimal("1000.00"))

    # Add extra attempts to exceed max retry (max=1 for PAYMENT_METHOD -> total attempt limit is 2)
    for i in range(2, 5):
        att = PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=i,
            payment_method="CARD",
            gateway="RAZORPAY",
            failure_code="CARD_DECLINED",
        )
        db_session.add(att)
    db_session.commit()

    res = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="SWITCH_TO_UPI",
    )

    assert res.disposition == "BLOCKED"
    assert res.status == "BLOCKED"
    assert "Maximum retry attempts" in res.message


def test_execution_metrics_aggregation(db_session: Session):
    """Test get_execution_metrics aggregates totals, success rates, and workflows."""
    txn1 = _seed_failed_txn(db_session, failure_code="TIMEOUT", method="UPI", amount=Decimal("1000.00"))
    txn2 = _seed_failed_txn(db_session, failure_code="CARD_DECLINED", method="CARD", amount=Decimal("2000.00"))

    recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn1.id,
        action_type="RETRY_SAME_METHOD",
        force_outcome="SUCCESS",
    )
    recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn2.id,
        action_type="SWITCH_TO_UPI",
        force_outcome="SUCCESS",
    )

    metrics = recovery_execution_engine.get_execution_metrics(session=db_session)
    assert metrics.total_executions >= 2
    assert metrics.successful_executions >= 2
    assert metrics.total_recovered_amount >= Decimal("3000.00")
    assert metrics.overall_recovery_rate >= 0.50
    assert "immediate_retry" in metrics.by_workflow
    assert "payment_method_switch" in metrics.by_workflow
