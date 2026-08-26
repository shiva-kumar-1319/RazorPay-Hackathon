"""Tests verifying the PostgreSQL/SQLAlchemy schema models and constraints."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from backend.app.models.base import Base
from backend.app.models.recovery import (
    ActionType,
    AuditLog,
    Customer,
    FailureEvent,
    OutboxEvent,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)


def test_all_expected_tables_are_registered() -> None:
    expected_tables = {
        "customers",
        "transactions",
        "payment_attempts",
        "failure_events",
        "recovery_cases",
        "recovery_actions",
        "outbox_events",
        "audit_logs",
        "processed_events",
        "quarantine_events",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables)


def test_customer_transaction_relationship(db_session: Session) -> None:
    customer = Customer(
        external_customer_id="cust-001",
        merchant_id="merchant-test",
        preferred_payment_method="UPI",
    )
    db_session.add(customer)
    db_session.flush()

    transaction = Transaction(
        external_transaction_id="txn-rel-001",
        merchant_id="merchant-test",
        customer_id=customer.id,
        amount=Decimal("1500.00"),
        currency="INR",
        status=TransactionStatus.PROCESSING,
    )
    db_session.add(transaction)
    db_session.commit()

    # Query back
    queried = db_session.scalar(
        select(Customer).where(Customer.external_customer_id == "cust-001")
    )
    assert queried is not None
    assert len(queried.transactions) == 1
    assert queried.transactions[0].amount == Decimal("1500.00")


def test_recovery_case_and_actions(db_session: Session) -> None:
    transaction = Transaction(
        external_transaction_id="txn-case-001",
        merchant_id="merchant-test",
        amount=Decimal("999.00"),
        currency="INR",
        status=TransactionStatus.FAILED,
    )
    db_session.add(transaction)
    db_session.flush()

    case = RecoveryCase(
        transaction_id=transaction.id,
        state=RecoveryState.OPEN,
        policy_version="v1.0",
    )
    db_session.add(case)
    db_session.flush()

    action = RecoveryAction(
        recovery_case_id=case.id,
        action_type=ActionType.SWITCH_TO_UPI,
        idempotency_key=f"case-{case.id}-switch-upi",
        selected=True,
        probability=Decimal("0.8500"),
        expected_value=Decimal("849.15"),
        reason_codes=["CARD_FAILED_HIGH_UPI_AFFINITY"],
    )
    db_session.add(action)
    db_session.commit()

    queried_case = db_session.scalar(
        select(RecoveryCase).where(RecoveryCase.transaction_id == transaction.id)
    )
    assert queried_case is not None
    assert len(queried_case.actions) == 1
    assert queried_case.actions[0].action_type == ActionType.SWITCH_TO_UPI
    assert queried_case.actions[0].selected is True
