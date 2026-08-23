"""Ingress endpoints for normalized provider events."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.schemas.events import IngestionResponse, PaymentFailedEvent
from backend.app.services.event_ingestion import ingest_payment_failure

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post("/payment-failures", response_model=IngestionResponse, status_code=status.HTTP_202_ACCEPTED)
def receive_payment_failure(event: PaymentFailedEvent, response: Response, db: Session = Depends(get_db)) -> IngestionResponse:
    """Accept a normalized failure and enqueue it for asynchronous recovery."""
    result = ingest_payment_failure(db, event)
    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    return IngestionResponse(
        accepted=True,
        duplicate=result.duplicate,
        transaction_id=result.transaction_id,
        failure_event_id=result.failure_event_id,
        policy_category=result.policy_category,
        recoverable=result.recoverable,
    )
