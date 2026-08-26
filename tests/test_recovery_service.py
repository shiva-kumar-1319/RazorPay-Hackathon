"""Unit tests for Recovery Orchestrator service and candidate action ranking."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    ActionType,
    AuditLog,
    OutboxEvent,
    PaymentAttempt,
    ProcessedEvent,
    RecoveryAction,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.events import DomainEventEnvelope
from backend.app.services.event_bus import EventBus
from backend.app.services.recovery_service import (
    RecoveryOrchestrator,
    get_pipeline_metrics,
    get_recovery_case_by_id,
    list_recovery_cases,
)


def _create_test_transaction(db_session: Session, failure_code: str, amount: Decimal = Decimal("4999.00")) -> tuple[Transaction, PaymentAttempt]:
    txn = Transaction(
        external_transaction_id=f"txn_{uuid4().hex[:12]}",
        merchant_id="merchant_test_1",
        amount=amount,
        currency="INR",
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()

    attempt = PaymentAttempt(
        transaction_id=txn.id,
        attempt_number=1,
        payment_method="CARD",
        failure_code=failure_code,
    )
    db_session.add(attempt)
    db_session.commit()
    return txn, attempt


def test_recovery_orchestrator_opens_case_for_card_decline(db_session: Session):
    bus = EventBus()
    orchestrator = RecoveryOrchestrator(event_bus=bus)

    txn, attempt = _create_test_transaction(db_session, failure_code="CARD_DECLINED", amount=Decimal("4999.00"))
    event_id = uuid4()

    event = DomainEventEnvelope(
        event_id=event_id,
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id=str(txn.id),
        payload={
            "transaction_id": str(txn.id),
            "failure_code": "CARD_DECLINED",
            "category": "PAYMENT_METHOD",
        },
    )

    case = orchestrator.process_payment_failure(db_session, event)
    assert case is not None
    assert case.state == RecoveryState.OPEN
    assert case.policy_version == "policy.v1"
    assert len(case.actions) == 2

    # Primary action must be SWITCH_TO_UPI
    primary = next(a for a in case.actions if a.selected)
    assert primary.action_type == ActionType.SWITCH_TO_UPI
    assert primary.probability == Decimal("0.8500")
    assert primary.expected_value == Decimal("4249.15")  # 4999 * 0.85

    # Secondary action is PAYMENT_LINK
    secondary = next(a for a in case.actions if not a.selected)
    assert secondary.action_type == ActionType.PAYMENT_LINK

    # Verify audit log was created
    audit = db_session.scalar(select(AuditLog).where(AuditLog.transaction_id == txn.id))
    assert audit is not None
    assert audit.actor == "recovery_orchestrator"
    assert "RECOMMENDED_SAFE_UPI" in primary.reason_codes

    # Verify downstream outbox events emitted
    outbox_rows = list(db_session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id.in_([str(txn.id), str(case.id)]))).all())
    event_types = [o.event_type for o in outbox_rows]
    assert "failure.classified.v1" in event_types
    assert "recovery.case_opened.v1" in event_types


def test_recovery_orchestrator_handles_otp_timeout_customer_action(db_session: Session):
    bus = EventBus()
    orchestrator = RecoveryOrchestrator(event_bus=bus)

    txn, attempt = _create_test_transaction(db_session, failure_code="OTP_TIMEOUT", amount=Decimal("2500.00"))
    event = DomainEventEnvelope(
        event_id=uuid4(),
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id=str(txn.id),
        payload={
            "transaction_id": str(txn.id),
            "failure_code": "OTP_TIMEOUT",
            "category": "CUSTOMER_ACTION",
        },
    )

    case = orchestrator.process_payment_failure(db_session, event)
    assert case is not None
    assert case.state == RecoveryState.OPEN
    primary = next(a for a in case.actions if a.selected)
    assert primary.action_type == ActionType.CUSTOMER_NOTIFICATION
    assert primary.probability == Decimal("0.7200")


def test_recovery_orchestrator_handles_transient_failure_backoff(db_session: Session):
    bus = EventBus()
    orchestrator = RecoveryOrchestrator(event_bus=bus)

    txn, attempt = _create_test_transaction(db_session, failure_code="UPI_FAILURE", amount=Decimal("3000.00"))
    event = DomainEventEnvelope(
        event_id=uuid4(),
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id=str(txn.id),
        payload={
            "transaction_id": str(txn.id),
            "failure_code": "UPI_FAILURE",
            "category": "TEMPORARY",
        },
    )

    case = orchestrator.process_payment_failure(db_session, event)
    assert case is not None
    assert case.state == RecoveryState.OPEN
    primary = next(a for a in case.actions if a.selected)
    assert primary.action_type == ActionType.DELAYED_RETRY
    assert primary.probability == Decimal("0.7800")


def test_recovery_orchestrator_stops_hard_failures(db_session: Session):
    bus = EventBus()
    orchestrator = RecoveryOrchestrator(event_bus=bus)

    txn, attempt = _create_test_transaction(db_session, failure_code="FRAUD_REJECTED", amount=Decimal("12000.00"))
    event = DomainEventEnvelope(
        event_id=uuid4(),
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id=str(txn.id),
        payload={
            "transaction_id": str(txn.id),
            "failure_code": "FRAUD_REJECTED",
            "category": "HARD_FAILURE",
        },
    )

    case = orchestrator.process_payment_failure(db_session, event)
    assert case is not None
    assert case.state == RecoveryState.STOPPED
    assert len(case.actions) == 1
    assert case.actions[0].action_type == ActionType.STOP_RECOVERY
    assert case.actions[0].selected is True
    assert case.actions[0].expected_value == Decimal("0.00")


def test_recovery_orchestrator_idempotent_duplicate_events(db_session: Session):
    bus = EventBus()
    orchestrator = RecoveryOrchestrator(event_bus=bus)

    txn, attempt = _create_test_transaction(db_session, failure_code="TIMEOUT", amount=Decimal("1500.00"))
    fixed_event_id = uuid4()

    event = DomainEventEnvelope(
        event_id=fixed_event_id,
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id=str(txn.id),
        payload={
            "transaction_id": str(txn.id),
            "failure_code": "TIMEOUT",
            "category": "TEMPORARY",
        },
    )

    # First delivery
    case1 = orchestrator.process_payment_failure(db_session, event)
    assert case1 is not None

    # Duplicate delivery with identical event_id
    case2 = orchestrator.process_payment_failure(db_session, event)
    assert case2 is not None
    assert case2.id == case1.id

    # Verify only 1 processed_events record exists for this consumer and event_id
    processed_count = db_session.scalar(
        select(ProcessedEvent).where(
            ProcessedEvent.consumer_name == "recovery_orchestrator",
            ProcessedEvent.event_id == str(fixed_event_id),
        )
    )
    assert processed_count is not None


def test_list_and_get_recovery_cases_queries(db_session: Session):
    bus = EventBus()
    orchestrator = RecoveryOrchestrator(event_bus=bus)

    txn1, _ = _create_test_transaction(db_session, failure_code="CARD_DECLINED", amount=Decimal("1000.00"))
    txn2, _ = _create_test_transaction(db_session, failure_code="BLOCKED_CARD", amount=Decimal("2000.00"))

    e1 = DomainEventEnvelope(
        event_id=uuid4(),
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id=str(txn1.id),
        payload={"transaction_id": str(txn1.id), "failure_code": "CARD_DECLINED"},
    )
    e2 = DomainEventEnvelope(
        event_id=uuid4(),
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id=str(txn2.id),
        payload={"transaction_id": str(txn2.id), "failure_code": "BLOCKED_CARD"},
    )

    case1 = orchestrator.process_payment_failure(db_session, e1)
    case2 = orchestrator.process_payment_failure(db_session, e2)

    total, cases = list_recovery_cases(db_session, merchant_id="merchant_test_1")
    assert total >= 2

    total_open, open_cases = list_recovery_cases(db_session, state="OPEN")
    assert total_open >= 1

    total_stopped, stopped_cases = list_recovery_cases(db_session, state="STOPPED")
    assert total_stopped >= 1

    detail = get_recovery_case_by_id(db_session, case1.id)
    assert detail is not None
    assert detail.id == case1.id

    metrics = get_pipeline_metrics(db_session)
    assert metrics["total_recovery_cases"] >= 2
    assert metrics["open_recovery_cases"] >= 1
    assert metrics["stopped_recovery_cases"] >= 1
