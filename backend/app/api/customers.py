"""REST API endpoints for Customer Intelligence, payment behavior profiling, and ML feature extraction."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_db
from backend.app.models.recovery import Customer, PaymentAttempt, Transaction
from backend.app.schemas.customers import (
    CustomerCreateRequest,
    CustomerDetailResponse,
    CustomerFeaturesSnapshot,
    CustomerListResponse,
    CustomerPaymentBehaviorResponse,
    CustomerRecoveryHistoryResponse,
    CustomerUpdateRequest,
)
from backend.app.schemas.transactions import TransactionListItem, TransactionListResponse
from backend.app.services.customer_intelligence import (
    compute_customer_intelligence,
    create_customer,
    extract_customer_features,
    get_customer_detail,
    get_customer_payment_behavior,
    get_customer_recovery_history,
    list_customers,
    update_customer,
)

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])


@router.get("", response_model=CustomerListResponse, summary="List customers with intelligence metrics")
def get_customers(
    merchant_id: str | None = Query(default=None, description="Filter by merchant ID"),
    risk_segment: str | None = Query(default=None, description="Filter by risk tier (VIP, STANDARD, HIGH_RISK, NEW)"),
    search: str | None = Query(default=None, description="Search by name, email, or external customer ID"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> CustomerListResponse:
    """Retrieve paginated customer directory with behavioral segment, lifetime spend, and success rate."""
    total, items = list_customers(
        session=db,
        merchant_id=merchant_id,
        risk_segment=risk_segment,
        search=search,
        limit=limit,
        offset=offset,
    )
    return CustomerListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=CustomerDetailResponse, status_code=status.HTTP_201_CREATED, summary="Register customer profile")
def register_customer(
    data: CustomerCreateRequest,
    db: Session = Depends(get_db),
) -> CustomerDetailResponse:
    """Create a new customer profile and initialize intelligence records."""
    try:
        customer = create_customer(db, data)
        db.commit()
        return get_customer_detail(db, customer.id)
    except ValueError as ex:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))


@router.get("/{customer_id}", response_model=CustomerDetailResponse, summary="Get customer profile and intelligence")
def get_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
) -> CustomerDetailResponse:
    """Fetch complete customer profile, lifetime metrics, behavioral segment, and payment statistics."""
    try:
        return get_customer_detail(db, customer_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer {customer_id} not found",
        )


@router.patch("/{customer_id}", response_model=CustomerDetailResponse, summary="Update customer profile preferences")
def patch_customer(
    customer_id: UUID,
    data: CustomerUpdateRequest,
    db: Session = Depends(get_db),
) -> CustomerDetailResponse:
    """Update contact information, preferred payment method, or risk segment."""
    try:
        customer = update_customer(db, customer_id, data)
        db.commit()
        return get_customer_detail(db, customer.id)
    except ValueError as ex:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))


@router.get("/{customer_id}/transactions", response_model=TransactionListResponse, summary="Get customer transaction history")
def get_customer_transactions(
    customer_id: UUID,
    status_filter: str | None = Query(default=None, alias="status", description="Filter by status (SUCCEEDED, FAILED)"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> TransactionListResponse:
    """Retrieve full transaction lifecycle history and attempt records for a specific customer."""
    customer = db.scalar(select(Customer).where(Customer.id == customer_id))
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer {customer_id} not found")

    stmt = (
        select(Transaction)
        .options(joinedload(Transaction.attempts))
        .where(Transaction.customer_id == customer_id)
    )
    count_stmt = select(func.count(Transaction.id)).where(Transaction.customer_id == customer_id)

    if status_filter:
        stmt = stmt.where(Transaction.status == status_filter.upper())
        count_stmt = count_stmt.where(Transaction.status == status_filter.upper())

    total = db.scalar(count_stmt) or 0
    txns = db.scalars(stmt.order_by(Transaction.created_at.desc()).offset(offset).limit(limit)).unique().all()

    items: list[TransactionListItem] = []
    for txn in txns:
        latest_att = txn.attempts[-1] if txn.attempts else None
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
                latest_failure_code=latest_att.failure_code if latest_att else None,
                latest_payment_method=latest_att.payment_method if latest_att else None,
                created_at=txn.created_at,
                updated_at=txn.updated_at,
            )
        )

    return TransactionListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/{customer_id}/payment-behavior",
    response_model=CustomerPaymentBehaviorResponse,
    summary="Get customer payment behavior analytics",
)
def get_customer_behavior(
    customer_id: UUID,
    db: Session = Depends(get_db),
) -> CustomerPaymentBehaviorResponse:
    """Analyze customer payment instrument preferences, method success rates, and channel affinity."""
    try:
        return get_customer_payment_behavior(db, customer_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer {customer_id} not found",
        )


@router.get(
    "/{customer_id}/recovery-history",
    response_model=CustomerRecoveryHistoryResponse,
    summary="Get customer recovery cases and conversion history",
)
def get_customer_recovery(
    customer_id: UUID,
    db: Session = Depends(get_db),
) -> CustomerRecoveryHistoryResponse:
    """Inspect customer-level recovery cases, past recovery recommendations, and recovery conversion yield."""
    try:
        return get_customer_recovery_history(db, customer_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer {customer_id} not found",
        )


@router.get(
    "/{customer_id}/features",
    response_model=CustomerFeaturesSnapshot,
    summary="Get normalized ML feature snapshot vector",
)
def get_customer_features_endpoint(
    customer_id: UUID,
    db: Session = Depends(get_db),
) -> CustomerFeaturesSnapshot:
    """Extract standardized point-in-time numerical feature array for ML scoring & decision engine."""
    try:
        return extract_customer_features(db, customer_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer {customer_id} not found",
        )


@router.post(
    "/{customer_id}/refresh",
    response_model=CustomerDetailResponse,
    summary="Force refresh customer intelligence calculations",
)
def refresh_customer_intelligence_endpoint(
    customer_id: UUID,
    db: Session = Depends(get_db),
) -> CustomerDetailResponse:
    """Recalculate customer lifetime GMV, success rates, streak, and behavioral segment."""
    try:
        compute_customer_intelligence(db, customer_id, persist=True)
        return get_customer_detail(db, customer_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer {customer_id} not found",
        )
