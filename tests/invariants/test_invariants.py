"""Invariants Test Suite: Cryptographic Tamper-Detection, Double-Billing Prevention, and Idempotency."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.app.models.recovery import PaymentAttempt, RecoveryCase, RecoveryState, Transaction, TransactionStatus
from backend.app.services.audit_chain import record_audit_event, verify_audit_chain
from backend.app.services.recovery_execution import recovery_execution_engine


def test_audit_hash_chain_sequential_integrity_and_tamper_detection(db_session: Session):
    """Test SHA-256 hash chaining records correctly and detects tampering."""
    txn = Transaction(
        external_transaction_id=f"txn_chain_{uuid4().hex[:8]}",
        merchant_id="merch_audit",
        amount=Decimal("2500.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.commit()

    # Record sequence 1, 2, 3
    e1 = record_audit_event(
        session=db_session,
        transaction_id=txn.id,
        event_type="payment.failed.v1",
        action="INGEST_FAILURE",
        actor="SYSTEM",
        before_state="INITIATED",
        after_state="FAILED",
        reason_codes=["BANK_TIMEOUT"],
    )
    e2 = record_audit_event(
        session=db_session,
        transaction_id=txn.id,
        event_type="agent.decided.v1",
        action="RECOMMEND_DELAYED_RETRY",
        actor="AGENT_RECOVERX",
        before_state="FAILED",
        after_state="PLAN_PROPOSED",
        reason_codes=["SCHEDULE_BACKOFF"],
    )
    e3 = record_audit_event(
        session=db_session,
        transaction_id=txn.id,
        event_type="recovery.executed.v1",
        action="EXECUTE_DELAYED_RETRY",
        actor="EXECUTION_ENGINE",
        before_state="PLAN_PROPOSED",
        after_state="RECOVERED",
        reason_codes=["DELAYED_RETRY_SUCCESS"],
    )

    # Verify intact chain
    valid, err = verify_audit_chain(db_session, txn.id)
    assert valid is True
    assert err is None

    # Tamper with event 2's action
    e2.action = "TAMPERED_MALICIOUS_ACTION"
    db_session.commit()

    # Verification must now fail on sequence 2
    valid_after, err_after = verify_audit_chain(db_session, txn.id)
    assert valid_after is False
    assert "Hash mismatch at sequence 2" in str(err_after)



def test_double_recovery_prevention_invariant(db_session: Session):
    """Invariant: Once transaction is SUCCEEDED, any recovery execution is unconditionally refused."""
    txn = Transaction(
        external_transaction_id=f"txn_dbl_{uuid4().hex[:8]}",
        merchant_id="merch_invariant",
        amount=Decimal("4999.00"),
        status=TransactionStatus.SUCCEEDED,
    )
    db_session.add(txn)
    db_session.commit()

    res = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="RETRY_SAME_METHOD",
    )
    assert res.disposition == "REFUSED"
    assert res.status == "REFUSED"
    assert res.guard_checks["not_already_succeeded"] is False
    assert "Double recovery is strictly prevented" in res.message


def test_hard_failure_terminal_stop_invariant(db_session: Session):
    """Invariant: Transactions with terminal fraud or blocked card failures MUST be blocked without retrying."""
    txn = Transaction(
        external_transaction_id=f"txn_fraud_{uuid4().hex[:8]}",
        merchant_id="merch_invariant",
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
            gateway="RAZORPAY",
            failure_code="FRAUD_REJECTED",
        )
    )
    db_session.commit()

    res = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="RETRY_SAME_METHOD",
    )
    assert res.disposition == "BLOCKED"
    assert res.status == "BLOCKED"
    assert res.guard_checks["policy_valid"] is False
    assert "Terminal stop applied for hard failure" in res.message


def test_idempotency_key_cached_response_invariant(db_session: Session):
    """Invariant: Re-executing with the same idempotency key returns cached result without duplicate execution."""
    txn = Transaction(
        external_transaction_id=f"txn_idemp_{uuid4().hex[:8]}",
        merchant_id="merch_invariant",
        amount=Decimal("1500.00"),
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

    idemp_key = f"key_{uuid4().hex[:12]}"

    # First execution
    res1 = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="SWITCH_TO_UPI",
        idempotency_key=idemp_key,
        force_outcome="SUCCESS",
    )
    assert res1.status == "SUCCEEDED"
    first_exec_id = res1.execution_id

    # Second execution with identical key
    res2 = recovery_execution_engine.execute_action(
        session=db_session,
        transaction_id=txn.id,
        action_type="SWITCH_TO_UPI",
        idempotency_key=idemp_key,
        force_outcome="SUCCESS",
    )
    assert res2.status == "SUCCEEDED"
    assert res2.attempt_number == res1.attempt_number
