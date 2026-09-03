"""Bounded Tool-Calling Payment Recovery Agent.

Day 10 deliverable: Autonomous tool-calling agent that investigates payment failures,
inspects policy gates, retrieves ML predictions & Expected Value scores, formulates
bounded recovery plans, validates executor guards, and writes explainable audit logs.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.recovery import AuditLog, OutboxEvent, Transaction
from backend.app.schemas.agent import (
    AgentExecutionResult,
    AgentExplanationResult,
    AgentInvestigationResponse,
    AgentRecoveryPlan,
    AgentStepTrace,
    ScoreCandidatesResult,
    ToolCallResult,
)
from backend.app.services.agent_tools import AgentToolRegistry, agent_tool_registry

logger = logging.getLogger("recoverx.recovery_agent")


class PaymentRecoveryAgent:
    """Bounded, tool-calling agent orchestrating payment failure investigation and recovery."""

    AGENT_ACTOR_NAME = "payment_recovery_agent"
    AGENT_VERSION = "v1.0.0"

    def __init__(self, tool_registry: AgentToolRegistry | None = None) -> None:
        self.tool_registry = tool_registry or agent_tool_registry

    def investigate_transaction(
        self,
        session: Session,
        transaction_id: str | UUID,
        override_failure_code: str | None = None,
        execute_bounded_action: bool = True,
    ) -> AgentInvestigationResponse:
        """Run an autonomous, bounded investigation loop for a failed payment transaction."""
        txn_uuid = UUID(str(transaction_id)) if isinstance(transaction_id, str) else transaction_id
        investigation_id = f"inv_{uuid4().hex[:10]}"
        start_time = time.perf_counter()

        steps: list[AgentStepTrace] = []
        audit_record_ids: list[str] = []
        step_counter = 1

        def _execute_step(thought: str, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
            nonlocal step_counter
            step_start = time.perf_counter()
            res = self.tool_registry.execute_tool(session, tool_name, arguments)
            step_duration = round((time.perf_counter() - step_start) * 1000, 2)

            steps.append(
                AgentStepTrace(
                    step_number=step_counter,
                    thought=thought,
                    tool_name=tool_name,
                    tool_arguments=arguments,
                    tool_result=res.data if res.success else {"error": res.error},
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    duration_ms=step_duration,
                )
            )
            step_counter += 1
            return res

        # --------------------------------------------------------------------
        # STEP 1: Inspect Transaction & Redacted Customer Context
        # --------------------------------------------------------------------
        ctx_res = _execute_step(
            thought="Investigate transaction failure facts, attempt history, and PII-redacted customer profile.",
            tool_name="get_transaction_context",
            arguments={"transaction_id": str(txn_uuid)},
        )
        if not ctx_res.success:
            total_duration = round((time.perf_counter() - start_time) * 1000, 2)
            return AgentInvestigationResponse(
                investigation_id=investigation_id,
                transaction_id=str(txn_uuid),
                status="NEEDS_REVIEW",
                failure_category="UNKNOWN",
                failure_code=override_failure_code or "UNKNOWN",
                chosen_action="STOP_RECOVERY",
                expected_value=0.0,
                predicted_probability=0.0,
                execution_disposition="REFUSED",
                customer_explanation="We were unable to locate your transaction details. Please contact customer support.",
                merchant_explanation=f"Investigation failed at Step 1: {ctx_res.error}",
                compliance_notes="Transaction context unavailable; recovery halted by default safety policy.",
                recovery_plan=None,
                steps=steps,
                audit_records=[],
                total_duration_ms=total_duration,
            )

        txn_ctx = ctx_res.data
        effective_failure_code = override_failure_code or txn_ctx.get("failure_code") or "UNKNOWN"

        # --------------------------------------------------------------------
        # STEP 2: Inspect Failure Policy & Category Boundaries
        # --------------------------------------------------------------------
        policy_res = _execute_step(
            thought=f"Check deterministic failure policy and category boundaries for failure code '{effective_failure_code}'.",
            tool_name="get_failure_policy",
            arguments={"failure_code": effective_failure_code},
        )
        policy_data = policy_res.data if policy_res.success else {}
        is_hard_stop = policy_data.get("is_hard_stop", False) or not policy_data.get("recoverable", True)
        category = policy_data.get("category", "TEMPORARY")
        customer_expl = policy_data.get("customer_explanation", "Payment could not be processed.")
        merchant_log = policy_data.get("merchant_technical_log", "Error occurred during payment processing.")
        compliance_advisory = policy_data.get("compliance_advisory")

        # --------------------------------------------------------------------
        # BRANCH A: HARD FAILURE / STOP RECOVERY
        # --------------------------------------------------------------------
        if is_hard_stop:
            plan_res = _execute_step(
                thought=f"Failure category is {category} (HARD_FAILURE). Enforcing strict terminal stop to prevent chargebacks and compliance violations.",
                tool_name="create_recovery_plan",
                arguments={
                    "transaction_id": str(txn_uuid),
                    "chosen_action": "STOP_RECOVERY",
                    "confidence_score": 1.0,
                    "reason_codes": policy_data.get("reason_codes", ["HARD_STOP_POLICY"]),
                },
            )
            plan_data = plan_res.data if plan_res.success else {}

            exec_res = _execute_step(
                thought="Execute bounded terminal stop verification via executor guard.",
                tool_name="request_execution",
                arguments={
                    "transaction_id": str(txn_uuid),
                    "recovery_plan_id": plan_data.get("recovery_plan_id", f"plan_stop_{txn_uuid}"),
                },
            )
            exec_data = exec_res.data if exec_res.success else {}

            explain_res = _execute_step(
                thought="Record terminal stop audit explanation and customer notification guidance.",
                tool_name="write_explanation",
                arguments={
                    "transaction_id": str(txn_uuid),
                    "recovery_plan_id": plan_data.get("recovery_plan_id"),
                    "explanation_summary": f"Hard failure ({effective_failure_code}). Stopped recovery immediately to prevent compliance risk.",
                    "customer_message": customer_expl,
                    "merchant_notes": f"HARD_STOP triggered: {merchant_log}",
                    "reason_codes": policy_data.get("reason_codes", ["HARD_STOP_POLICY"]),
                },
            )
            if explain_res.success and explain_res.data.get("audit_id"):
                audit_record_ids.append(explain_res.data["audit_id"])

            total_duration = round((time.perf_counter() - start_time) * 1000, 2)
            return AgentInvestigationResponse(
                investigation_id=investigation_id,
                transaction_id=str(txn_uuid),
                status="STOPPED",
                failure_category=category,
                failure_code=effective_failure_code,
                chosen_action="STOP_RECOVERY",
                expected_value=0.0,
                predicted_probability=0.0,
                execution_disposition=exec_data.get("disposition", "APPROVED"),
                customer_explanation=customer_expl,
                merchant_explanation=f"Recovery stopped due to {category} classification ({effective_failure_code}).",
                compliance_notes=compliance_advisory or "Strict terminal stop applied.",
                recovery_plan=AgentRecoveryPlan(**plan_data) if plan_res.success else None,
                steps=steps,
                audit_records=audit_record_ids,
                total_duration_ms=total_duration,
            )

        # --------------------------------------------------------------------
        # STEP 3: ML Predictions & Expected Value Scoring
        # --------------------------------------------------------------------
        score_res = _execute_step(
            thought=f"Score permitted recovery actions for {category} using ML success probabilities and net Expected Value optimization.",
            tool_name="score_candidates",
            arguments={
                "transaction_id": str(txn_uuid),
                "failure_code": effective_failure_code,
            },
        )
        if not score_res.success or not score_res.data.get("best_action"):
            total_duration = round((time.perf_counter() - start_time) * 1000, 2)
            return AgentInvestigationResponse(
                investigation_id=investigation_id,
                transaction_id=str(txn_uuid),
                status="NEEDS_REVIEW",
                failure_category=category,
                failure_code=effective_failure_code,
                chosen_action="STOP_RECOVERY",
                expected_value=0.0,
                predicted_probability=0.0,
                execution_disposition="REFUSED",
                customer_explanation=customer_expl,
                merchant_explanation="No viable recovery actions identified during ML scoring. Manual review requested.",
                compliance_notes=compliance_advisory,
                recovery_plan=None,
                steps=steps,
                audit_records=audit_record_ids,
                total_duration_ms=total_duration,
            )

        score_data = score_res.data
        best_action = score_data["best_action"]
        chosen_action_type = best_action["action_type"]
        best_ev = float(best_action["expected_value"])
        predicted_prob = float(best_action["probability"])

        # Determine fallback action (runner up)
        candidates = score_data.get("candidates", [])
        fallback_action = None
        if len(candidates) > 1:
            for c in candidates:
                if c["action_type"] != chosen_action_type and c["expected_value"] > 0:
                    fallback_action = c["action_type"]
                    break

        # --------------------------------------------------------------------
        # STEP 4: Formulate Bounded Recovery Plan
        # --------------------------------------------------------------------
        plan_res = _execute_step(
            thought=f"Formulate structured recovery plan for optimal action '{chosen_action_type}' (EV: ₹{best_ev:.2f}, P: {predicted_prob:.1%}).",
            tool_name="create_recovery_plan",
            arguments={
                "transaction_id": str(txn_uuid),
                "chosen_action": chosen_action_type,
                "confidence_score": max(0.60, min(0.99, predicted_prob)),
                "reason_codes": policy_data.get("reason_codes", []) + ["AGENT_EV_OPTIMAL"],
                "fallback_action": fallback_action,
            },
        )
        plan_data = plan_res.data if plan_res.success else {}
        recovery_plan_obj = AgentRecoveryPlan(**plan_data) if plan_res.success else None

        # --------------------------------------------------------------------
        # STEP 5: Request Bounded Execution (Pre-Execution Guard)
        # --------------------------------------------------------------------
        exec_disposition = "QUEUED"
        if execute_bounded_action and recovery_plan_obj:
            exec_res = _execute_step(
                thought="Run pre-execution validation guards (status, attempt count, policy checks) to approve action execution.",
                tool_name="request_execution",
                arguments={
                    "transaction_id": str(txn_uuid),
                    "recovery_plan_id": recovery_plan_obj.recovery_plan_id,
                    "idempotency_key": recovery_plan_obj.idempotency_key,
                },
            )
            if exec_res.success:
                exec_disposition = exec_res.data.get("disposition", "APPROVED")
            else:
                exec_disposition = "REFUSED"

        # --------------------------------------------------------------------
        # STEP 6: Write Explainable Audit Trail
        # --------------------------------------------------------------------
        narrative_summary = (
            f"Agent selected {chosen_action_type} as the optimal recovery path for {effective_failure_code} "
            f"({category}). ML model predicted {predicted_prob:.1%} success rate, yielding net Expected Value "
            f"₹{best_ev:.2f}. Execution disposition: {exec_disposition}."
        )

        merchant_notes = (
            f"Root cause: {merchant_log}. Recommended {chosen_action_type} via channel '{best_action.get('channel', 'system')}'. "
            f"Estimated cost ₹{best_action.get('execution_cost', 0):.2f}, friction penalty ₹{best_action.get('friction_penalty', 0):.2f}."
        )

        explain_res = _execute_step(
            thought="Persist comprehensive audit explanation with customer and merchant narratives.",
            tool_name="write_explanation",
            arguments={
                "transaction_id": str(txn_uuid),
                "recovery_plan_id": recovery_plan_obj.recovery_plan_id if recovery_plan_obj else None,
                "explanation_summary": narrative_summary,
                "customer_message": customer_expl,
                "merchant_notes": merchant_notes,
                "reason_codes": policy_data.get("reason_codes", []) + ["AGENT_DECISION_FINAL"],
            },
        )
        if explain_res.success and explain_res.data.get("audit_id"):
            audit_record_ids.append(explain_res.data["audit_id"])

        # --------------------------------------------------------------------
        # STEP 7: Emit Outbox Event for Agent Investigation
        # --------------------------------------------------------------------
        session.add(
            OutboxEvent(
                event_type="recovery.agent_investigated.v1",
                aggregate_type="transaction",
                aggregate_id=str(txn_uuid),
                payload={
                    "event_id": str(uuid4()),
                    "investigation_id": investigation_id,
                    "transaction_id": str(txn_uuid),
                    "failure_code": effective_failure_code,
                    "failure_category": category,
                    "chosen_action": chosen_action_type,
                    "expected_value": best_ev,
                    "predicted_probability": predicted_prob,
                    "execution_disposition": exec_disposition,
                    "agent_version": self.AGENT_VERSION,
                },
            )
        )
        session.commit()

        total_duration = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(
            "Agent investigation %s completed for txn %s in %.2fms: action=%s, ev=%.2f, disposition=%s",
            investigation_id,
            txn_uuid,
            total_duration,
            chosen_action_type,
            best_ev,
            exec_disposition,
        )

        return AgentInvestigationResponse(
            investigation_id=investigation_id,
            transaction_id=str(txn_uuid),
            status="COMPLETED",
            failure_category=category,
            failure_code=effective_failure_code,
            chosen_action=chosen_action_type,
            expected_value=best_ev,
            predicted_probability=predicted_prob,
            execution_disposition=exec_disposition,
            customer_explanation=customer_expl,
            merchant_explanation=merchant_notes,
            compliance_notes=compliance_advisory,
            recovery_plan=recovery_plan_obj,
            steps=steps,
            audit_records=audit_record_ids,
            total_duration_ms=total_duration,
        )


class DeterministicAgentFallback:
    """Deterministic ReAct reasoning fallback when no LLM API key is configured.

    Executes the exact same bounded tool trajectory deterministically, emitting
    an AgentInvestigationResponse with detailed ReAct step traces.
    """

    def __init__(self, tool_registry: AgentToolRegistry | None = None) -> None:
        self.agent = PaymentRecoveryAgent(tool_registry=tool_registry)

    def investigate_transaction(
        self,
        session: Session,
        transaction_id: str | UUID,
        override_failure_code: str | None = None,
        execute_bounded_action: bool = False,
    ) -> AgentInvestigationResponse:
        """Run the deterministic bounded investigation loop (propose plan only)."""
        return self.agent.investigate_transaction(
            session=session,
            transaction_id=transaction_id,
            override_failure_code=override_failure_code,
            execute_bounded_action=execute_bounded_action,
        )


# Global Singleton Agent and Fallback
payment_recovery_agent = PaymentRecoveryAgent()
deterministic_agent_fallback = DeterministicAgentFallback()

