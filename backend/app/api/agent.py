"""REST API endpoints for the Bounded Tool-Calling Payment Recovery Agent."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models.recovery import AuditLog, Transaction
from backend.app.schemas.agent import (
    AgentInvestigationRequest,
    AgentInvestigationResponse,
    AgentPlanRequest,
    AgentRecoveryPlan,
    AgentToolCatalogResponse,
    ToolCallRequest,
    ToolCallResult,
)
from backend.app.services.agent_tools import agent_tool_registry, tool_create_recovery_plan
from backend.app.services.recovery_agent import payment_recovery_agent

logger = logging.getLogger("recoverx.api.agent")

router = APIRouter(prefix="/api/v1/agent", tags=["Recovery Agent"])


@router.get(
    "/tools",
    response_model=AgentToolCatalogResponse,
    summary="List Allow-Listed Agent Tools",
    description="Retrieve all registered allow-listed tools, input parameter schemas, and safety guardrails.",
)
def list_agent_tools() -> AgentToolCatalogResponse:
    """Return catalog of registered allow-listed tools."""
    return agent_tool_registry.get_catalog()


@router.post(
    "/tools/execute",
    response_model=ToolCallResult,
    summary="Execute an Allow-Listed Tool",
    description="Execute an individual allow-listed tool with strict schema validation and safety isolation.",
)
def execute_tool_endpoint(
    payload: ToolCallRequest,
    db: Session = Depends(get_db),
) -> ToolCallResult:
    """Execute a single allow-listed tool."""
    res = agent_tool_registry.execute_tool(db, payload.tool_name, payload.arguments)
    if not res.success and "Disallowed tool" in (res.error or ""):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res.error)
    return res


@router.post(
    "/investigate",
    response_model=AgentInvestigationResponse,
    summary="Autonomous Failure Investigation",
    description="Run the Payment Recovery Agent autonomously to investigate failure, score candidate actions, plan bounded recovery, and write audit explanations.",
)
def investigate_transaction_endpoint(
    payload: AgentInvestigationRequest,
    db: Session = Depends(get_db),
) -> AgentInvestigationResponse:
    """Investigate a transaction failure using autonomous tool calling."""
    try:
        txn_uuid = UUID(payload.transaction_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid transaction UUID: {payload.transaction_id}")

    txn = db.scalar(select(Transaction).where(Transaction.id == txn_uuid))
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transaction {payload.transaction_id} not found")

    return payment_recovery_agent.investigate_transaction(
        session=db,
        transaction_id=txn_uuid,
        override_failure_code=payload.override_failure_code,
        execute_bounded_action=payload.execute_bounded_action,
    )


@router.post(
    "/plan",
    response_model=AgentRecoveryPlan,
    summary="Create Bounded Recovery Plan",
    description="Create or validate a structured recovery plan for a transaction, enforcing policy constraints.",
)
def create_plan_endpoint(
    payload: AgentPlanRequest,
    db: Session = Depends(get_db),
) -> AgentRecoveryPlan:
    """Create a structured recovery plan."""
    try:
        txn_uuid = UUID(payload.transaction_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid transaction UUID: {payload.transaction_id}")

    try:
        plan = tool_create_recovery_plan(
            session=db,
            transaction_id=txn_uuid,
            chosen_action=payload.chosen_action,
            confidence_score=payload.confidence_score,
            reason_codes=payload.reason_codes,
            fallback_action=payload.fallback_action,
            parameters=payload.parameters,
        )
        db.commit()
        return plan
    except ValueError as ex:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))


@router.get(
    "/traces/{transaction_id}",
    response_model=list[dict[str, Any]],
    summary="Get Agent Audit Traces",
    description="Retrieve all historical agent decision traces and audit explanations for a transaction.",
)
def get_agent_traces_endpoint(
    transaction_id: str,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Fetch past agent audit logs for a transaction."""
    try:
        txn_uuid = UUID(transaction_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid transaction UUID: {transaction_id}")

    logs = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.transaction_id == txn_uuid,
            AuditLog.actor == "payment_recovery_agent",
        )
        .order_by(AuditLog.created_at.asc())
    ).all()

    return [
        {
            "audit_id": str(log.id),
            "transaction_id": str(log.transaction_id),
            "event_type": log.event_type,
            "actor": log.actor,
            "reason_codes": log.reason_codes,
            "metadata": log.metadata_,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
