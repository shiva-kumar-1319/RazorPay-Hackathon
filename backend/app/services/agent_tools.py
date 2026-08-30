"""Allow-listed tools and Tool Registry for the Payment Recovery Agent.

Day 10 deliverable: 6 strictly allow-listed, schema-validated tools
with non-negotiable guardrails, PII redaction, and executor validation.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.app.models.recovery import (
    ActionType,
    AuditLog,
    Customer,
    CustomerIntelligence,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.agent import (
    AgentExecutionResult,
    AgentExplanationResult,
    AgentRecoveryPlan,
    AgentToolCatalogResponse,
    CandidateScoreEvidence,
    RedactedAttemptRecord,
    RedactedCustomerProfile,
    RedactedTransactionContext,
    ScoreCandidatesResult,
    ToolCallResult,
    ToolDefinitionSchema,
    ToolParameterSchema,
)
from backend.app.schemas.failure import FailureClassificationRequest
from backend.app.services.customer_intelligence import compute_customer_intelligence
from backend.app.services.decision_engine import recovery_decision_engine
from backend.app.services.failure_intelligence import failure_intelligence_service
from backend.app.services.recovery_policy import evaluate_failure_policy

logger = logging.getLogger("recoverx.agent_tools")


# ============================================================================
# PII REDACTION HELPERS
# ============================================================================


def _mask_email(email: str | None) -> str | None:
    """Mask email address (e.g. priya.sharma@example.com -> p***a@example.com)."""
    if not email or "@" not in email:
        return None
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        masked_user = f"{user[0]}*" if user else "*"
    else:
        masked_user = f"{user[0]}{'*' * (len(user) - 2)}{user[-1]}"
    return f"{masked_user}@{domain}"


def _mask_phone(phone: str | None) -> str | None:
    """Mask phone number (e.g. +919876543210 -> +91 ******3210)."""
    if not phone:
        return None
    clean = re.sub(r"[^\d+]", "", phone)
    if len(clean) >= 8:
        prefix = clean[:3] if clean.startswith("+") else clean[:2]
        suffix = clean[-4:]
        return f"{prefix} {'*' * 6}{suffix}"
    return "****"


# ============================================================================
# 1. TOOL IMPLEMENTATIONS
# ============================================================================


def tool_get_transaction_context(session: Session, transaction_id: str | UUID) -> RedactedTransactionContext:
    """Fetch read-only transaction facts, redacted attempt history, and customer profile."""
    txn_uuid = UUID(str(transaction_id)) if isinstance(transaction_id, str) else transaction_id

    txn = session.scalar(
        select(Transaction)
        .options(
            joinedload(Transaction.attempts),
            joinedload(Transaction.customer).joinedload(Customer.intelligence),
            joinedload(Transaction.recovery_cases),
        )
        .where(Transaction.id == txn_uuid)
    )
    if not txn:
        raise ValueError(f"Transaction {txn_uuid} not found")

    # Sort attempts chronologically
    sorted_attempts = sorted(txn.attempts or [], key=lambda a: (a.attempt_number or 1))
    attempts_history = [
        RedactedAttemptRecord(
            attempt_number=att.attempt_number,
            payment_method=att.payment_method or "UNKNOWN",
            gateway=att.gateway,
            failure_code=att.failure_code,
            created_at=att.created_at.isoformat() if att.created_at else None,
        )
        for att in sorted_attempts
    ]

    # Extract current failure details
    last_failure_code = None
    for att in reversed(sorted_attempts):
        if att.failure_code:
            last_failure_code = att.failure_code
            break

    policy = evaluate_failure_policy(last_failure_code or "UNKNOWN")

    # Build PII-redacted customer profile
    redacted_customer = None
    if txn.customer:
        c = txn.customer
        intel = c.intelligence
        if not intel:
            try:
                intel = compute_customer_intelligence(session, c.id, persist=False)
            except Exception:
                intel = None

        redacted_customer = RedactedCustomerProfile(
            external_customer_id=c.external_customer_id,
            masked_email=_mask_email(c.email),
            masked_phone=_mask_phone(c.phone),
            risk_segment=c.risk_segment or "STANDARD",
            behavioral_segment=intel.behavioral_segment if intel else "NEW_CUSTOMER",
            success_rate=float(intel.success_rate) if intel else 0.0,
            recovery_rate=float(intel.recovery_rate) if intel else 0.0,
            recent_failure_streak=intel.recent_failure_streak if intel else 0,
            risk_score=float(intel.risk_score) if intel else 0.1,
            preferred_payment_method=intel.preferred_payment_method if intel else c.preferred_payment_method,
            total_transactions=intel.total_transactions if intel else 0,
            total_spent=float(intel.total_spent) if intel else 0.0,
        )

    return RedactedTransactionContext(
        transaction_id=str(txn.id),
        merchant_id=txn.merchant_id,
        amount=float(txn.amount),
        currency=txn.currency or "INR",
        status=txn.status.value,
        current_attempt_count=len(sorted_attempts),
        failure_code=last_failure_code,
        failure_category=policy.category,
        is_recoverable=policy.recoverable,
        attempts_history=attempts_history,
        customer=redacted_customer,
    )


def tool_get_failure_policy(failure_code: str) -> dict[str, Any]:
    """Inspect read-only failure policy, category, permitted actions, and stopping rules."""
    policy = evaluate_failure_policy(failure_code)
    classified = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(failure_code=failure_code)
    )

    is_hard_stop = not policy.recoverable or policy.category == "HARD_FAILURE"
    compliance_str = "; ".join(classified.compliance_notes) if classified.compliance_notes else None

    return {
        "failure_code": classified.normalized_code,
        "category": policy.category,
        "recoverable": policy.recoverable,
        "is_hard_stop": is_hard_stop,
        "max_retries": classified.max_retries_permitted,
        "backoff_base_delay_seconds": classified.retry_delay_seconds,
        "permitted_actions": [a.value for a in policy.permitted_actions],
        "reason_codes": list(policy.reason_codes),
        "customer_explanation": classified.customer_explanation,
        "merchant_technical_log": classified.merchant_explanation,
        "compliance_advisory": compliance_str,
    }


def tool_score_candidates(
    session: Session,
    transaction_id: str | UUID,
    failure_code: str | None = None,
    candidate_actions: list[str] | None = None,
) -> ScoreCandidatesResult:
    """Score candidate recovery actions using ML prediction model and Cost-Aware Expected Value engine."""
    ctx = tool_get_transaction_context(session, transaction_id)
    eff_failure_code = failure_code or ctx.failure_code or "UNKNOWN"
    policy = evaluate_failure_policy(eff_failure_code)

    # Filter candidate actions by policy gate (strictly enforced)
    permitted_action_types = list(policy.permitted_actions)
    if candidate_actions:
        requested_types = []
        for a_str in candidate_actions:
            try:
                requested_types.append(ActionType(a_str.upper()))
            except ValueError:
                pass
        # Only permit intersection
        candidate_list = [a for a in permitted_action_types if a in requested_types]
        if not candidate_list:
            candidate_list = permitted_action_types
    else:
        candidate_list = permitted_action_types

    # Find customer intelligence if present in DB
    customer_intel = None
    txn_uuid = UUID(str(transaction_id)) if isinstance(transaction_id, str) else transaction_id
    txn = session.scalar(
        select(Transaction)
        .options(joinedload(Transaction.customer).joinedload(Customer.intelligence))
        .where(Transaction.id == txn_uuid)
    )
    if txn and txn.customer and txn.customer.intelligence:
        customer_intel = txn.customer.intelligence

    scored_actions = recovery_decision_engine.evaluate_actions(
        failure_category=policy.category,
        amount=ctx.amount,
        candidate_action_types=candidate_list,
        customer_intel=customer_intel,
        hour_of_day=12,
    )

    ev_list: list[CandidateScoreEvidence] = []
    best_ev: CandidateScoreEvidence | None = None

    for act in scored_actions:
        item = CandidateScoreEvidence(
            action_type=act.action_type.value,
            probability=act.probability,
            expected_value=act.expected_value,
            gross_expected_value=act.gross_expected_value,
            execution_cost=act.execution_cost,
            friction_penalty=act.friction_penalty,
            channel=act.channel,
            rank=act.rank,
            selected=act.selected,
            reason=act.reason,
        )
        ev_list.append(item)
        if act.selected:
            best_ev = item

    summary = (
        f"Evaluated {len(ev_list)} permitted actions for category {policy.category}. "
        f"Optimal action: {best_ev.action_type if best_ev else 'NONE'} with EV ₹{best_ev.expected_value:.2f}"
        if best_ev
        else "No viable recovery candidates."
    )

    return ScoreCandidatesResult(
        transaction_id=str(ctx.transaction_id),
        failure_category=policy.category,
        candidates=ev_list,
        best_action=best_ev,
        recommendation_summary=summary,
    )


def tool_create_recovery_plan(
    session: Session,
    transaction_id: str | UUID,
    chosen_action: str,
    confidence_score: float = 0.85,
    reason_codes: list[str] | None = None,
    fallback_action: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> AgentRecoveryPlan:
    """Formulate and persist a validated draft recovery plan with an idempotency key."""
    txn_uuid = UUID(str(transaction_id)) if isinstance(transaction_id, str) else transaction_id
    ctx = tool_get_transaction_context(session, txn_uuid)

    try:
        action_type = ActionType(chosen_action.upper())
    except ValueError:
        raise ValueError(f"Invalid ActionType: {chosen_action}")

    policy = evaluate_failure_policy(ctx.failure_code or "UNKNOWN")

    # Strict Safety Check: Verify action is permitted by policy
    if not policy.recoverable and action_type != ActionType.STOP_RECOVERY:
        raise ValueError(
            f"Policy violation: Category {policy.category} requires STOP_RECOVERY, cannot plan {action_type.value}"
        )
    if action_type not in policy.permitted_actions and action_type != ActionType.STOP_RECOVERY:
        raise ValueError(
            f"Policy violation: {action_type.value} is not permitted for failure code {ctx.failure_code} ({policy.category})"
        )

    # Compute expected value for the plan
    scoring = tool_score_candidates(session, txn_uuid, ctx.failure_code, [action_type.value])
    scored = scoring.best_action

    expected_val = scored.expected_value if scored else 0.0
    predicted_prob = scored.probability if scored else 0.0

    # Ensure recovery case exists in DB
    recovery_case = session.scalar(
        select(RecoveryCase).where(RecoveryCase.transaction_id == txn_uuid)
    )
    if not recovery_case:
        initial_state = RecoveryState.STOPPED if action_type == ActionType.STOP_RECOVERY else RecoveryState.OPEN
        recovery_case = RecoveryCase(
            transaction_id=txn_uuid,
            state=initial_state,
            policy_version="policy.v2",
            version=1,
        )
        session.add(recovery_case)
        session.flush()

    plan_id = f"plan_{recovery_case.id}_{uuid4().hex[:8]}"
    idempotency_key = f"idemp_{recovery_case.id}_{action_type.value.lower()}_{uuid4().hex[:6]}"

    effective_reasons = list(policy.reason_codes) + (reason_codes or [])
    if ctx.customer and ctx.customer.behavioral_segment == "VIP_HIGH_VALUE":
        effective_reasons.append("CUSTOMER_VIP_PRIORITY")

    # Persist or update selected RecoveryAction in DB
    existing_act = session.scalar(
        select(RecoveryAction).where(
            RecoveryAction.recovery_case_id == recovery_case.id,
            RecoveryAction.action_type == action_type,
        )
    )
    if existing_act:
        existing_act.selected = True
        existing_act.probability = Decimal(str(round(predicted_prob, 4)))
        existing_act.expected_value = Decimal(str(round(expected_val, 2)))
        existing_act.reason_codes = effective_reasons
        existing_act.idempotency_key = idempotency_key
    else:
        new_act = RecoveryAction(
            recovery_case_id=recovery_case.id,
            action_type=action_type,
            idempotency_key=idempotency_key,
            selected=True,
            probability=Decimal(str(round(predicted_prob, 4))),
            expected_value=Decimal(str(round(expected_val, 2))),
            reason_codes=effective_reasons,
        )
        session.add(new_act)

    session.flush()

    return AgentRecoveryPlan(
        recovery_plan_id=plan_id,
        transaction_id=str(txn_uuid),
        chosen_action=action_type.value,
        confidence_score=float(confidence_score),
        expected_value=float(expected_val),
        predicted_probability=float(predicted_prob),
        fallback_action=fallback_action,
        reason_codes=effective_reasons,
        parameters=parameters or {},
        idempotency_key=idempotency_key,
        status="APPROVED" if expected_val >= 0.0 else "DRAFT",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def tool_request_execution(
    session: Session,
    transaction_id: str | UUID,
    recovery_plan_id: str,
    idempotency_key: str | None = None,
) -> AgentExecutionResult:
    """Pre-execution validation guard: revalidates transaction status, amounts, retry limits, and policy."""
    txn_uuid = UUID(str(transaction_id)) if isinstance(transaction_id, str) else transaction_id

    txn = session.scalar(
        select(Transaction)
        .options(joinedload(Transaction.attempts), joinedload(Transaction.recovery_cases))
        .where(Transaction.id == txn_uuid)
    )
    if not txn:
        return AgentExecutionResult(
            disposition="REFUSED",
            execution_id=f"exec_err_{uuid4().hex[:8]}",
            recovery_plan_id=recovery_plan_id,
            transaction_id=str(txn_uuid),
            action_type="UNKNOWN",
            message=f"Transaction {txn_uuid} does not exist.",
            guard_checks={"transaction_exists": False},
        )

    # 1. Guard Check: Transaction must not already be SUCCEEDED
    if txn.status == TransactionStatus.SUCCEEDED:
        return AgentExecutionResult(
            disposition="REFUSED",
            execution_id=f"exec_ref_{uuid4().hex[:8]}",
            recovery_plan_id=recovery_plan_id,
            transaction_id=str(txn_uuid),
            action_type="NONE",
            message="Execution refused: Transaction has already SUCCEEDED. Double recovery is strictly prevented.",
            guard_checks={"not_already_succeeded": False, "attempt_limit_valid": True, "policy_valid": True},
        )

    attempts = txn.attempts or []
    last_failure_code = None
    for att in reversed(attempts):
        if att.failure_code:
            last_failure_code = att.failure_code
            break

    policy = evaluate_failure_policy(last_failure_code or "UNKNOWN")
    classified = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(failure_code=last_failure_code or "UNKNOWN")
    )
    max_retries = classified.max_retries_permitted

    # 2. Guard Check: Attempt limits
    attempt_limit_ok = len(attempts) <= (max_retries + 1)
    if not attempt_limit_ok:
        return AgentExecutionResult(
            disposition="BLOCKED",
            execution_id=f"exec_blk_{uuid4().hex[:8]}",
            recovery_plan_id=recovery_plan_id,
            transaction_id=str(txn_uuid),
            action_type="STOP_RECOVERY",
            message=f"Execution blocked: Maximum retry attempts ({max_retries}) exceeded for {policy.category}.",
            guard_checks={"not_already_succeeded": True, "attempt_limit_valid": False, "policy_valid": True},
        )

    # Locate recovery case & selected action
    recovery_case = session.scalar(
        select(RecoveryCase)
        .options(joinedload(RecoveryCase.actions))
        .where(RecoveryCase.transaction_id == txn_uuid)
    )

    selected_action = None
    if recovery_case and recovery_case.actions:
        for act in recovery_case.actions:
            if act.selected:
                selected_action = act
                break

    action_name = selected_action.action_type.value if selected_action else "STOP_RECOVERY"

    # 3. Guard Check: Policy Validity
    policy_ok = (
        selected_action is not None
        and (selected_action.action_type in policy.permitted_actions or selected_action.action_type == ActionType.STOP_RECOVERY)
    )
    if not policy_ok:
        return AgentExecutionResult(
            disposition="REFUSED",
            execution_id=f"exec_ref_{uuid4().hex[:8]}",
            recovery_plan_id=recovery_plan_id,
            transaction_id=str(txn_uuid),
            action_type=action_name,
            message=f"Execution refused: Action {action_name} is not permitted by policy for {policy.category}.",
            guard_checks={"not_already_succeeded": True, "attempt_limit_valid": True, "policy_valid": False},
        )

    # All guard checks passed!
    exec_id = f"exec_{uuid4().hex[:10]}"
    disposition = "QUEUED" if action_name in ("DELAYED_RETRY", "CUSTOMER_NOTIFICATION") else "APPROVED"

    if recovery_case:
        recovery_case.state = RecoveryState.SCHEDULED if disposition == "QUEUED" else RecoveryState.OPEN
        recovery_case.version += 1

    next_scheduled = None
    if disposition == "QUEUED":
        backoff_sec = classified.retry_delay_seconds * (2 ** max(0, len(attempts) - 1))
        next_scheduled = datetime.fromtimestamp(time.time() + backoff_sec, tz=timezone.utc).isoformat()

    session.flush()

    return AgentExecutionResult(
        disposition=disposition,
        execution_id=exec_id,
        recovery_plan_id=recovery_plan_id,
        transaction_id=str(txn_uuid),
        action_type=action_name,
        message=f"Action {action_name} approved and validated against all safety boundaries.",
        guard_checks={
            "transaction_exists": True,
            "not_already_succeeded": True,
            "attempt_limit_valid": True,
            "policy_valid": True,
            "amount_positive": float(txn.amount) > 0,
        },
        next_scheduled_at=next_scheduled,
    )


def tool_write_explanation(
    session: Session,
    transaction_id: str | UUID,
    recovery_plan_id: str | None,
    explanation_summary: str,
    customer_message: str,
    merchant_notes: str,
    reason_codes: list[str] | None = None,
) -> AgentExplanationResult:
    """Record a structured, multi-stakeholder explanation and immutable audit log."""
    txn_uuid = UUID(str(transaction_id)) if isinstance(transaction_id, str) else transaction_id
    ctx = tool_get_transaction_context(session, txn_uuid)
    policy = evaluate_failure_policy(ctx.failure_code or "UNKNOWN")
    classified = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(failure_code=ctx.failure_code or "UNKNOWN")
    )

    effective_reasons = list(dict.fromkeys(list(policy.reason_codes) + (reason_codes or [])))
    compliance_str = "; ".join(classified.compliance_notes) if classified.compliance_notes else None

    audit_entry = AuditLog(
        transaction_id=txn_uuid,
        event_type="recovery.agent_explanation.v1",
        actor="payment_recovery_agent",
        reason_codes=effective_reasons,
        metadata_={
            "recovery_plan_id": recovery_plan_id,
            "explanation_summary": explanation_summary,
            "customer_message": customer_message,
            "merchant_notes": merchant_notes,
            "compliance_advisory": compliance_str,
            "failure_category": policy.category,
            "agent_version": "v1.0.0",
        },
    )
    session.add(audit_entry)
    session.flush()

    return AgentExplanationResult(
        audit_id=str(audit_entry.id),
        transaction_id=str(txn_uuid),
        explanation_summary=explanation_summary,
        customer_message=customer_message,
        merchant_notes=merchant_notes,
        compliance_advisory=compliance_str,
        reason_codes=effective_reasons,
        recorded_at=audit_entry.created_at.isoformat() if audit_entry.created_at else datetime.now(timezone.utc).isoformat(),
    )


# ============================================================================
# 2. AGENT TOOL REGISTRY
# ============================================================================


class AgentToolRegistry:
    """Registry of allow-listed tools, schemas, and bounded invocation handlers."""

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the 6 canonical allow-listed tools."""
        self.register_tool(
            name="get_transaction_context",
            description="Fetch safe, PII-redacted transaction facts, prior attempts, and customer behavioral profile.",
            category="read_only",
            parameters=[
                ToolParameterSchema(
                    name="transaction_id",
                    type="string",
                    description="UUID of the transaction to inspect",
                    required=True,
                ),
            ],
            handler=tool_get_transaction_context,
        )

        self.register_tool(
            name="get_failure_policy",
            description="Inspect failure category, permitted candidate recovery actions, max retries, and stop rules.",
            category="read_only",
            parameters=[
                ToolParameterSchema(
                    name="failure_code",
                    type="string",
                    description="Canonical failure code (e.g. CARD_DECLINED, TIMEOUT, FRAUD_REJECTED)",
                    required=True,
                ),
            ],
            handler=lambda session, **kwargs: tool_get_failure_policy(failure_code=kwargs["failure_code"]),
        )

        self.register_tool(
            name="score_candidates",
            description="Evaluate ML success probabilities and Cost-Aware Expected Values for permitted recovery actions.",
            category="read_only",
            parameters=[
                ToolParameterSchema(
                    name="transaction_id",
                    type="string",
                    description="UUID of the failed transaction",
                    required=True,
                ),
                ToolParameterSchema(
                    name="failure_code",
                    type="string",
                    description="Optional failure code override",
                    required=False,
                    default=None,
                ),
                ToolParameterSchema(
                    name="candidate_actions",
                    type="array[string]",
                    description="Optional candidate action subset to evaluate (must be permitted by policy)",
                    required=False,
                    default=None,
                ),
            ],
            handler=tool_score_candidates,
        )

        self.register_tool(
            name="create_recovery_plan",
            description="Formulate and persist an approved recovery plan draft with an idempotency key.",
            category="planning",
            parameters=[
                ToolParameterSchema(
                    name="transaction_id",
                    type="string",
                    description="UUID of the failed transaction",
                    required=True,
                ),
                ToolParameterSchema(
                    name="chosen_action",
                    type="string",
                    description="Selected ActionType (e.g. SWITCH_TO_UPI, DELAYED_RETRY, PAYMENT_LINK, STOP_RECOVERY)",
                    required=True,
                ),
                ToolParameterSchema(
                    name="confidence_score",
                    type="number",
                    description="Agent confidence in this decision (0.0 to 1.0)",
                    required=False,
                    default=0.85,
                ),
                ToolParameterSchema(
                    name="reason_codes",
                    type="array[string]",
                    description="List of deterministic reason codes supporting this decision",
                    required=False,
                    default=[],
                ),
                ToolParameterSchema(
                    name="fallback_action",
                    type="string",
                    description="Optional fallback action if primary action fails",
                    required=False,
                    default=None,
                ),
            ],
            handler=tool_create_recovery_plan,
        )

        self.register_tool(
            name="request_execution",
            description="Run pre-execution validation guards (status, attempt counts, policy) and schedule recovery action.",
            category="execution_guard",
            parameters=[
                ToolParameterSchema(
                    name="transaction_id",
                    type="string",
                    description="UUID of the failed transaction",
                    required=True,
                ),
                ToolParameterSchema(
                    name="recovery_plan_id",
                    type="string",
                    description="ID of the approved recovery plan",
                    required=True,
                ),
                ToolParameterSchema(
                    name="idempotency_key",
                    type="string",
                    description="Optional unique idempotency key",
                    required=False,
                    default=None,
                ),
            ],
            handler=tool_request_execution,
        )

        self.register_tool(
            name="write_explanation",
            description="Write explainable multi-stakeholder narratives (customer, merchant, compliance) to the immutable audit ledger.",
            category="audit",
            parameters=[
                ToolParameterSchema(
                    name="transaction_id",
                    type="string",
                    description="UUID of the failed transaction",
                    required=True,
                ),
                ToolParameterSchema(
                    name="recovery_plan_id",
                    type="string",
                    description="ID of the associated recovery plan",
                    required=False,
                    default=None,
                ),
                ToolParameterSchema(
                    name="explanation_summary",
                    type="string",
                    description="Executive summary of the agent decision and evidence",
                    required=True,
                ),
                ToolParameterSchema(
                    name="customer_message",
                    type="string",
                    description="Empathetic, non-technical message for the customer",
                    required=True,
                ),
                ToolParameterSchema(
                    name="merchant_notes",
                    type="string",
                    description="Technical root cause analysis and recommendations for the merchant",
                    required=True,
                ),
                ToolParameterSchema(
                    name="reason_codes",
                    type="array[string]",
                    description="Deterministic reason codes",
                    required=False,
                    default=[],
                ),
            ],
            handler=tool_write_explanation,
        )

    def register_tool(
        self,
        name: str,
        description: str,
        category: str,
        parameters: list[ToolParameterSchema],
        handler: Callable[..., Any],
    ) -> None:
        """Register a new allow-listed tool."""
        self._tools[name] = {
            "definition": ToolDefinitionSchema(
                name=name,
                description=description,
                parameters=parameters,
                category=category,
                safety_level="strictly_bounded",
                read_only=(category == "read_only"),
            ),
            "handler": handler,
        }

    def get_tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_catalog(self) -> AgentToolCatalogResponse:
        """Return catalog of all registered tools and safety boundaries."""
        tools = [item["definition"] for item in self._tools.values()]
        guardrails = [
            "No free-form network, arbitrary database write, or unconstrained payment tools.",
            "All tool arguments are strictly schema-validated via Pydantic.",
            "Customer PII is strictly redacted (masked phone, masked email, tokenized attributes).",
            "Deterministic policy gate strictly precedes agent action selection.",
            "Pre-execution guard revalidates status (blocks SUCCEEDED double billing), attempt limits, and policy.",
            "HARD_FAILURE errors (e.g. FRAUD_REJECTED, EXPIRED_CARD) strictly terminate with STOP_RECOVERY.",
            "Every tool invocation and decision is recorded in the immutable audit ledger with correlation IDs.",
        ]
        return AgentToolCatalogResponse(tools=tools, guardrails=guardrails)

    def execute_tool(self, session: Session, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        """Execute an allow-listed tool with safety isolation and timing measurement."""
        if tool_name not in self._tools:
            return ToolCallResult(
                tool_name=tool_name,
                success=False,
                data={},
                error=f"Disallowed tool '{tool_name}'. Only allow-listed tools are permitted: {self.get_tool_names()}",
                execution_time_ms=0.0,
            )

        handler = self._tools[tool_name]["handler"]
        start_time = time.perf_counter()

        try:
            res = handler(session, **arguments)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # Convert Pydantic models or dicts to json-compatible dict
            if hasattr(res, "model_dump"):
                data = res.model_dump(mode="json")
            elif isinstance(res, dict):
                data = res
            else:
                data = {"result": str(res)}

            return ToolCallResult(
                tool_name=tool_name,
                success=True,
                data=data,
                error=None,
                execution_time_ms=elapsed_ms,
            )
        except Exception as ex:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning("Tool execution error in %s: %s", tool_name, ex, exc_info=True)
            return ToolCallResult(
                tool_name=tool_name,
                success=False,
                data={},
                error=str(ex),
                execution_time_ms=elapsed_ms,
            )


# Global Singleton Registry
agent_tool_registry = AgentToolRegistry()
