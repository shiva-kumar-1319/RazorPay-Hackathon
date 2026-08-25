"""REST API endpoints for simulating payment transactions, attempts, and scenarios."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.schemas.simulator import (
    BatchSimulationResponse,
    CreateSimulatedPaymentRequest,
    FailureCodeMetadata,
    PaymentSimulationResponse,
    ScenarioInfoResponse,
    ScenarioMetadata,
    SimulateAttemptRequest,
    SimulateBatchRequest,
)
from backend.app.simulator.constants import (
    FAILURE_CATALOG,
    Gateway,
    PaymentMethod,
    SCENARIO_PROFILES,
)
from backend.app.simulator.engine import PaymentSimulator

router = APIRouter(prefix="/api/v1/simulator", tags=["simulator"])


@router.post(
    "/payments",
    response_model=PaymentSimulationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Simulate a new payment transaction",
)
def create_simulated_payment(
    request: CreateSimulatedPaymentRequest, db: Session = Depends(get_db)
) -> PaymentSimulationResponse:
    """Create and simulate a realistic payment transaction and initial attempt."""
    try:
        simulator = PaymentSimulator(db)
        return simulator.simulate_payment(request)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Simulation failed: {str(exc)}",
        ) from exc


@router.post(
    "/payments/{transaction_id}/attempts",
    response_model=PaymentSimulationResponse,
    summary="Simulate a follow-up attempt on an existing transaction",
)
def simulate_additional_attempt(
    transaction_id: UUID,
    request: SimulateAttemptRequest,
    db: Session = Depends(get_db),
) -> PaymentSimulationResponse:
    """Execute a retry or payment-method switch attempt on an existing transaction."""
    try:
        simulator = PaymentSimulator(db)
        return simulator.simulate_attempt(transaction_id, request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Attempt simulation failed: {str(exc)}",
        ) from exc


@router.post(
    "/batch",
    response_model=BatchSimulationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Simulate a batch of transactions",
)
def simulate_batch_payments(
    request: SimulateBatchRequest, db: Session = Depends(get_db)
) -> BatchSimulationResponse:
    """Generate a batch of realistic transactions under a specified scenario."""
    try:
        simulator = PaymentSimulator(db)
        return simulator.simulate_batch(request)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch simulation failed: {str(exc)}",
        ) from exc


@router.get(
    "/scenarios",
    response_model=ScenarioInfoResponse,
    summary="List available simulation presets, payment methods, and failure codes",
)
def get_simulation_scenarios() -> ScenarioInfoResponse:
    """Retrieve metadata of available simulation profiles, failure codes, and payment methods."""
    scenarios_list = [
        ScenarioMetadata(
            name=scenario_name.value,
            description=cfg["description"],
            default_success_rate=cfg["success_rate"],
            method_weights={m.value if hasattr(m, "value") else str(m): w for m, w in cfg["method_weights"].items()},
            failure_weights=cfg["failure_weights"],
        )
        for scenario_name, cfg in SCENARIO_PROFILES.items()
    ]

    failure_codes_list = [
        FailureCodeMetadata(
            code=def_.code,
            category=def_.category,
            description=def_.description,
            recoverable=def_.recoverable,
            typical_methods=list(def_.typical_methods),
            default_error_message=def_.default_error_message,
        )
        for def_ in FAILURE_CATALOG.values()
    ]

    return ScenarioInfoResponse(
        scenarios=scenarios_list,
        failure_codes=failure_codes_list,
        payment_methods=[m.value for m in PaymentMethod],
        gateways=[g.value for g in Gateway],
    )
