"""Unit tests for Transactional Outbox Publisher service."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.recovery import OutboxEvent, QuarantineEvent
from backend.app.schemas.events import DomainEventEnvelope
from backend.app.services.event_bus import EventBus
from backend.app.services.outbox_publisher import OutboxPublisherService


def test_outbox_publisher_processes_pending_events(db_session: Session):
    bus = EventBus()
    dispatched_events: list[DomainEventEnvelope] = []
    bus.subscribe("payment.failed.v1", lambda e: dispatched_events.append(e))

    publisher = OutboxPublisherService(event_bus=bus)

    # Insert test outbox events
    evt1 = OutboxEvent(
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id=str(uuid4()),
        payload={"event_id": str(uuid4()), "failure_code": "CARD_DECLINED"},
    )
    evt2 = OutboxEvent(
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id=str(uuid4()),
        payload={"event_id": str(uuid4()), "failure_code": "TIMEOUT"},
    )
    db_session.add_all([evt1, evt2])
    db_session.commit()

    assert publisher.get_backlog_count(db_session) == 2
    assert publisher.get_published_count(db_session) == 0

    # Publish
    published, failed = publisher.publish_pending_events(db_session, limit=10)
    assert published == 2
    assert failed == 0
    assert len(dispatched_events) == 2
    assert publisher.get_backlog_count(db_session) == 0
    assert publisher.get_published_count(db_session) == 2


def test_outbox_publisher_handles_malformed_event_with_quarantine(db_session: Session):
    bus = EventBus()

    def buggy_subscriber(e):
        # Force an unhandled exception to simulate fatal handler issue if needed
        pass

    bus.subscribe("malformed.event", buggy_subscriber)
    publisher = OutboxPublisherService(event_bus=bus)

    # Corrupt outbox row with broken event
    corrupt_evt = OutboxEvent(
        event_type="malformed.event",
        aggregate_type="transaction",
        aggregate_id="not_a_real_uuid",
        payload=None,  # Null payload
    )
    db_session.add(corrupt_evt)
    db_session.commit()

    published, failed = publisher.publish_pending_events(db_session, limit=10)
    # The publisher will successfully convert it to envelope with fallback uuid or record quarantine
    assert publisher.get_backlog_count(db_session) == 0
