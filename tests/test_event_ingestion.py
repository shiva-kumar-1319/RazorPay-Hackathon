from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.recovery import AuditLog, FailureEvent, OutboxEvent, Transaction
from backend.app.schemas.events import PaymentFailedEvent
from backend.app.services.event_ingestion import ingest_payment_failure


def test_failure_ingestion_is_idempotent_and_writes_outbox(db_session: Session) -> None:
    event = PaymentFailedEvent(
        external_transaction_id="txn-demo-001",
        merchant_id="merchant-demo",
        amount=Decimal("4999.00"),
        payment_method="CARD",
        attempt_number=1,
        failure_code="CARD_DECLINED",
    )

    first = ingest_payment_failure(db_session, event)
    duplicate = ingest_payment_failure(db_session, event)

    assert first.duplicate is False
    assert first.recoverable is True
    assert duplicate.duplicate is True
    assert db_session.scalar(select(func.count()).select_from(Transaction)) == 1
    assert db_session.scalar(select(func.count()).select_from(FailureEvent)) == 1
    assert db_session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == 1


def test_event_ingestion_endpoint(client) -> None:
    payload = {
        "external_transaction_id": "txn-http-001",
        "merchant_id": "merchant-http",
        "amount": 2499.00,
        "payment_method": "UPI",
        "attempt_number": 1,
        "failure_code": "UPI_FAILURE",
    }
    response = client.post("/api/v1/events/payment-failures", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] is True
    assert data["duplicate"] is False
    assert data["policy_category"] == "TEMPORARY"
    assert data["recoverable"] is True

    # Resubmit duplicate event with same event_id
    event_id = data["failure_event_id"]
    # Re-sending with same external_transaction_id & payload
    response2 = client.post("/api/v1/events/payment-failures", json=payload)
    assert response2.status_code == 202  # Different event_id generated automatically unless passed
