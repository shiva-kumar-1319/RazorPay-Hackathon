"""Durable, idempotent ingestion of failed-payment events."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    AuditLog,
    FailureEvent,
    OutboxEvent,
    PaymentAttempt,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.events import PaymentFailedEvent
from backend.app.services.recovery_policy import evaluate_failure_policy


@dataclass(frozen=True)
class IngestionResult:
    duplicate: bool
    transaction_id: UUID
    failure_event_id: UUID
    policy_category: str
    recoverable: bool


def ingest_payment_failure(session: Session, event: PaymentFailedEvent) -> IngestionResult:
    """Persist source facts, audit record, and publishable outbox event atomically."""
    source_event_id = str(event.event_id)
    existing = session.scalar(select(FailureEvent).where(FailureEvent.source_event_id == source_event_id))
    if existing:
        return IngestionResult(
            duplicate=True,
            transaction_id=existing.transaction_id,
            failure_event_id=existing.id,
            policy_category=existing.category,
            recoverable=existing.recoverable,
        )

    transaction = session.scalar(
        select(Transaction).where(Transaction.external_transaction_id == event.external_transaction_id)
    )
    if transaction is None:
        transaction = Transaction(
            external_transaction_id=event.external_transaction_id,
            merchant_id=event.merchant_id,
            amount=event.amount,
            currency=event.currency,
            status=TransactionStatus.FAILED,
        )
        session.add(transaction)
        session.flush()
    else:
        transaction.status = TransactionStatus.FAILED
        transaction.version += 1

    attempt = session.scalar(
        select(PaymentAttempt).where(
            PaymentAttempt.transaction_id == transaction.id,
            PaymentAttempt.attempt_number == event.attempt_number,
        )
    )
    if attempt is None:
        attempt = PaymentAttempt(
            transaction_id=transaction.id,
            attempt_number=event.attempt_number,
            payment_method=event.payment_method,
            gateway=event.gateway,
            failure_code=event.failure_code,
        )
        session.add(attempt)
        session.flush()

    policy = evaluate_failure_policy(event.failure_code)
    failure = FailureEvent(
        source_event_id=source_event_id,
        transaction_id=transaction.id,
        attempt_id=attempt.id,
        failure_code=event.failure_code,
        category=policy.category,
        recoverable=policy.recoverable,
        payload=event.model_dump(mode="json"),
    )
    session.add(failure)
    session.flush()
    session.add(
        AuditLog(
            transaction_id=transaction.id,
            event_type="payment.failed.v1",
            actor="payment_ingestion",
            reason_codes=list(policy.reason_codes),
            metadata_={"source_event_id": source_event_id, "correlation_id": str(event.correlation_id)},
        )
    )
    session.add(
        OutboxEvent(
            event_type="payment.failed.v1",
            aggregate_type="transaction",
            aggregate_id=str(transaction.id),
            payload={
                "event_id": source_event_id,
                "correlation_id": str(event.correlation_id),
                "transaction_id": str(transaction.id),
                "failure_event_id": str(failure.id),
                "failure_code": event.failure_code,
                "category": policy.category,
            },
        )
    )
    session.commit()
    session.refresh(failure)
    return IngestionResult(False, transaction.id, failure.id, policy.category, policy.recoverable)
