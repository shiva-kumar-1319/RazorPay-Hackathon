"""Dashboard REST API endpoints for RecoverX Real-Time Analytics & Projections."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.schemas.dashboard import (
    AgentDecisionsResponse,
    DashboardFunnelResponse,
    DashboardOverviewMetrics,
    LiveFailedPaymentsResponse,
    ModelHealthResponse,
    RecoveryAttemptsResponse,
    SimulateBatchRequest,
    SimulateBatchResponse,
)
from backend.app.services.dashboard_service import dashboard_service

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverviewMetrics)
def get_dashboard_overview(
    merchant_id: str = Query("merch_101", description="Merchant tenant identifier"),
    date_from: datetime | None = Query(None, description="Start timestamp (UTC)"),
    date_to: datetime | None = Query(None, description="End timestamp (UTC)"),
    db: Session = Depends(get_db),
) -> DashboardOverviewMetrics:
    """Fetch high-level merchant KPIs including failed GMV, recovered GMV, recovery rate, friction, and trends."""
    return dashboard_service.get_overview_metrics(
        session=db,
        merchant_id=merchant_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/funnel", response_model=DashboardFunnelResponse)
def get_recovery_funnel(
    merchant_id: str = Query("merch_101", description="Merchant tenant identifier"),
    date_from: datetime | None = Query(None, description="Start timestamp (UTC)"),
    date_to: datetime | None = Query(None, description="End timestamp (UTC)"),
    db: Session = Depends(get_db),
) -> DashboardFunnelResponse:
    """Fetch recovery conversion funnel segmented by failure category and payment methods."""
    return dashboard_service.get_recovery_funnel(
        session=db,
        merchant_id=merchant_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/live-failed-payments", response_model=LiveFailedPaymentsResponse)
def get_live_failed_payments(
    merchant_id: str = Query("merch_101", description="Merchant tenant identifier"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    category: str | None = Query(None, description="Filter by failure category (TEMPORARY, PAYMENT_METHOD, CUSTOMER_ACTION, HARD_FAILURE)"),
    state: str | None = Query(None, description="Filter by recovery state (OPEN, SCHEDULED, RECOVERED, STOPPED, NEEDS_REVIEW)"),
    db: Session = Depends(get_db),
) -> LiveFailedPaymentsResponse:
    """Fetch live feed of failed payment transactions with PII masking and classification."""
    return dashboard_service.get_live_failed_payments(
        session=db,
        merchant_id=merchant_id,
        limit=limit,
        offset=offset,
        category=category,
        state=state,
    )


@router.get("/agent-decisions", response_model=AgentDecisionsResponse)
def get_agent_decisions(
    merchant_id: str = Query("merch_101", description="Merchant tenant identifier"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> AgentDecisionsResponse:
    """Fetch live stream of autonomous recovery agent decisions, tool investigations, and reasoning traces."""
    return dashboard_service.get_agent_decisions_feed(
        session=db,
        merchant_id=merchant_id,
        limit=limit,
    )


@router.get("/recovery-attempts", response_model=RecoveryAttemptsResponse)
def get_recovery_attempts(
    merchant_id: str = Query("merch_101", description="Merchant tenant identifier"),
    limit: int = Query(50, ge=1, le=200),
    workflow: str | None = Query(None, description="Filter by workflow (IMMEDIATE_RETRY, METHOD_SWITCH, DELAYED_RETRY, PAYMENT_LINK, STOP_RECOVERY)"),
    db: Session = Depends(get_db),
) -> RecoveryAttemptsResponse:
    """Fetch granular logs of recovery workflow executions across retry, switch, scheduler, and payment links."""
    return dashboard_service.get_recovery_attempts_feed(
        session=db,
        merchant_id=merchant_id,
        limit=limit,
        workflow=workflow,
    )


@router.get("/model-health", response_model=ModelHealthResponse)
def get_model_health(
    merchant_id: str = Query("merch_101", description="Merchant tenant identifier"),
    db: Session = Depends(get_db),
) -> ModelHealthResponse:
    """Fetch ML prediction model accuracy, AUC-ROC, score distribution, and calibration curves."""
    return dashboard_service.get_model_health_projections(
        session=db,
        merchant_id=merchant_id,
    )


@router.post("/simulate-live-batch", response_model=SimulateBatchResponse)
def simulate_live_batch(
    payload: SimulateBatchRequest,
    db: Session = Depends(get_db),
) -> SimulateBatchResponse:
    """Simulate a live stream of realistic payment failures, run agent investigations, and execute recoveries."""
    return dashboard_service.simulate_live_batch(
        session=db,
        merchant_id=payload.merchant_id,
        count=payload.count,
        auto_investigate=payload.auto_investigate,
        auto_execute=payload.auto_execute,
    )
