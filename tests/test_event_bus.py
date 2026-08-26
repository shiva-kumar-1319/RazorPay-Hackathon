"""Unit tests for the RecoverX In-Memory EventBus service."""

from uuid import uuid4

from backend.app.schemas.events import DomainEventEnvelope
from backend.app.services.event_bus import EventBus


def test_event_bus_subscription_and_sync_dispatch():
    bus = EventBus()
    received_events: list[DomainEventEnvelope] = []

    def handler(event: DomainEventEnvelope):
        received_events.append(event)

    bus.subscribe("payment.failed.v1", handler)

    envelope = DomainEventEnvelope(
        event_id=uuid4(),
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id="txn_123",
        payload={"reason": "CARD_DECLINED"},
    )

    dispatched = bus.publish_sync(envelope)
    assert dispatched == 1
    assert len(received_events) == 1
    assert received_events[0].aggregate_id == "txn_123"
    assert received_events[0].payload["reason"] == "CARD_DECLINED"


def test_event_bus_wildcard_subscription():
    bus = EventBus()
    events_received: list[str] = []

    bus.subscribe("*", lambda e: events_received.append(e.event_type))

    e1 = DomainEventEnvelope(
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id="txn_1",
    )
    e2 = DomainEventEnvelope(
        event_type="recovery.decided.v1",
        aggregate_type="recovery_case",
        aggregate_id="case_1",
    )

    bus.publish_sync(e1)
    bus.publish_sync(e2)

    assert len(events_received) == 2
    assert "payment.failed.v1" in events_received
    assert "recovery.decided.v1" in events_received


def test_event_bus_error_boundary_does_not_break_other_subscribers():
    bus = EventBus()
    good_calls = []

    def faulty_handler(event: DomainEventEnvelope):
        raise ValueError("Simulated subscriber failure")

    def successful_handler(event: DomainEventEnvelope):
        good_calls.append(event.event_type)

    bus.subscribe("payment.failed.v1", faulty_handler)
    bus.subscribe("payment.failed.v1", successful_handler)

    envelope = DomainEventEnvelope(
        event_type="payment.failed.v1",
        aggregate_type="transaction",
        aggregate_id="txn_456",
    )

    # publish_sync should execute both, catching the faulty one and letting the good one pass
    successful = bus.publish_sync(envelope)
    assert successful == 1
    assert len(good_calls) == 1
    metrics = bus.get_metrics()
    assert metrics["total_published"] == 1
    assert metrics["total_dispatched"] == 1
    assert metrics["total_errors"] == 1
