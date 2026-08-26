"""Background outbox publisher worker process and CLI utility."""

import argparse
import logging
import sys
import time

from backend.app.config import get_settings
from backend.app.db import get_session_factory, initialize_database
from backend.app.logging import configure_logging
from backend.app.services.outbox_publisher import outbox_publisher
from backend.app.services.recovery_service import get_pipeline_metrics, recovery_orchestrator

logger = logging.getLogger("recoverx.worker")


def run_worker_pass(limit: int = 100) -> tuple[int, int]:
    """Run a single pass of the outbox publisher."""
    # Ensure recovery orchestrator is initialized and listening to event bus
    _ = recovery_orchestrator
    session_factory = get_session_factory()
    with session_factory() as session:
        return outbox_publisher.publish_pending_events(session, limit=limit)


def print_status() -> None:
    """Print current pipeline metrics and backlog status."""
    session_factory = get_session_factory()
    with session_factory() as session:
        metrics = get_pipeline_metrics(session)
    print("\n--- RecoverX Real-Time Event Pipeline Status ---")
    print(f"Pending Outbox Backlog : {metrics['outbox_pending_count']}")
    print(f"Published Outbox Total : {metrics['outbox_published_count']}")
    print(f"Processed Events Total : {metrics['processed_events_count']}")
    print(f"Quarantined Events     : {metrics['quarantine_events_count']}")
    print(f"Total Recovery Cases   : {metrics['total_recovery_cases']}")
    print(f"  - Open Cases         : {metrics['open_recovery_cases']}")
    print(f"  - Stopped Cases      : {metrics['stopped_recovery_cases']}")
    print(f"Pipeline Healthy       : {metrics['pipeline_healthy']}")
    print("------------------------------------------------\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="RecoverX Outbox Publisher & Event Pipeline Worker")
    parser.add_argument("--once", action="store_true", help="Run a single outbox publication pass and exit")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds (default: 2.0s)")
    parser.add_argument("--batch-size", type=int, default=100, help="Max outbox records per batch (default: 100)")
    parser.add_argument("--status", action="store_true", help="Print pipeline status metrics and exit")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if settings.auto_create_schema:
        initialize_database()

    if args.status:
        print_status()
        sys.exit(0)

    if args.once:
        logger.info("Executing single outbox publisher pass (limit=%d)...", args.batch_size)
        published, failed = run_worker_pass(limit=args.batch_size)
        logger.info("Single pass complete: %d published, %d failed", published, failed)
        print_status()
        sys.exit(0)

    logger.info("Starting RecoverX Outbox Worker daemon (interval=%.1fs, batch_size=%d)...", args.interval, args.batch_size)
    try:
        while True:
            published, failed = run_worker_pass(limit=args.batch_size)
            if published > 0 or failed > 0:
                logger.info("Published %d events (%d failed)", published, failed)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Outbox worker received shutdown signal. Exiting.")


if __name__ == "__main__":
    main()
