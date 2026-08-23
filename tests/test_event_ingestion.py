from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Base
from backend.app.models.recovery import AuditLog, FailureEvent, OutboxEvent, Transaction
from backend.app.schemas.events import PaymentFailedEvent
from backend.app.services.event_ingestion import ingest_payment_failure


def test_failure_ingestion_is_idempotent_and_writes_outbox() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session: Session = sessionmaker(bind=engine)()
    event = PaymentFailedEvent(
        external_transaction_id="txn-demo-001",
        merchant_id="merchant-demo",
        amount=Decimal("4999.00"),
        payment_method="CARD",
        attempt_number=1,
        failure_code="CARD_DECLINED",
    )

    first = ingest_payment_failure(session, event)
    duplicate = ingest_payment_failure(session, event)

    assert first.duplicate is False
    assert first.recoverable is True
    assert duplicate.duplicate is True
    assert session.scalar(select(func.count()).select_from(Transaction)) == 1
    assert session.scalar(select(func.count()).select_from(FailureEvent)) == 1
    assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
    assert session.scalar(select(func.count()).select_from(AuditLog)) == 1
