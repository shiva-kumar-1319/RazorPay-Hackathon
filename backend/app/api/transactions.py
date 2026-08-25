"""REST API endpoints for querying transactions and attempt lifecycles."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_db
from backend.app.models.recovery import Customer, PaymentAttempt, RecoveryCase, Transaction
from backend.app.schemas.transactions import (
    CustomerSummary,
    FailureEventSummary,
    PaymentAttemptSummary,
    RecoveryActionSummary,
    RecoveryCaseSummary,
    TransactionDetailResponse,
    TransactionListItem,
    TransactionListResponse,
)

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


@router.get(
    "",
    response_model=TransactionListResponse,
    summary="List transactions with filtering and pagination",
)
def list_transactions(
    merchant_id: str | None = Query(default=None, description="Filter by merchant ID"),
    status: str | None = Query(default=None, description="Filter by transaction status"),
    payment_method: str | None = Query(default=None, description="Filter by latest payment method"),
    limit: int = Query(default=20, ge=1, le=100, description="Page limit"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
) -> TransactionListResponse:
    """Retrieve paginated transactions with attempt counts and latest status."""
    stmt = select(Transaction).options(joinedload(Transaction.attempts))
    count_stmt = select(func.count(Transaction.id))

    if merchant_id:
        stmt = stmt.where(Transaction.merchant_id == merchant_id)
        count_stmt = count_stmt.where(Transaction.merchant_id == merchant_id)
    if status:
        stmt = stmt.where(Transaction.status == status.upper())
        count_stmt = count_stmt.where(Transaction.status == status.upper())

    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(Transaction.created_at.desc()).offset(offset).limit(limit)
    transactions = db.scalars(stmt).unique().all()

    items: list[TransactionListItem] = []
    for txn in transactions:
        latest_attempt = txn.attempts[-1] if txn.attempts else None
        
        # Optional method filter
        if payment_method and (not latest_attempt or latest_attempt.payment_method != payment_method.upper()):
            continue

        items.append(
            TransactionListItem(
                id=txn.id,
                external_transaction_id=txn.external_transaction_id,
                merchant_id=txn.merchant_id,
                customer_id=txn.customer_id,
                amount=txn.amount,
                currency=txn.currency,
                status=txn.status.value,
                version=txn.version,
                attempts_count=len(txn.attempts),
                latest_failure_code=latest_attempt.failure_code if latest_attempt else None,
                latest_payment_method=latest_attempt.payment_method if latest_attempt else None,
                created_at=txn.created_at,
                updated_at=txn.updated_at,
            )
        )

    return TransactionListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{transaction_id}",
    response_model=TransactionDetailResponse,
    summary="Get transaction details and full attempt history",
)
def get_transaction(
    transaction_id: UUID, db: Session = Depends(get_db)
) -> TransactionDetailResponse:
    """Fetch complete transaction details, attempts, failure events, and recovery cases."""
    stmt = (
        select(Transaction)
        .options(
            joinedload(Transaction.customer),
            joinedload(Transaction.attempts).joinedload(PaymentAttempt.failures),
            joinedload(Transaction.recovery_cases).joinedload(RecoveryCase.actions),
        )
        .where(Transaction.id == transaction_id)
    )
    transaction = db.scalar(stmt)
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {transaction_id} not found",
        )

    customer_summary = None
    if transaction.customer:
        customer_summary = CustomerSummary(
            id=transaction.customer.id,
            external_customer_id=transaction.customer.external_customer_id,
            merchant_id=transaction.customer.merchant_id,
            preferred_payment_method=transaction.customer.preferred_payment_method,
        )

    attempts_summary: list[PaymentAttemptSummary] = []
    for att in sorted(transaction.attempts, key=lambda a: a.attempt_number):
        failures = [
            FailureEventSummary(
                id=f.id,
                source_event_id=f.source_event_id,
                failure_code=f.failure_code,
                category=f.category,
                recoverable=f.recoverable,
                payload=f.payload,
                created_at=f.created_at,
            )
            for f in att.failures
        ]
        attempts_summary.append(
            PaymentAttemptSummary(
                id=att.id,
                attempt_number=att.attempt_number,
                payment_method=att.payment_method,
                gateway=att.gateway,
                failure_code=att.failure_code,
                created_at=att.created_at,
                failures=failures,
            )
        )

    cases_summary: list[RecoveryCaseSummary] = []
    for case in transaction.recovery_cases:
        actions = [
            RecoveryActionSummary(
                id=act.id,
                action_type=act.action_type.value,
                idempotency_key=act.idempotency_key,
                selected=act.selected,
                probability=act.probability,
                expected_value=act.expected_value,
                reason_codes=act.reason_codes,
                created_at=act.created_at,
            )
            for act in case.actions
        ]
        cases_summary.append(
            RecoveryCaseSummary(
                id=case.id,
                state=case.state.value,
                policy_version=case.policy_version,
                version=case.version,
                actions=actions,
                created_at=case.created_at,
            )
        )

    return TransactionDetailResponse(
        id=transaction.id,
        external_transaction_id=transaction.external_transaction_id,
        merchant_id=transaction.merchant_id,
        customer_id=transaction.customer_id,
        customer=customer_summary,
        amount=transaction.amount,
        currency=transaction.currency,
        status=transaction.status.value,
        version=transaction.version,
        attempts_count=len(transaction.attempts),
        attempts=attempts_summary,
        recovery_cases=cases_summary,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
    )
