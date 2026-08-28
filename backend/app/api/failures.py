"""API endpoints for Failure Intelligence, classification, taxonomy lookups, and analytics."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.schemas.failure import (
    BatchFailureClassificationRequest,
    BatchFailureClassificationResponse,
    FailureAnalyticsResponse,
    FailureClassificationRequest,
    FailureIntelligenceDetail,
    FailureTaxonomyResponse,
)
from backend.app.services.failure_intelligence import (
    TAXONOMY_CATALOG,
    failure_intelligence_service,
)

router = APIRouter(prefix="/api/v1/failures", tags=["failures"])


@router.post("/classify", response_model=FailureIntelligenceDetail)
def classify_payment_failure(
    request: FailureClassificationRequest,
) -> FailureIntelligenceDetail:
    """Classify any payment failure code, gateway error, or raw message into canonical categories (TEMPORARY, PAYMENT_METHOD, CUSTOMER_ACTION, HARD_FAILURE)."""
    return failure_intelligence_service.classify_failure(request)


@router.post("/batch-classify", response_model=BatchFailureClassificationResponse)
def batch_classify_payment_failures(
    request: BatchFailureClassificationRequest,
) -> BatchFailureClassificationResponse:
    """Classify multiple payment failure payloads in bulk."""
    results = [
        failure_intelligence_service.classify_failure(item)
        for item in request.items
    ]
    return BatchFailureClassificationResponse(
        total_processed=len(results),
        results=results,
    )


@router.get("/taxonomy", response_model=FailureTaxonomyResponse)
def get_failure_taxonomy() -> FailureTaxonomyResponse:
    """Retrieve the full standardized RecoverX failure taxonomy, category classifications, gateway mappings, and retry limits."""
    return failure_intelligence_service.get_taxonomy()


@router.get("/analytics", response_model=FailureAnalyticsResponse)
def get_failure_analytics(
    db: Session = Depends(get_db),
) -> FailureAnalyticsResponse:
    """Calculate aggregated failure intelligence breakdown, recovery conversion by category, gateway/method failure rates, and transient anomaly alerts."""
    analytics_data = failure_intelligence_service.calculate_analytics(db)
    return FailureAnalyticsResponse(**analytics_data)


@router.get("/{failure_code}/explain", response_model=FailureIntelligenceDetail)
def explain_failure_code(
    failure_code: str,
) -> FailureIntelligenceDetail:
    """Get root cause diagnostics, merchant technical details, customer-friendly explanation, and recovery action strategy for a failure code."""
    detail = failure_intelligence_service.explain_code(failure_code)
    return detail
