"""Transactional Outbox Publisher service for reliable, at-least-once event delivery."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db import reset_current_session, set_current_session
from backend.app.models.recovery import OutboxEvent, QuarantineEvent
from backend.app.schemas.events import DomainEventEnvelope
from backend.app.services.event_bus import EventBus, get_event_bus

logger = logging.getLogger("recoverx.outbox_publisher")


class OutboxPublisherService:
    """Publishes unpublished OutboxEvent entries to the EventBus reliably."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or get_event_bus()

    def publish_pending_events(self, session: Session, limit: int = 100) -> tuple[int, int]:
        """Fetch unpublished outbox rows, dispatch to the event bus, and mark published.

        Returns (published_count, failed_count).
        """
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
        )
        events = list(session.scalars(stmt).all())
        if not events:
            return 0, 0

        published_count = 0
        failed_count = 0
        now = datetime.now(timezone.utc)

        token = set_current_session(session)
        try:
            for outbox_row in events:
                try:
                    # Construct DomainEventEnvelope from outbox row
                    payload_dict = outbox_row.payload or {}
                    raw_event_id = payload_dict.get("event_id") or str(outbox_row.id)
                    try:
                        event_uuid = UUID(str(raw_event_id))
                    except (ValueError, TypeError):
                        event_uuid = uuid4()

                    raw_corr_id = payload_dict.get("correlation_id") or str(uuid4())
                    try:
                        corr_uuid = UUID(str(raw_corr_id))
                    except (ValueError, TypeError):
                        corr_uuid = uuid4()

                    envelope = DomainEventEnvelope(
                        event_id=event_uuid,
                        event_type=outbox_row.event_type,
                        occurred_at=outbox_row.created_at,
                        aggregate_type=outbox_row.aggregate_type,
                        aggregate_id=outbox_row.aggregate_id,
                        correlation_id=corr_uuid,
                        causation_id=None,
                        schema_version=1,
                        payload=payload_dict,
                    )

                    # Publish to EventBus
                    self.event_bus.publish_sync(envelope)
                    outbox_row.published_at = now
                    published_count += 1

                except Exception as exc:
                    failed_count += 1
                    logger.exception("Failed to publish outbox event %s: %s", outbox_row.id, exc)

                    # Route poison/malformed event to quarantine to preserve pipeline flow
                    payload_json = json.dumps(outbox_row.payload, default=str) if outbox_row.payload else "{}"
                    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
                    quarantine = QuarantineEvent(
                        source_event_id=str(outbox_row.id),
                        event_type=outbox_row.event_type,
                        consumer_name="outbox_publisher",
                        reason=f"Publication failed: {str(exc)[:240]}",
                        payload=outbox_row.payload or {},
                        payload_hash=payload_hash,
                        status="QUARANTINED",
                    )
                    session.add(quarantine)
                    outbox_row.published_at = now  # Mark published so publisher does not lock forever

            session.commit()
        finally:
            reset_current_session(token)

        logger.info("Outbox publisher processed %d events (%d succeeded, %d failed)", len(events), published_count, failed_count)
        return published_count, failed_count

    @staticmethod
    def get_backlog_count(session: Session) -> int:
        """Count unpublished outbox rows."""
        stmt = select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))
        return session.scalar(stmt) or 0

    @staticmethod
    def get_published_count(session: Session) -> int:
        """Count published outbox rows."""
        stmt = select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_not(None))
        return session.scalar(stmt) or 0


# Singleton helper
outbox_publisher = OutboxPublisherService()
