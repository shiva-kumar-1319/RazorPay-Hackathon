"""API endpoints for Recovery Execution engine, customer recovery links, and scheduling."""

import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.auth import get_current_merchant, verify_merchant_ownership
from backend.app.db import get_db
from backend.app.models.recovery import Transaction
from backend.app.schemas.execution import (
    CustomerCheckoutDetailResponse,
    CustomerCheckoutSubmitRequest,
    CustomerCheckoutSubmitResponse,
    CustomerRecoveryLinkCreateRequest,
    CustomerRecoveryLinkResponse,
    ExecuteActionRequest,
    ExecuteActionResponse,
    ExecutionMetricsResponse,
    ProcessScheduledRetriesRequest,
    ProcessScheduledRetriesResponse,
)
from backend.app.services.recovery_execution import recovery_execution_engine

router = APIRouter(prefix="/api/v1/execution", tags=["execution"])


@router.post("/actions/execute", response_model=ExecuteActionResponse)
def execute_recovery_action(
    request: ExecuteActionRequest,
    db: Session = Depends(get_db),
    merchant_id: str = Depends(get_current_merchant),
) -> ExecuteActionResponse:
    """Execute an automated, bounded recovery action (retry, switch, delayed retry, or customer recovery)."""
    # Guard against force_outcome abuse outside of testing
    if request.force_outcome is not None:
        app_env = os.getenv("APP_ENV", "development").lower()
        if app_env not in ("test", "testing"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="force_outcome parameter is forbidden in non-test environments.",
            )

    # Validate merchant tenant ownership
    try:
        txn_uuid = UUID(str(request.transaction_id))
        txn = db.get(Transaction, txn_uuid)
        if txn:
            verify_merchant_ownership(merchant_id, txn.merchant_id)
    except ValueError:
        pass

    try:
        res = recovery_execution_engine.execute_action(
            session=db,
            transaction_id=request.transaction_id,
            action_type=request.action_type,
            recovery_action_id=request.recovery_action_id,
            recovery_plan_id=request.recovery_plan_id,
            idempotency_key=request.idempotency_key,
            parameters=request.parameters,
            force_outcome=request.force_outcome,
        )
        return res
    except ValueError as ex:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ex),
        )


@router.post("/scheduler/run-due", response_model=ProcessScheduledRetriesResponse)
def run_due_scheduled_retries(
    request: ProcessScheduledRetriesRequest | None = None,
    db: Session = Depends(get_db),
) -> ProcessScheduledRetriesResponse:
    """Process all delayed retries that have reached their scheduled execution time."""
    limit = request.limit if request else 50
    force_now = request.force_now if request else False
    force_outcome = request.force_outcome if request else None

    if force_outcome is not None:
        app_env = os.getenv("APP_ENV", "development").lower()
        if app_env not in ("test", "testing"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="force_outcome parameter is forbidden in non-test environments.",
            )

    return recovery_execution_engine.process_due_scheduled_retries(
        session=db,
        limit=limit,
        force_now=force_now,
        force_outcome=force_outcome,
    )


@router.post("/customer/create-link", response_model=CustomerRecoveryLinkResponse)
def create_customer_recovery_link(
    request: CustomerRecoveryLinkCreateRequest,
    db: Session = Depends(get_db),
    merchant_id: str = Depends(get_current_merchant),
) -> CustomerRecoveryLinkResponse:
    """Generate a tokenized customer recovery session and dispatch notification."""
    try:
        txn_uuid = UUID(str(request.transaction_id))
        txn = db.get(Transaction, txn_uuid)
        if txn:
            verify_merchant_ownership(merchant_id, txn.merchant_id)
    except ValueError:
        pass

    try:
        return recovery_execution_engine.create_customer_recovery_link(
            session=db,
            transaction_id=request.transaction_id,
            recovery_action_id=request.recovery_action_id,
            channel=request.channel,
            expires_in_minutes=request.expires_in_minutes,
            custom_message=request.custom_message,
        )

    except ValueError as ex:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "not found" in str(ex).lower() else status.HTTP_400_BAD_REQUEST,
            detail=str(ex),
        )


@router.get("/customer/link/{token}", response_model=CustomerCheckoutDetailResponse)
def get_customer_checkout(
    token: str,
    db: Session = Depends(get_db),
) -> CustomerCheckoutDetailResponse:
    """Public customer checkout view for inspecting payment details via recovery token."""
    try:
        return recovery_execution_engine.get_customer_checkout_details(session=db, token=token)
    except ValueError as ex:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(ex),
        )


@router.post("/customer/link/{token}/pay", response_model=CustomerCheckoutSubmitResponse)
def submit_customer_recovery_payment(
    token: str,
    request: CustomerCheckoutSubmitRequest,
    db: Session = Depends(get_db),
) -> CustomerCheckoutSubmitResponse:
    """Customer submits interactive recovery payment via recovery link."""
    try:
        return recovery_execution_engine.complete_customer_checkout(
            session=db,
            token=token,
            payment_method=request.payment_method,
            instrument_details=request.instrument_details,
            simulate_outcome=request.simulate_outcome,
        )
    except ValueError as ex:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ex),
        )


@router.get("/metrics", response_model=ExecutionMetricsResponse)
def get_execution_metrics(
    db: Session = Depends(get_db),
) -> ExecutionMetricsResponse:
    """Retrieve operational KPIs, recovery success rates, and workflow conversion metrics."""
    return recovery_execution_engine.get_execution_metrics(session=db)
