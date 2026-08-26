"""In-memory event bus and subscription registry for real-time domain events."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine
from uuid import UUID

from backend.app.schemas.events import DomainEventEnvelope

logger = logging.getLogger("recoverx.event_bus")

# Type alias for event handlers
SyncHandler = Callable[[DomainEventEnvelope], Any]
AsyncHandler = Callable[[DomainEventEnvelope], Coroutine[Any, Any, Any]]
EventHandler = SyncHandler | AsyncHandler


@dataclass
class EventBusMetrics:
    total_published: int = 0
    total_dispatched: int = 0
    total_errors: int = 0
    last_published_at: datetime | None = None


class EventBus:
    """Asynchronous and synchronous in-process event bus with topic-matching and error boundaries."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._metrics = EventBusMetrics()

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for a specific event_type or '*' for all events."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)
            logger.debug("Subscribed %s to %s", getattr(handler, "__name__", str(handler)), event_type)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a previously registered handler."""
        if event_type in self._subscribers and handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)

    def clear(self) -> None:
        """Clear all registered subscriptions and reset metrics."""
        self._subscribers.clear()
        self._metrics = EventBusMetrics()

    def get_metrics(self) -> dict[str, Any]:
        """Return operational metrics for the event bus."""
        return {
            "total_published": self._metrics.total_published,
            "total_dispatched": self._metrics.total_dispatched,
            "total_errors": self._metrics.total_errors,
            "subscriber_topics": list(self._subscribers.keys()),
            "last_published_at": self._metrics.last_published_at.isoformat() if self._metrics.last_published_at else None,
        }

    def publish_sync(self, event: DomainEventEnvelope) -> int:
        """Publish a domain event synchronously to all matching subscribers.
        
        Returns the number of subscribers that processed the event without error.
        """
        self._metrics.total_published += 1
        self._metrics.last_published_at = datetime.now(timezone.utc)

        matching_handlers = list(self._subscribers.get(event.event_type, [])) + list(self._subscribers.get("*", []))
        successful_dispatches = 0

        for handler in matching_handlers:
            handler_name = getattr(handler, "__name__", str(handler))
            try:
                if inspect.iscoroutinefunction(handler):
                    # For coroutine in sync context, run via event loop or asyncio.run
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(handler(event))
                    except RuntimeError:
                        asyncio.run(handler(event))
                else:
                    handler(event)
                successful_dispatches += 1
                self._metrics.total_dispatched += 1
            except Exception as exc:
                self._metrics.total_errors += 1
                logger.exception(
                    "Error executing event subscriber %s for event %s (%s): %s",
                    handler_name,
                    event.event_type,
                    event.event_id,
                    exc,
                )

        return successful_dispatches

    async def publish(self, event: DomainEventEnvelope) -> int:
        """Publish a domain event asynchronously to all matching subscribers."""
        self._metrics.total_published += 1
        self._metrics.last_published_at = datetime.now(timezone.utc)

        matching_handlers = list(self._subscribers.get(event.event_type, [])) + list(self._subscribers.get("*", []))
        successful_dispatches = 0

        for handler in matching_handlers:
            handler_name = getattr(handler, "__name__", str(handler))
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
                successful_dispatches += 1
                self._metrics.total_dispatched += 1
            except Exception as exc:
                self._metrics.total_errors += 1
                logger.exception(
                    "Error executing async event subscriber %s for event %s (%s): %s",
                    handler_name,
                    event.event_type,
                    event.event_id,
                    exc,
                )

        return successful_dispatches


# Global singleton event bus instance
_global_event_bus = EventBus()


def get_event_bus() -> EventBus:
    """Access the application-wide global EventBus instance."""
    return _global_event_bus
