"""Unit tests for the 6 allow-listed agent tools and tool registry."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    ActionType,
    Customer,
    CustomerIntelligence,
    PaymentAttempt,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.services.agent_tools import (
    _mask_email,
    _mask_phone,
    agent_tool_registry,
    tool_create_recovery_plan,
    tool_get_failure_policy,
    tool_get_transaction_context,
    tool_request_execution,
    tool_score_candidates,
    tool_write_explanation,
)


def test_pii_masking_helpers() -> None:
    """Test email and phone PII masking functions."""
    assert _mask_email("priya.sharma@example.com") == "p**********a@example.com"
    assert _mask_email("ab@domain.com") == "a*@domain.com"
    assert _mask_email(None) is None

    assert _mask_phone("+919876543210") == "+91 ******3210"
    assert _mask_phone("9876543210") == "98 ******3210"
    assert _mask_phone(None) is None


def test_get_transaction_context_redacts_pii(db_session: Session) -> None:
    """Test get_transaction_context tool returns safe, PII-redacted customer details."""
    customer = Customer(
        external_customer_id=f"cust_test_{uuid4().hex[:6]}",
        merchant_id="merch_test",
        name="Vikram Mehta",
        email="vikram.mehta@fintech.in",
        phone="+919123456789",
        risk_segment="STANDARD",
        preferred_payment_method="CARD",
    )
    db_session.add(customer)
    db_session.flush()

    txn = Transaction(
        external_transaction_id=f"txn_test_{uuid4().hex[:8]}",
        merchant_id="merch_test",
        customer_id=customer.id,
        amount=Decimal("3500.00"),
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

    ctx = tool_get_transaction_context(db_session, txn.id)

    assert ctx.transaction_id == str(txn.id)
    assert ctx.merchant_id == "merch_test"
    assert ctx.amount == 3500.00
    assert ctx.currency == "INR"
    assert ctx.status == "FAILED"
    assert ctx.failure_code == "CARD_DECLINED"
    assert ctx.failure_category == "PAYMENT_METHOD"
    assert ctx.is_recoverable is True
    assert ctx.current_attempt_count == 1
    assert len(ctx.attempts_history) == 1
    assert ctx.attempts_history[0].payment_method == "CARD"

    assert ctx.customer is not None
    assert ctx.customer.external_customer_id == customer.external_customer_id
    assert ctx.customer.masked_email == "v**********a@fintech.in"
    assert ctx.customer.masked_phone == "+91 ******6789"
    # Ensure raw PII is not leaked
    assert "vikram.mehta@fintech.in" not in ctx.model_dump_json()


def test_get_failure_policy_tool() -> None:
    """Test get_failure_policy returns canonical category, permitted actions, and stop rules."""
    # 1. Recoverable payment method failure
    card_policy = tool_get_failure_policy("CARD_DECLINED")
    assert card_policy["category"] == "PAYMENT_METHOD"
    assert card_policy["recoverable"] is True
    assert card_policy["is_hard_stop"] is False
    assert "SWITCH_TO_UPI" in card_policy["permitted_actions"]
    assert "RETRY_SAME_METHOD" not in card_policy["permitted_actions"]

    # 2. Hard failure (terminal stop)
    fraud_policy = tool_get_failure_policy("FRAUD_REJECTED")
    assert fraud_policy["category"] == "HARD_FAILURE"
    assert fraud_policy["recoverable"] is False
    assert fraud_policy["is_hard_stop"] is True
    assert fraud_policy["max_retries"] == 0
    assert fraud_policy["permitted_actions"] == ["STOP_RECOVERY"]

    # 3. Temporary network failure
    timeout_policy = tool_get_failure_policy("TIMEOUT")
    assert timeout_policy["category"] == "TEMPORARY"
    assert timeout_policy["recoverable"] is True
    assert timeout_policy["max_retries"] == 3
    assert "DELAYED_RETRY" in timeout_policy["permitted_actions"]


def test_score_candidates_tool(db_session: Session) -> None:
    """Test score_candidates tool evaluates ML success probability and EV for policy actions."""
    txn = Transaction(
        external_transaction_id=f"txn_score_{uuid4().hex[:8]}",
        merchant_id="merch_test",
        amount=Decimal("4500.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            failure_code="CARD_DECLINED",
        )
    )
    db_session.commit()

    res = tool_score_candidates(db_session, txn.id, failure_code="CARD_DECLINED")

    assert res.transaction_id == str(txn.id)
    assert res.failure_category == "PAYMENT_METHOD"
    assert len(res.candidates) > 0
    assert res.best_action is not None
    assert res.best_action.expected_value > 0.0
    assert res.best_action.probability > 0.0
    assert res.best_action.action_type in ("SWITCH_TO_UPI", "PAYMENT_LINK", "SWITCH_TO_NETBANKING")


def test_create_recovery_plan_tool_enforces_policy(db_session: Session) -> None:
    """Test create_recovery_plan creates plan for valid actions and rejects policy violations."""
    txn = Transaction(
        external_transaction_id=f"txn_plan_{uuid4().hex[:8]}",
        merchant_id="merch_test",
        amount=Decimal("2000.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            failure_code="CARD_DECLINED",
        )
    )
    db_session.commit()

    # 1. Valid plan creation
    plan = tool_create_recovery_plan(
        session=db_session,
        transaction_id=txn.id,
        chosen_action="SWITCH_TO_UPI",
        confidence_score=0.88,
        reason_codes=["RECOMMENDED_SAFE_UPI"],
    )
    assert plan.transaction_id == str(txn.id)
    assert plan.chosen_action == "SWITCH_TO_UPI"
    assert plan.expected_value > 0
    assert plan.status in ("APPROVED", "DRAFT")
    assert plan.idempotency_key.startswith("idemp_")

    # 2. Invalid action policy violation (e.g. RETRY_SAME_METHOD on CARD_DECLINED)
    with pytest.raises(ValueError, match="Policy violation"):
        tool_create_recovery_plan(
            session=db_session,
            transaction_id=txn.id,
            chosen_action="RETRY_SAME_METHOD",
        )


def test_request_execution_guard_blocks_succeeded_transactions(db_session: Session) -> None:
    """Test executor guard refuses execution on already-succeeded transactions (prevents double billing)."""
    txn = Transaction(
        external_transaction_id=f"txn_succ_{uuid4().hex[:8]}",
        merchant_id="merch_test",
        amount=Decimal("1500.00"),
        status=TransactionStatus.SUCCEEDED,  # Already Succeeded!
    )
    db_session.add(txn)
    db_session.flush()

    res = tool_request_execution(
        session=db_session,
        transaction_id=txn.id,
        recovery_plan_id="plan_test_123",
    )

    assert res.disposition == "REFUSED"
    assert "already SUCCEEDED" in res.message
    assert res.guard_checks["not_already_succeeded"] is False


def test_request_execution_guard_blocks_exceeded_attempts(db_session: Session) -> None:
    """Test executor guard blocks execution when max attempts are exceeded."""
    txn = Transaction(
        external_transaction_id=f"txn_max_{uuid4().hex[:8]}",
        merchant_id="merch_test",
        amount=Decimal("1500.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()

    # Add 5 attempts for a card decline (max retries is 1)
    for i in range(1, 5):
        db_session.add(
            PaymentAttempt(
                transaction_id=txn.id,
                attempt_number=i,
                payment_method="CARD",
                failure_code="CARD_DECLINED",
            )
        )
    db_session.commit()

    res = tool_request_execution(
        session=db_session,
        transaction_id=txn.id,
        recovery_plan_id="plan_test_456",
    )

    assert res.disposition == "BLOCKED"
    assert "Maximum retry attempts" in res.message
    assert res.guard_checks["attempt_limit_valid"] is False


def test_write_explanation_tool(db_session: Session) -> None:
    """Test write_explanation tool inserts structured audit log with reason codes."""
    txn = Transaction(
        external_transaction_id=f"txn_expl_{uuid4().hex[:8]}",
        merchant_id="merch_test",
        amount=Decimal("2500.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            failure_code="CARD_DECLINED",
        )
    )
    db_session.commit()

    res = tool_write_explanation(
        session=db_session,
        transaction_id=txn.id,
        recovery_plan_id="plan_test_expl",
        explanation_summary="Agent recommended UPI switch with ₹1700 EV.",
        customer_message="Your card was declined by your bank. Tap here to pay with UPI.",
        merchant_notes="Card declined: switch to UPI to minimize friction.",
        reason_codes=["RECOMMENDED_SAFE_UPI"],
    )

    assert res.transaction_id == str(txn.id)
    assert res.explanation_summary == "Agent recommended UPI switch with ₹1700 EV."
    assert "RECOMMENDED_SAFE_UPI" in res.reason_codes
    assert res.audit_id is not None


def test_agent_tool_registry_disallows_arbitrary_tools(db_session: Session) -> None:
    """Test registry blocks disallowed tool names and returns tool catalog with guardrails."""
    catalog = agent_tool_registry.get_catalog()
    tool_names = [t.name for t in catalog.tools]
    assert "get_transaction_context" in tool_names
    assert "get_failure_policy" in tool_names
    assert "score_candidates" in tool_names
    assert "create_recovery_plan" in tool_names
    assert "request_execution" in tool_names
    assert "write_explanation" in tool_names
    assert len(catalog.guardrails) >= 5

    # Test executing an unknown tool
    res = agent_tool_registry.execute_tool(
        session=db_session,
        tool_name="execute_raw_sql_query",
        arguments={"sql": "DROP TABLE transactions;"},
    )
    assert res.success is False
    assert "Disallowed tool" in res.error
