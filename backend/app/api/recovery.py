"""API endpoints for Recovery Cases and Real-Time Event Pipeline operations."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models.recovery import AuditLog, PaymentAttempt
from backend.app.schemas.recovery import (
    OutboxPublishResponse,
    PipelineProcessResponse,
    PipelineStatusResponse,
    RecoveryActionRead,
    RecoveryCaseDetail,
    RecoveryCaseListResponse,
    RecoveryCaseRead,
)
from backend.app.services.outbox_publisher import outbox_publisher
from backend.app.services.recovery_service import (
    get_pipeline_metrics,
    get_recovery_case_by_id,
    list_recovery_cases,
)

router = APIRouter(prefix="/api/v1/recovery", tags=["recovery"])


@router.get("/cases", response_model=RecoveryCaseListResponse)
def get_recovery_cases(
    merchant_id: str | None = Query(None, description="Filter cases by merchant ID"),
    state: str | None = Query(None, description="Filter cases by recovery state (OPEN, SCHEDULED, RECOVERED, STOPPED)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> RecoveryCaseListResponse:
    """List recovery cases with candidate actions and current recovery states."""
    total, items = list_recovery_cases(
        session=db,
        merchant_id=merchant_id,
        state=state,
        limit=limit,
        offset=offset,
    )

    response_items = []
    for case in items:
        txn = case.transaction
        response_items.append(
            RecoveryCaseRead(
                id=case.id,
                transaction_id=case.transaction_id,
                merchant_id=txn.merchant_id if txn else None,
                external_transaction_id=txn.external_transaction_id if txn else None,
                amount=txn.amount if txn else None,
                currency=txn.currency if txn else "INR",
                state=case.state.value,
                policy_version=case.policy_version,
                version=case.version,
                created_at=case.created_at,
                updated_at=case.updated_at,
                actions=[
                    RecoveryActionRead(
                        id=a.id,
                        recovery_case_id=a.recovery_case_id,
                        action_type=a.action_type.value,
                        idempotency_key=a.idempotency_key,
                        selected=a.selected,
                        probability=a.probability,
                        expected_value=a.expected_value,
                        reason_codes=a.reason_codes,
                        created_at=a.created_at,
                        updated_at=a.updated_at,
                    )
                    for a in case.actions
                ],
            )
        )

    return RecoveryCaseListResponse(total=total, items=response_items)


@router.get("/cases/{case_id}", response_model=RecoveryCaseDetail)
def get_recovery_case(
    case_id: UUID,
    db: Session = Depends(get_db),
) -> RecoveryCaseDetail:
    """Retrieve detailed recovery case information, candidate action rankings, and audit trail."""
    case = get_recovery_case_by_id(db, case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recovery case {case_id} not found",
        )

    txn = case.transaction
    latest_attempt = None
    if txn and txn.attempts:
        latest_attempt = sorted(txn.attempts, key=lambda a: a.attempt_number, reverse=True)[0]

    # Fetch audit trail logs for the transaction
    audit_logs = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.transaction_id == case.transaction_id)
            .order_by(AuditLog.created_at.asc())
        ).all()
    )

    audit_trail = [
        {
            "id": str(log.id),
            "event_type": log.event_type,
            "actor": log.actor,
            "reason_codes": log.reason_codes,
            "metadata": log.metadata_,
            "created_at": log.created_at.isoformat(),
        }
        for log in audit_logs
    ]

    return RecoveryCaseDetail(
        id=case.id,
        transaction_id=case.transaction_id,
        merchant_id=txn.merchant_id if txn else None,
        external_transaction_id=txn.external_transaction_id if txn else None,
        amount=txn.amount if txn else None,
        currency=txn.currency if txn else "INR",
        state=case.state.value,
        policy_version=case.policy_version,
        version=case.version,
        created_at=case.created_at,
        updated_at=case.updated_at,
        transaction_status=txn.status.value if txn else None,
        latest_failure_code=latest_attempt.failure_code if latest_attempt else None,
        latest_failure_category=latest_attempt.failures[0].category if latest_attempt and latest_attempt.failures else None,
        latest_attempt_number=latest_attempt.attempt_number if latest_attempt else None,
        actions=[
            RecoveryActionRead(
                id=a.id,
                recovery_case_id=a.recovery_case_id,
                action_type=a.action_type.value,
                idempotency_key=a.idempotency_key,
                selected=a.selected,
                probability=a.probability,
                expected_value=a.expected_value,
                reason_codes=a.reason_codes,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in case.actions
        ],
        audit_trail=audit_trail,
    )


@router.post("/pipeline/publish", response_model=OutboxPublishResponse)
def trigger_outbox_publish(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> OutboxPublishResponse:
    """Manually trigger publication of pending transactional outbox events to the EventBus."""
    published_count, failed_count = outbox_publisher.publish_pending_events(db, limit=limit)
    return OutboxPublishResponse(
        published_count=published_count,
        failed_count=failed_count,
        message=f"Published {published_count} outbox events ({failed_count} failed)",
    )


@router.post("/pipeline/process", response_model=PipelineProcessResponse)
def trigger_pipeline_process(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> PipelineProcessResponse:
    """Process pending outbox events end-to-end through the event bus and recovery orchestrator."""
    published_count, failed_count = outbox_publisher.publish_pending_events(db, limit=limit)
    metrics = get_pipeline_metrics(db)

    return PipelineProcessResponse(
        outbox_published=published_count,
        events_dispatched=published_count,
        cases_opened=metrics["open_recovery_cases"],
        cases_stopped=metrics["stopped_recovery_cases"],
        errors=[f"{failed_count} publication failures"] if failed_count > 0 else [],
    )


@router.get("/pipeline/status", response_model=PipelineStatusResponse)
def get_pipeline_status_endpoint(
    db: Session = Depends(get_db),
) -> PipelineStatusResponse:
    """Fetch pipeline operational metrics, outbox backlog, processed deduplication counts, and quarantine count."""
    metrics = get_pipeline_metrics(db)
    return PipelineStatusResponse(**metrics)
