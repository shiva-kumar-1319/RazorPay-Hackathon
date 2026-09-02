"""Evaluation & Business Proof REST API endpoints for RecoverX.

Day 13 deliverable: provides endpoints for baseline vs RecoverX benchmarks,
business proof ROI calculations, stopping rules compliance verification,
and tamper-evident audit trail reconstruction.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.schemas.evaluation import (
    AuditTrailResponse,
    BenchmarkComparisonResponse,
    BenchmarkRunRequest,
    BusinessProofSummaryResponse,
    StoppingRulesResponse,
)
from backend.app.services.evaluation_service import evaluation_service

router = APIRouter(prefix="/api/v1/evaluation", tags=["Evaluation & Business Proof"])


@router.post("/run-benchmark", response_model=BenchmarkComparisonResponse)
def run_benchmark_evaluation(
    payload: BenchmarkRunRequest,
    db: Session = Depends(get_db),
) -> BenchmarkComparisonResponse:
    """Run a comparative benchmark simulation comparing:

    1. No Action (Baseline 0)
    2. Blind Retry (Naive same-method retry)
    3. Rule-Based Heuristic (Deterministic heuristics)
    4. RecoverX AI (Failure intelligence + ML probability + Net EV + Smart routing + Stopping rules)
    """
    return evaluation_service.run_benchmark(
        session=db,
        merchant_id=payload.merchant_id,
        num_transactions=payload.num_transactions,
        scenarios=payload.scenarios,
        seed=payload.seed,
    )


@router.get("/business-proof", response_model=BusinessProofSummaryResponse)
def get_business_proof(
    merchant_id: str = Query("merch_101", description="Merchant tenant identifier"),
    db: Session = Depends(get_db),
) -> BusinessProofSummaryResponse:
    """Fetch executive business proof metrics: Total recovered GMV, net recovery efficiency %,

    incremental revenue gain, ROI multiplier, cost-to-recover ratio, and friction reduction.
    """
    return evaluation_service.get_business_proof_summary(
        session=db,
        merchant_id=merchant_id,
    )


@router.get("/stopping-rules", response_model=StoppingRulesResponse)
def verify_stopping_rules(
    merchant_id: str = Query("merch_101", description="Merchant tenant identifier"),
    db: Session = Depends(get_db),
) -> StoppingRulesResponse:
    """Audit and verify 100% compliance across all 6 core safety stopping rules:

    1. Hard Failure Terminal Stop
    2. Max Attempt Ceiling Limit
    3. Negative Expected Value Abort Guard
    4. Double-Billing & Succeeded Terminal Guard
    5. Tokenized Link Expiry TTL Guard
    6. Consecutive Timeout Exponential Backoff Guard
    """
    return evaluation_service.verify_stopping_rules(
        session=db,
        merchant_id=merchant_id,
    )


@router.get("/audit-trail/{transaction_id}", response_model=AuditTrailResponse)
def get_transaction_audit_trail(
    transaction_id: str,
    db: Session = Depends(get_db),
) -> AuditTrailResponse:
    """Fetch complete chronological cryptographic audit timeline for a transaction.

    Includes actor stamps, tool execution traces, policy versions, and SHA-256 integrity hashes.
    """
    try:
        return evaluation_service.get_transaction_audit_trail(
            session=db,
            transaction_id=transaction_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/batch-simulate", response_model=BenchmarkComparisonResponse)
def batch_simulate_evaluation(
    payload: BenchmarkRunRequest,
    db: Session = Depends(get_db),
) -> BenchmarkComparisonResponse:
    """Run interactive batch simulation with custom configuration and produce comparative benchmark."""
    return evaluation_service.run_benchmark(
        session=db,
        merchant_id=payload.merchant_id,
        num_transactions=payload.num_transactions,
        scenarios=payload.scenarios,
        seed=payload.seed,
    )
