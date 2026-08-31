"""Recovery Execution Engine and Workflows for RecoverX.

Day 11 deliverable: Implements automated, bounded execution across 4 recovery strategies:
1. Immediate Retry (RETRY_SAME_METHOD)
2. Payment-Method Switch (SWITCH_TO_UPI, SWITCH_TO_CARD, SWITCH_TO_NETBANKING)
3. Delayed Retry with Exponential Backoff & Scheduler (DELAYED_RETRY)
4. Customer Recovery Workflow & Tokenized Payment Link (CUSTOMER_NOTIFICATION, PAYMENT_LINK)
"""

from __future__ import annotations

import logging
import random
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.models.recovery import (
    ActionType,
    AuditLog,
    Customer,
    CustomerIntelligence,
    CustomerRecoverySession,
    FailureEvent,
    OutboxEvent,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.execution import (
    CustomerCheckoutDetailResponse,
    CustomerCheckoutSubmitResponse,
    CustomerRecoveryLinkResponse,
    ExecuteActionResponse,
    ExecutionMetricsResponse,
    ProcessScheduledRetriesResponse,
)
from backend.app.schemas.failure import FailureClassificationRequest
from backend.app.services.failure_intelligence import failure_intelligence_service
from backend.app.services.recovery_policy import evaluate_failure_policy
from backend.app.simulator.constants import (
    FAILURE_CATALOG,
    Gateway,
    PaymentMethod,
    SAMPLE_ISSUER_BANKS,
    SAMPLE_UPI_APPS,
)

logger = logging.getLogger("recoverx.recovery_execution")


def _generate_masked_instrument(payment_method: str) -> dict[str, str]:
    """Generate safe reference instrument metadata."""
    if payment_method == "CARD":
        brand = random.choice(["Visa", "Mastercard", "RuPay"])
        card_type = random.choice(["Credit", "Debit"])
        bin_num = "411111" if brand == "Visa" else ("524188" if brand == "Mastercard" else "607152")
        last4 = f"{random.randint(1000, 9999)}"
        return {
            "card_brand": brand,
            "card_type": card_type,
            "masked_number": f"{bin_num}******{last4}",
            "issuer_bank": random.choice(SAMPLE_ISSUER_BANKS),
        }
    if payment_method == "UPI":
        app = random.choice(SAMPLE_UPI_APPS)
        handle = random.choice(["okhdfcbank", "oksbi", "paytm", "apl", "ybl"])
        return {
            "upi_app": app,
            "vpa_handle": f"cust_{random.randint(100, 999)}@{handle}",
            "remitter_bank": random.choice(SAMPLE_ISSUER_BANKS),
        }
    if payment_method == "NETBANKING":
        return {
            "bank_name": random.choice(SAMPLE_ISSUER_BANKS),
            "channel": "Retail NetBanking",
        }
    return {"wallet_provider": "Paytm Wallet"}


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime object is timezone-aware in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class RecoveryExecutionEngine:
    """Core execution engine for turning recovery decisions and plans into verified actions."""

    EXECUTOR_ACTOR = "recovery_executor"

    # ========================================================================
    # 1. PRIMARY EXECUTION ENTRY POINT
    # ========================================================================

    def execute_action(
        self,
        session: Session,
        transaction_id: str | UUID,
        action_type: str | None = None,
        recovery_action_id: str | UUID | None = None,
        recovery_plan_id: str | None = None,
        idempotency_key: str | None = None,
        parameters: dict[str, Any] | None = None,
        force_outcome: str | None = None,
    ) -> ExecuteActionResponse:
        """Execute a validated recovery action across any of the 4 supported recovery workflows."""
        txn_uuid = UUID(str(transaction_id)) if isinstance(transaction_id, str) else transaction_id
        execution_id = f"exec_{uuid4().hex[:10]}"
        params = parameters or {}

        # 1. Locate Transaction with attempts, customer, and recovery cases
        txn = session.scalar(
            select(Transaction)
            .options(
                joinedload(Transaction.attempts),
                joinedload(Transaction.customer).joinedload(Customer.intelligence),
                joinedload(Transaction.recovery_cases).joinedload(RecoveryCase.actions),
            )
            .where(Transaction.id == txn_uuid)
        )
        if not txn:
            return ExecuteActionResponse(
                execution_id=execution_id,
                transaction_id=str(txn_uuid),
                recovery_case_id="none",
                action_type="UNKNOWN",
                disposition="REFUSED",
                status="REFUSED",
                message=f"Transaction {txn_uuid} not found.",
                guard_checks={"transaction_exists": False},
            )

        # 2. Guard Check: Double-Recovery Prevention
        if txn.status == TransactionStatus.SUCCEEDED:
            return ExecuteActionResponse(
                execution_id=execution_id,
                transaction_id=str(txn_uuid),
                recovery_case_id=str(txn.recovery_cases[0].id) if txn.recovery_cases else "none",
                action_type="NONE",
                disposition="REFUSED",
                status="REFUSED",
                message="Execution refused: Transaction has already SUCCEEDED. Double recovery is strictly prevented.",
                guard_checks={"not_already_succeeded": False, "attempt_limit_valid": True, "policy_valid": True},
            )

        # 3. Locate or create Recovery Case
        recovery_case = txn.recovery_cases[0] if txn.recovery_cases else None
        if not recovery_case:
            recovery_case = RecoveryCase(
                transaction_id=txn.id,
                state=RecoveryState.OPEN,
                policy_version="policy.v2",
                version=1,
            )
            session.add(recovery_case)
            session.flush()

        attempts = sorted(txn.attempts or [], key=lambda a: a.attempt_number)
        last_failure_code = attempts[-1].failure_code if attempts and attempts[-1].failure_code else "UNKNOWN"
        policy = evaluate_failure_policy(last_failure_code)
        classified = failure_intelligence_service.classify_failure(
            FailureClassificationRequest(failure_code=last_failure_code)
        )
        max_retries = classified.max_retries_permitted

        # 4. Resolve Target Action & ActionType
        effective_action_type_str = action_type
        target_action_obj: RecoveryAction | None = None

        if recovery_action_id:
            act_uuid = UUID(str(recovery_action_id)) if isinstance(recovery_action_id, str) else recovery_action_id
            target_action_obj = session.scalar(select(RecoveryAction).where(RecoveryAction.id == act_uuid))
            if target_action_obj:
                effective_action_type_str = target_action_obj.action_type.value

        if not effective_action_type_str:
            # Check if any action in case is already selected
            for act in recovery_case.actions:
                if act.selected:
                    target_action_obj = act
                    effective_action_type_str = act.action_type.value
                    break

        if not effective_action_type_str:
            # Fallback to policy default
            effective_action_type_str = policy.permitted_actions[0].value if policy.permitted_actions else "STOP_RECOVERY"

        try:
            act_enum = ActionType(effective_action_type_str.upper())
        except ValueError:
            return ExecuteActionResponse(
                execution_id=execution_id,
                transaction_id=str(txn.id),
                recovery_case_id=str(recovery_case.id),
                action_type=str(effective_action_type_str),
                disposition="REFUSED",
                status="REFUSED",
                message=f"Unsupported ActionType: {effective_action_type_str}",
                guard_checks={"action_type_valid": False},
            )

        # 5. Guard Check: Hard Failure / STOP_RECOVERY
        if act_enum == ActionType.STOP_RECOVERY or not policy.recoverable or policy.category == "HARD_FAILURE":
            recovery_case.state = RecoveryState.STOPPED
            recovery_case.version += 1
            if target_action_obj:
                target_action_obj.status = "BLOCKED"
                target_action_obj.executed_at = datetime.now(timezone.utc)
            session.commit()
            return ExecuteActionResponse(
                execution_id=execution_id,
                transaction_id=str(txn.id),
                recovery_case_id=str(recovery_case.id),
                recovery_action_id=str(target_action_obj.id) if target_action_obj else None,
                action_type="STOP_RECOVERY",
                disposition="BLOCKED",
                status="BLOCKED",
                message=f"Execution blocked: Terminal stop applied for hard failure code '{last_failure_code}'.",
                guard_checks={"not_already_succeeded": True, "attempt_limit_valid": True, "policy_valid": False},
            )

        # 6. Guard Check: Max Attempts Limit
        if len(attempts) > (max_retries + 1):
            recovery_case.state = RecoveryState.STOPPED
            recovery_case.version += 1
            session.commit()
            return ExecuteActionResponse(
                execution_id=execution_id,
                transaction_id=str(txn.id),
                recovery_case_id=str(recovery_case.id),
                recovery_action_id=str(target_action_obj.id) if target_action_obj else None,
                action_type=act_enum.value,
                disposition="BLOCKED",
                status="BLOCKED",
                message=f"Execution blocked: Maximum retry attempts ({max_retries}) exceeded for category '{policy.category}'.",
                guard_checks={"not_already_succeeded": True, "attempt_limit_valid": False, "policy_valid": True},
            )

        # 7. Ensure RecoveryAction record exists
        if not target_action_obj:
            idemp_key = idempotency_key or f"act_{recovery_case.id}_{act_enum.value.lower()}_{uuid4().hex[:6]}"
            target_action_obj = session.scalar(
                select(RecoveryAction).where(
                    RecoveryAction.recovery_case_id == recovery_case.id,
                    RecoveryAction.action_type == act_enum,
                )
            )
            if not target_action_obj:
                target_action_obj = RecoveryAction(
                    recovery_case_id=recovery_case.id,
                    action_type=act_enum,
                    idempotency_key=idemp_key,
                    selected=True,
                    status="PENDING",
                    probability=Decimal("0.7500"),
                    expected_value=Decimal(str(round(float(txn.amount) * 0.75, 2))),
                    reason_codes=list(policy.reason_codes) + ["EXECUTED_BY_ENGINE"],
                )
                session.add(target_action_obj)
                session.flush()

        # ====================================================================
        # DISPATCH TO WORKFLOW HANDLERS
        # ====================================================================
        if act_enum == ActionType.RETRY_SAME_METHOD:
            return self._execute_retry_same_method(
                session=session,
                txn=txn,
                recovery_case=recovery_case,
                action=target_action_obj,
                execution_id=execution_id,
                force_outcome=force_outcome,
            )

        if act_enum in (ActionType.SWITCH_TO_UPI, ActionType.SWITCH_TO_CARD, ActionType.SWITCH_TO_NETBANKING):
            target_method = "UPI" if act_enum == ActionType.SWITCH_TO_UPI else ("NETBANKING" if act_enum == ActionType.SWITCH_TO_NETBANKING else "CARD")
            return self._execute_method_switch(
                session=session,
                txn=txn,
                recovery_case=recovery_case,
                action=target_action_obj,
                execution_id=execution_id,
                target_method=target_method,
                force_outcome=force_outcome,
                parameters=params,
            )

        if act_enum == ActionType.DELAYED_RETRY:
            return self._schedule_delayed_retry(
                session=session,
                txn=txn,
                recovery_case=recovery_case,
                action=target_action_obj,
                execution_id=execution_id,
                base_delay_seconds=classified.retry_delay_seconds,
                attempt_count=len(attempts),
                parameters=params,
            )

        if act_enum in (ActionType.CUSTOMER_NOTIFICATION, ActionType.PAYMENT_LINK):
            return self._execute_customer_recovery(
                session=session,
                txn=txn,
                recovery_case=recovery_case,
                action=target_action_obj,
                execution_id=execution_id,
                parameters=params,
            )

        # Fallback
        return ExecuteActionResponse(
            execution_id=execution_id,
            transaction_id=str(txn.id),
            recovery_case_id=str(recovery_case.id),
            recovery_action_id=str(target_action_obj.id),
            action_type=act_enum.value,
            disposition="REFUSED",
            status="REFUSED",
            message=f"No workflow handler for action {act_enum.value}",
        )

    # ========================================================================
    # 2. WORKFLOW 1: IMMEDIATE RETRY (RETRY_SAME_METHOD)
    # ========================================================================

    def _execute_retry_same_method(
        self,
        session: Session,
        txn: Transaction,
        recovery_case: RecoveryCase,
        action: RecoveryAction,
        execution_id: str,
        force_outcome: str | None = None,
    ) -> ExecuteActionResponse:
        """Execute an immediate payment attempt using the same payment instrument."""
        attempts = sorted(txn.attempts or [], key=lambda a: a.attempt_number)
        next_attempt_number = len(attempts) + 1
        current_method = attempts[-1].payment_method if attempts else "CARD"
        gateway = attempts[-1].gateway if attempts else Gateway.RAZORPAY.value
        correlation_id = uuid4()
        now = datetime.now(timezone.utc)

        # Determine outcome: Transient network/timeout issues have 80% resolution probability
        if force_outcome:
            is_success = force_outcome.upper() == "SUCCESS"
        else:
            is_success = random.random() < 0.80

        instrument_meta = _generate_masked_instrument(current_method)
        latency_ms = random.randint(220, 850)

        if is_success:
            # Success Path
            new_attempt = PaymentAttempt(
                transaction_id=txn.id,
                attempt_number=next_attempt_number,
                payment_method=current_method,
                gateway=gateway,
                failure_code=None,
            )
            session.add(new_attempt)

            txn.status = TransactionStatus.SUCCEEDED
            txn.version += 1
            recovery_case.state = RecoveryState.RECOVERED
            recovery_case.version += 1

            action.status = "COMPLETED"
            action.executed_at = now
            action.execution_channel = "DIRECT_RETRY_API"
            action.metadata_ = {
                "execution_id": execution_id,
                "attempt_number": next_attempt_number,
                "outcome": "SUCCESS",
                "latency_ms": latency_ms,
            }

            # Outbox and Audit
            session.add(
                OutboxEvent(
                    event_type="payment.succeeded.v1",
                    aggregate_type="transaction",
                    aggregate_id=str(txn.id),
                    payload={
                        "event_id": str(uuid4()),
                        "correlation_id": str(correlation_id),
                        "transaction_id": str(txn.id),
                        "attempt_number": next_attempt_number,
                        "amount": str(txn.amount),
                        "payment_method": current_method,
                        "recovery_action": "RETRY_SAME_METHOD",
                    },
                )
            )
            session.add(
                OutboxEvent(
                    event_type="recovery.outcome.v1",
                    aggregate_type="recovery_case",
                    aggregate_id=str(recovery_case.id),
                    payload={
                        "event_id": str(uuid4()),
                        "correlation_id": str(correlation_id),
                        "recovery_case_id": str(recovery_case.id),
                        "transaction_id": str(txn.id),
                        "outcome": "RECOVERED",
                        "action_type": "RETRY_SAME_METHOD",
                        "attempt_number": next_attempt_number,
                        "recovered_amount": str(txn.amount),
                    },
                )
            )
            session.add(
                AuditLog(
                    transaction_id=txn.id,
                    event_type="recovery.executed.v1",
                    actor=self.EXECUTOR_ACTOR,
                    reason_codes=["IMMEDIATE_RETRY_SUCCESS", "RECOVERY_COMPLETED"],
                    metadata_={
                        "execution_id": execution_id,
                        "action_type": "RETRY_SAME_METHOD",
                        "attempt_number": next_attempt_number,
                        "outcome": "SUCCESS",
                        "latency_ms": latency_ms,
                    },
                )
            )
            session.commit()

            return ExecuteActionResponse(
                execution_id=execution_id,
                transaction_id=str(txn.id),
                recovery_case_id=str(recovery_case.id),
                recovery_action_id=str(action.id),
                action_type="RETRY_SAME_METHOD",
                disposition="COMPLETED",
                status="SUCCEEDED",
                attempt_number=next_attempt_number,
                new_payment_method=current_method,
                execution_channel="DIRECT_RETRY_API",
                message=f"Immediate retry succeeded on attempt #{next_attempt_number}. Transaction recovered for ₹{txn.amount}.",
                guard_checks={"transaction_exists": True, "not_already_succeeded": True, "attempt_limit_valid": True, "policy_valid": True},
                metadata={"outcome": "SUCCESS", "latency_ms": latency_ms},
            )

        # Failure Path
        fail_code = "NETWORK_ERROR"
        fail_def = FAILURE_CATALOG.get(fail_code, FAILURE_CATALOG["TIMEOUT"])
        new_attempt = PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=next_attempt_number,
            payment_method=current_method,
            gateway=gateway,
            failure_code=fail_code,
        )
        session.add(new_attempt)
        session.flush()

        session.add(
            FailureEvent(
                source_event_id=f"evt_exec_{uuid4().hex[:12]}",
                transaction_id=txn.id,
                attempt_id=new_attempt.id,
                failure_code=fail_code,
                category="TEMPORARY",
                recoverable=True,
                payload={"error_message": fail_def.default_error_message, "payment_method": current_method},
            )
        )

        txn.status = TransactionStatus.FAILED
        txn.version += 1
        action.status = "FAILED"
        action.executed_at = now
        action.execution_channel = "DIRECT_RETRY_API"
        action.metadata_ = {"execution_id": execution_id, "attempt_number": next_attempt_number, "outcome": "FAIL", "failure_code": fail_code}

        session.add(
            AuditLog(
                transaction_id=txn.id,
                event_type="recovery.executed.v1",
                actor=self.EXECUTOR_ACTOR,
                reason_codes=["IMMEDIATE_RETRY_FAILED"],
                metadata_={"execution_id": execution_id, "action_type": "RETRY_SAME_METHOD", "attempt_number": next_attempt_number, "outcome": "FAIL"},
            )
        )
        session.commit()

        return ExecuteActionResponse(
            execution_id=execution_id,
            transaction_id=str(txn.id),
            recovery_case_id=str(recovery_case.id),
            recovery_action_id=str(action.id),
            action_type="RETRY_SAME_METHOD",
            disposition="COMPLETED",
            status="FAILED",
            attempt_number=next_attempt_number,
            new_payment_method=current_method,
            execution_channel="DIRECT_RETRY_API",
            message=f"Immediate retry failed on attempt #{next_attempt_number} with code '{fail_code}'.",
            guard_checks={"transaction_exists": True, "not_already_succeeded": True, "attempt_limit_valid": True, "policy_valid": True},
            metadata={"outcome": "FAIL", "failure_code": fail_code},
        )

    # ========================================================================
    # 3. WORKFLOW 2: PAYMENT-METHOD SWITCH (SWITCH_TO_UPI / CARD / NETBANKING)
    # ========================================================================

    def _execute_method_switch(
        self,
        session: Session,
        txn: Transaction,
        recovery_case: RecoveryCase,
        action: RecoveryAction,
        execution_id: str,
        target_method: str,
        force_outcome: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> ExecuteActionResponse:
        """Switch payment method to bypass card declines, mandate errors, or instrument issues."""
        attempts = sorted(txn.attempts or [], key=lambda a: a.attempt_number)
        next_attempt_number = len(attempts) + 1
        correlation_id = uuid4()
        now = datetime.now(timezone.utc)
        params = parameters or {}

        # Resolve gateway and target instrument
        if target_method == "UPI":
            gateway = "NPCI_UPI"
            action_type_name = "SWITCH_TO_UPI"
            default_channel = "UPI_INTENT_REDIRECT"
        elif target_method == "NETBANKING":
            gateway = Gateway.RAZORPAY.value
            action_type_name = "SWITCH_TO_NETBANKING"
            default_channel = "NETBANKING_REDIRECT"
        else:
            gateway = Gateway.STRIPE.value
            action_type_name = "SWITCH_TO_CARD"
            default_channel = "ALTERNATE_CARD_CHECKOUT"

        instrument_meta = _generate_masked_instrument(target_method)
        if "vpa" in params and target_method == "UPI":
            instrument_meta["vpa_handle"] = params["vpa"]

        # Switching away from bad instrument has high success rate (88%)
        if force_outcome:
            is_success = force_outcome.upper() == "SUCCESS"
        else:
            is_success = random.random() < 0.88

        latency_ms = random.randint(190, 780)

        if is_success:
            new_attempt = PaymentAttempt(
                transaction_id=txn.id,
                attempt_number=next_attempt_number,
                payment_method=target_method,
                gateway=gateway,
                failure_code=None,
            )
            session.add(new_attempt)

            txn.status = TransactionStatus.SUCCEEDED
            txn.version += 1
            recovery_case.state = RecoveryState.RECOVERED
            recovery_case.version += 1

            action.status = "COMPLETED"
            action.executed_at = now
            action.execution_channel = default_channel
            action.metadata_ = {
                "execution_id": execution_id,
                "switched_from": attempts[-1].payment_method if attempts else "CARD",
                "switched_to": target_method,
                "attempt_number": next_attempt_number,
                "outcome": "SUCCESS",
                "instrument": instrument_meta,
            }

            session.add(
                OutboxEvent(
                    event_type="payment.succeeded.v1",
                    aggregate_type="transaction",
                    aggregate_id=str(txn.id),
                    payload={
                        "event_id": str(uuid4()),
                        "correlation_id": str(correlation_id),
                        "transaction_id": str(txn.id),
                        "attempt_number": next_attempt_number,
                        "amount": str(txn.amount),
                        "payment_method": target_method,
                        "switched_from": attempts[-1].payment_method if attempts else "CARD",
                        "recovery_action": action_type_name,
                    },
                )
            )
            session.add(
                OutboxEvent(
                    event_type="recovery.outcome.v1",
                    aggregate_type="recovery_case",
                    aggregate_id=str(recovery_case.id),
                    payload={
                        "event_id": str(uuid4()),
                        "correlation_id": str(correlation_id),
                        "recovery_case_id": str(recovery_case.id),
                        "transaction_id": str(txn.id),
                        "outcome": "RECOVERED",
                        "action_type": action_type_name,
                        "switched_to": target_method,
                        "attempt_number": next_attempt_number,
                        "recovered_amount": str(txn.amount),
                    },
                )
            )
            session.add(
                AuditLog(
                    transaction_id=txn.id,
                    event_type="recovery.executed.v1",
                    actor=self.EXECUTOR_ACTOR,
                    reason_codes=["PAYMENT_METHOD_SWITCH_SUCCESS", f"SWITCHED_TO_{target_method}"],
                    metadata_={
                        "execution_id": execution_id,
                        "action_type": action_type_name,
                        "switched_to": target_method,
                        "attempt_number": next_attempt_number,
                        "outcome": "SUCCESS",
                        "instrument": instrument_meta,
                    },
                )
            )
            session.commit()

            return ExecuteActionResponse(
                execution_id=execution_id,
                transaction_id=str(txn.id),
                recovery_case_id=str(recovery_case.id),
                recovery_action_id=str(action.id),
                action_type=action_type_name,
                disposition="COMPLETED",
                status="SUCCEEDED",
                attempt_number=next_attempt_number,
                new_payment_method=target_method,
                execution_channel=default_channel,
                message=f"Successfully switched payment method to {target_method}. Transaction recovered on attempt #{next_attempt_number}.",
                guard_checks={"transaction_exists": True, "not_already_succeeded": True, "attempt_limit_valid": True, "policy_valid": True},
                metadata={"outcome": "SUCCESS", "switched_to": target_method, "instrument": instrument_meta},
            )

        # Failure on switch
        fail_code = "UPI_FAILURE" if target_method == "UPI" else "GATEWAY_ERROR"
        new_attempt = PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=next_attempt_number,
            payment_method=target_method,
            gateway=gateway,
            failure_code=fail_code,
        )
        session.add(new_attempt)
        session.flush()

        txn.status = TransactionStatus.FAILED
        txn.version += 1
        action.status = "FAILED"
        action.executed_at = now
        action.execution_channel = default_channel
        action.metadata_ = {"execution_id": execution_id, "switched_to": target_method, "outcome": "FAIL", "failure_code": fail_code}

        session.add(
            AuditLog(
                transaction_id=txn.id,
                event_type="recovery.executed.v1",
                actor=self.EXECUTOR_ACTOR,
                reason_codes=[f"SWITCH_TO_{target_method}_FAILED"],
                metadata_={"execution_id": execution_id, "action_type": action_type_name, "outcome": "FAIL", "failure_code": fail_code},
            )
        )
        session.commit()

        return ExecuteActionResponse(
            execution_id=execution_id,
            transaction_id=str(txn.id),
            recovery_case_id=str(recovery_case.id),
            recovery_action_id=str(action.id),
            action_type=action_type_name,
            disposition="COMPLETED",
            status="FAILED",
            attempt_number=next_attempt_number,
            new_payment_method=target_method,
            execution_channel=default_channel,
            message=f"Payment method switch to {target_method} failed on attempt #{next_attempt_number}.",
            guard_checks={"transaction_exists": True, "not_already_succeeded": True, "attempt_limit_valid": True, "policy_valid": True},
            metadata={"outcome": "FAIL", "failure_code": fail_code},
        )

    # ========================================================================
    # 4. WORKFLOW 3: DELAYED RETRY (DELAYED_RETRY)
    # ========================================================================

    def _schedule_delayed_retry(
        self,
        session: Session,
        txn: Transaction,
        recovery_case: RecoveryCase,
        action: RecoveryAction,
        execution_id: str,
        base_delay_seconds: int,
        attempt_count: int,
        parameters: dict[str, Any] | None = None,
    ) -> ExecuteActionResponse:
        """Schedule delayed retry with exponential backoff and jitter."""
        params = parameters or {}
        now = datetime.now(timezone.utc)

        # Exponential backoff formula: base * 2^(attempt - 1) + jitter
        backoff_mult = 2 ** max(0, attempt_count - 1)
        base_delay = params.get("delay_seconds", base_delay_seconds * backoff_mult)
        jitter = random.randint(0, min(10, int(base_delay * 0.15)))
        total_delay = max(1, int(base_delay) + jitter)

        scheduled_time = now + timedelta(seconds=total_delay)

        action.status = "SCHEDULED"
        action.scheduled_at = scheduled_time
        action.execution_channel = "DELAYED_SCHEDULER"
        action.metadata_ = {
            "execution_id": execution_id,
            "delay_seconds": total_delay,
            "attempt_number_expected": attempt_count + 1,
            "scheduled_at": scheduled_time.isoformat(),
        }

        recovery_case.state = RecoveryState.SCHEDULED
        recovery_case.version += 1

        # Outbox event for scheduler
        session.add(
            OutboxEvent(
                event_type="recovery.scheduled.v1",
                aggregate_type="recovery_action",
                aggregate_id=str(action.id),
                payload={
                    "event_id": str(uuid4()),
                    "transaction_id": str(txn.id),
                    "recovery_case_id": str(recovery_case.id),
                    "action_id": str(action.id),
                    "action_type": "DELAYED_RETRY",
                    "scheduled_at": scheduled_time.isoformat(),
                    "delay_seconds": total_delay,
                },
            )
        )
        session.add(
            AuditLog(
                transaction_id=txn.id,
                event_type="recovery.scheduled.v1",
                actor=self.EXECUTOR_ACTOR,
                reason_codes=["EXPONENTIAL_BACKOFF_SCHEDULED", f"DELAY_{total_delay}S"],
                metadata_={
                    "execution_id": execution_id,
                    "action_type": "DELAYED_RETRY",
                    "scheduled_at": scheduled_time.isoformat(),
                    "delay_seconds": total_delay,
                },
            )
        )
        session.commit()

        return ExecuteActionResponse(
            execution_id=execution_id,
            transaction_id=str(txn.id),
            recovery_case_id=str(recovery_case.id),
            recovery_action_id=str(action.id),
            action_type="DELAYED_RETRY",
            disposition="QUEUED",
            status="SCHEDULED",
            scheduled_at=scheduled_time.isoformat(),
            execution_channel="DELAYED_SCHEDULER",
            message=f"Delayed retry scheduled with {total_delay}s exponential backoff for {scheduled_time.isoformat()}.",
            guard_checks={"transaction_exists": True, "not_already_succeeded": True, "attempt_limit_valid": True, "policy_valid": True},
            metadata={"scheduled_at": scheduled_time.isoformat(), "delay_seconds": total_delay},
        )

    def process_due_scheduled_retries(
        self,
        session: Session,
        limit: int = 50,
        force_now: bool = False,
        force_outcome: str | None = None,
    ) -> ProcessScheduledRetriesResponse:
        """Process all delayed retries that have reached their scheduled execution time."""
        now = datetime.now(timezone.utc)
        query = (
            select(RecoveryAction)
            .join(RecoveryCase, RecoveryAction.recovery_case_id == RecoveryCase.id)
            .join(Transaction, RecoveryCase.transaction_id == Transaction.id)
            .where(
                RecoveryAction.status == "SCHEDULED",
                RecoveryAction.action_type == ActionType.DELAYED_RETRY,
            )
        )
        if not force_now:
            query = query.where(RecoveryAction.scheduled_at <= now)

        scheduled_actions = list(session.scalars(query.limit(limit)).all())
        executed_list: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for action in scheduled_actions:
            recovery_case = session.scalar(select(RecoveryCase).where(RecoveryCase.id == action.recovery_case_id))
            if not recovery_case:
                continue
            txn = session.scalar(
                select(Transaction)
                .options(joinedload(Transaction.attempts))
                .where(Transaction.id == recovery_case.transaction_id)
            )
            if not txn or txn.status == TransactionStatus.SUCCEEDED:
                action.status = "CANCELLED"
                session.commit()
                continue

            # Execute delayed attempt (high recovery rate for recovered network / bank)
            res = self._execute_retry_same_method(
                session=session,
                txn=txn,
                recovery_case=recovery_case,
                action=action,
                execution_id=f"sched_exec_{uuid4().hex[:8]}",
                force_outcome=force_outcome,
            )
            if res.status == "SUCCEEDED":
                succeeded += 1
            else:
                failed += 1
            executed_list.append({
                "action_id": str(action.id),
                "transaction_id": str(txn.id),
                "status": res.status,
                "attempt_number": res.attempt_number,
                "message": res.message,
            })

        return ProcessScheduledRetriesResponse(
            processed_count=len(executed_list),
            succeeded_count=succeeded,
            failed_count=failed,
            executions=executed_list,
        )

    # ========================================================================
    # 5. WORKFLOW 4: CUSTOMER RECOVERY (NOTIFICATION & PAYMENT LINK)
    # ========================================================================

    def _execute_customer_recovery(
        self,
        session: Session,
        txn: Transaction,
        recovery_case: RecoveryCase,
        action: RecoveryAction,
        execution_id: str,
        parameters: dict[str, Any] | None = None,
    ) -> ExecuteActionResponse:
        """Create tokenized payment link and dispatch customer notification."""
        params = parameters or {}
        channel = params.get("channel", "SMS").upper()
        expires_minutes = params.get("expires_in_minutes", 30)
        custom_msg = params.get("custom_message")

        link_response = self.create_customer_recovery_link(
            session=session,
            transaction_id=txn.id,
            recovery_action_id=action.id,
            channel=channel,
            expires_in_minutes=expires_minutes,
            custom_message=custom_msg,
        )

        action.status = "SCHEDULED"
        action.execution_channel = channel
        action.metadata_ = {
            "execution_id": execution_id,
            "session_id": link_response.session_id,
            "token": link_response.token,
            "checkout_url": link_response.checkout_url,
            "channel": channel,
            "expires_at": link_response.expires_at,
        }
        recovery_case.state = RecoveryState.SCHEDULED
        session.commit()

        return ExecuteActionResponse(
            execution_id=execution_id,
            transaction_id=str(txn.id),
            recovery_case_id=str(recovery_case.id),
            recovery_action_id=str(action.id),
            action_type=action.action_type.value,
            disposition="QUEUED",
            status="SCHEDULED",
            execution_channel=channel,
            message=f"Customer recovery payment link generated and dispatched via {channel}. Checkout URL: {link_response.checkout_url}",
            guard_checks={"transaction_exists": True, "not_already_succeeded": True, "attempt_limit_valid": True, "policy_valid": True},
            metadata={
                "session_id": link_response.session_id,
                "token": link_response.token,
                "checkout_url": link_response.checkout_url,
                "channel": channel,
                "expires_at": link_response.expires_at,
            },
        )

    def create_customer_recovery_link(
        self,
        session: Session,
        transaction_id: str | UUID,
        recovery_action_id: str | UUID | None = None,
        channel: str = "SMS",
        expires_in_minutes: int = 30,
        custom_message: str | None = None,
    ) -> CustomerRecoveryLinkResponse:
        """Create a tokenized interactive payment link session for a customer."""
        txn_uuid = UUID(str(transaction_id)) if isinstance(transaction_id, str) else transaction_id
        txn = session.scalar(
            select(Transaction)
            .options(joinedload(Transaction.customer), joinedload(Transaction.attempts))
            .where(Transaction.id == txn_uuid)
        )
        if not txn:
            raise ValueError(f"Transaction {txn_uuid} not found.")

        attempts = sorted(txn.attempts or [], key=lambda a: a.attempt_number)
        last_failure_code = attempts[-1].failure_code if attempts and attempts[-1].failure_code else "UNKNOWN"
        classified = failure_intelligence_service.classify_failure(
            FailureClassificationRequest(failure_code=last_failure_code)
        )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=expires_in_minutes)
        token = f"rec_{secrets.token_urlsafe(16)}"
        session_id = uuid4()
        checkout_url = f"https://pay.recoverx.io/pay/{token}"

        # Resolve recovery action if not specified
        act_uuid = UUID(str(recovery_action_id)) if recovery_action_id else None
        if not act_uuid:
            recovery_case = session.scalar(select(RecoveryCase).where(RecoveryCase.transaction_id == txn.id))
            if recovery_case:
                act = session.scalar(
                    select(RecoveryAction).where(RecoveryAction.recovery_case_id == recovery_case.id)
                )
                if act:
                    act_uuid = act.id

        if not act_uuid:
            # Create a fallback recovery case and action
            rec_case = RecoveryCase(transaction_id=txn.id, state=RecoveryState.OPEN, policy_version="policy.v2")
            session.add(rec_case)
            session.flush()
            rec_act = RecoveryAction(
                recovery_case_id=rec_case.id,
                action_type=ActionType.PAYMENT_LINK,
                idempotency_key=f"act_{rec_case.id}_link_{uuid4().hex[:6]}",
                selected=True,
                probability=Decimal("0.7000"),
                expected_value=Decimal(str(round(float(txn.amount) * 0.70, 2))),
            )
            session.add(rec_act)
            session.flush()
            act_uuid = rec_act.id

        customer_msg = custom_message or (
            f"Your payment of ₹{txn.amount} for order at {txn.merchant_id} was interrupted: "
            f"{classified.customer_explanation} Please tap here to complete payment: {checkout_url}"
        )

        method_options = ["UPI", "NETBANKING", "CARD"]

        cust_session = CustomerRecoverySession(
            id=session_id,
            recovery_action_id=act_uuid,
            transaction_id=txn.id,
            token=token,
            status="ACTIVE",
            expires_at=expires_at,
            payment_method_options=method_options,
            customer_notes=classified.customer_explanation,
            metadata_={
                "channel": channel,
                "checkout_url": checkout_url,
                "customer_message": customer_msg,
                "amount": str(txn.amount),
                "merchant_id": txn.merchant_id,
            },
        )
        session.add(cust_session)

        # Record notification outbox event & audit log
        session.add(
            OutboxEvent(
                event_type="recovery.customer_notified.v1",
                aggregate_type="customer_recovery_session",
                aggregate_id=str(session_id),
                payload={
                    "event_id": str(uuid4()),
                    "session_id": str(session_id),
                    "token": token,
                    "transaction_id": str(txn.id),
                    "channel": channel,
                    "amount": str(txn.amount),
                    "expires_at": expires_at.isoformat(),
                },
            )
        )
        session.add(
            AuditLog(
                transaction_id=txn.id,
                event_type="recovery.customer_notified.v1",
                actor=self.EXECUTOR_ACTOR,
                reason_codes=[f"NOTIFICATION_SENT_{channel}", "PAYMENT_LINK_GENERATED"],
                metadata_={
                    "session_id": str(session_id),
                    "channel": channel,
                    "token": token,
                    "expires_at": expires_at.isoformat(),
                },
            )
        )
        session.commit()

        return CustomerRecoveryLinkResponse(
            session_id=str(session_id),
            token=token,
            checkout_url=checkout_url,
            transaction_id=str(txn.id),
            amount=Decimal(str(txn.amount)),
            currency=txn.currency,
            channel=channel,
            expires_at=expires_at.isoformat(),
            status="ACTIVE",
            payment_method_options=method_options,
            customer_message=customer_msg,
        )

    def get_customer_checkout_details(self, session: Session, token: str) -> CustomerCheckoutDetailResponse:
        """Fetch public customer checkout details by recovery token."""
        now = datetime.now(timezone.utc)
        cust_session = session.scalar(
            select(CustomerRecoverySession)
            .options(joinedload(CustomerRecoverySession.transaction).joinedload(Transaction.attempts))
            .where(CustomerRecoverySession.token == token)
        )
        if not cust_session:
            raise ValueError(f"Recovery token '{token}' not found.")

        txn = cust_session.transaction
        is_expired = _ensure_utc(cust_session.expires_at) < now or cust_session.status != "ACTIVE"
        attempts = sorted(txn.attempts or [], key=lambda a: a.attempt_number)
        last_failure_code = attempts[-1].failure_code if attempts and attempts[-1].failure_code else None

        return CustomerCheckoutDetailResponse(
            token=cust_session.token,
            transaction_id=str(txn.id),
            merchant_id=txn.merchant_id,
            amount=Decimal(str(txn.amount)),
            currency=txn.currency,
            status="EXPIRED" if is_expired and cust_session.status == "ACTIVE" else cust_session.status,
            expires_at=cust_session.expires_at.isoformat(),
            is_expired=is_expired,
            failure_code=last_failure_code,
            customer_explanation=cust_session.customer_notes or "Please complete your payment.",
            payment_method_options=cust_session.payment_method_options or ["UPI", "NETBANKING", "CARD"],
        )

    def complete_customer_checkout(
        self,
        session: Session,
        token: str,
        payment_method: str,
        instrument_details: dict[str, Any] | None = None,
        simulate_outcome: str | None = None,
    ) -> CustomerCheckoutSubmitResponse:
        """Process customer interactive payment completion from recovery link."""
        now = datetime.now(timezone.utc)
        cust_session = session.scalar(
            select(CustomerRecoverySession)
            .options(
                joinedload(CustomerRecoverySession.transaction).joinedload(Transaction.attempts),
                joinedload(CustomerRecoverySession.recovery_action).joinedload(RecoveryAction.recovery_case),
            )
            .where(CustomerRecoverySession.token == token)
        )
        if not cust_session:
            raise ValueError(f"Recovery token '{token}' not found.")

        if cust_session.status == "COMPLETED":
            return CustomerCheckoutSubmitResponse(
                success=True,
                transaction_id=str(cust_session.transaction_id),
                status="ALREADY_COMPLETED",
                payment_method=payment_method,
                message="This recovery payment has already been completed.",
                attempt_number=len(cust_session.transaction.attempts),
                recovered_at=cust_session.completed_at.isoformat() if cust_session.completed_at else now.isoformat(),
            )

        if _ensure_utc(cust_session.expires_at) < now:
            cust_session.status = "EXPIRED"
            session.commit()
            raise ValueError("This recovery payment link has expired.")

        txn = cust_session.transaction
        if txn.status == TransactionStatus.SUCCEEDED:
            cust_session.status = "COMPLETED"
            cust_session.completed_at = now
            session.commit()
            return CustomerCheckoutSubmitResponse(
                success=True,
                transaction_id=str(txn.id),
                status="SUCCEEDED",
                payment_method=payment_method,
                message="Transaction already succeeded.",
                attempt_number=len(txn.attempts),
                recovered_at=now.isoformat(),
            )

        attempts = sorted(txn.attempts or [], key=lambda a: a.attempt_number)
        next_attempt_number = len(attempts) + 1
        gateway = "NPCI_UPI" if payment_method.upper() == "UPI" else Gateway.RAZORPAY.value

        is_success = simulate_outcome.upper() == "SUCCESS" if simulate_outcome else True

        if is_success:
            new_attempt = PaymentAttempt(
                transaction_id=txn.id,
                attempt_number=next_attempt_number,
                payment_method=payment_method.upper(),
                gateway=gateway,
                failure_code=None,
            )
            session.add(new_attempt)

            txn.status = TransactionStatus.SUCCEEDED
            txn.version += 1

            cust_session.status = "COMPLETED"
            cust_session.completed_at = now

            rec_action = cust_session.recovery_action
            if rec_action:
                rec_action.status = "COMPLETED"
                rec_action.executed_at = now
                if rec_action.recovery_case:
                    rec_action.recovery_case.state = RecoveryState.RECOVERED
                    rec_action.recovery_case.version += 1

            # Outbox & Audit
            session.add(
                OutboxEvent(
                    event_type="payment.succeeded.v1",
                    aggregate_type="transaction",
                    aggregate_id=str(txn.id),
                    payload={
                        "event_id": str(uuid4()),
                        "transaction_id": str(txn.id),
                        "attempt_number": next_attempt_number,
                        "amount": str(txn.amount),
                        "payment_method": payment_method.upper(),
                        "channel": "CUSTOMER_PAYMENT_LINK",
                    },
                )
            )
            session.add(
                AuditLog(
                    transaction_id=txn.id,
                    event_type="recovery.customer_recovered.v1",
                    actor="customer_interactive",
                    reason_codes=["PAYMENT_LINK_COMPLETED", f"METHOD_{payment_method.upper()}"],
                    metadata_={
                        "token": token,
                        "session_id": str(cust_session.id),
                        "payment_method": payment_method.upper(),
                        "attempt_number": next_attempt_number,
                    },
                )
            )
            session.commit()

            return CustomerCheckoutSubmitResponse(
                success=True,
                transaction_id=str(txn.id),
                status="SUCCEEDED",
                payment_method=payment_method.upper(),
                message=f"Payment of ₹{txn.amount} successfully completed via {payment_method.upper()}.",
                attempt_number=next_attempt_number,
                recovered_at=now.isoformat(),
            )

        # Customer submission failed
        new_attempt = PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=next_attempt_number,
            payment_method=payment_method.upper(),
            gateway=gateway,
            failure_code="USER_CANCELLED",
        )
        session.add(new_attempt)
        session.commit()

        return CustomerCheckoutSubmitResponse(
            success=False,
            transaction_id=str(txn.id),
            status="FAILED",
            payment_method=payment_method.upper(),
            message="Payment attempt could not be processed. Please try again.",
            attempt_number=next_attempt_number,
            recovered_at=now.isoformat(),
        )

    # ========================================================================
    # 6. OPERATIONAL KPI METRICS
    # ========================================================================

    def get_execution_metrics(self, session: Session) -> ExecutionMetricsResponse:
        """Aggregate operational KPIs and recovery conversion rates."""
        total_actions = session.scalar(select(func.count()).select_from(RecoveryAction)) or 0
        succeeded = session.scalar(
            select(func.count()).select_from(RecoveryAction).where(RecoveryAction.status == "COMPLETED")
        ) or 0
        failed = session.scalar(
            select(func.count()).select_from(RecoveryAction).where(RecoveryAction.status == "FAILED")
        ) or 0
        scheduled = session.scalar(
            select(func.count()).select_from(RecoveryAction).where(RecoveryAction.status == "SCHEDULED")
        ) or 0

        # Calculate total recovered amount
        recovered_cases = session.scalars(
            select(RecoveryCase)
            .options(joinedload(RecoveryCase.transaction))
            .where(RecoveryCase.state == RecoveryState.RECOVERED)
        ).all()
        recovered_amount = Decimal("0.00")
        for c in recovered_cases:
            if c.transaction:
                recovered_amount += Decimal(str(c.transaction.amount))

        recovery_rate = round(succeeded / max(1, (succeeded + failed)), 4) if (succeeded + failed) > 0 else 0.0

        # Workflow breakdowns
        workflows = {
            "immediate_retry": {"action": "RETRY_SAME_METHOD", "total": 0, "succeeded": 0},
            "payment_method_switch": {"action": "SWITCH_TO_UPI/CARD/NB", "total": 0, "succeeded": 0},
            "delayed_retry": {"action": "DELAYED_RETRY", "total": 0, "succeeded": 0},
            "customer_recovery": {"action": "PAYMENT_LINK/NOTIFICATION", "total": 0, "succeeded": 0},
        }

        all_actions = session.scalars(select(RecoveryAction)).all()
        for a in all_actions:
            if a.action_type == ActionType.RETRY_SAME_METHOD:
                workflows["immediate_retry"]["total"] += 1
                if a.status == "COMPLETED":
                    workflows["immediate_retry"]["succeeded"] += 1
            elif a.action_type in (ActionType.SWITCH_TO_UPI, ActionType.SWITCH_TO_CARD, ActionType.SWITCH_TO_NETBANKING):
                workflows["payment_method_switch"]["total"] += 1
                if a.status == "COMPLETED":
                    workflows["payment_method_switch"]["succeeded"] += 1
            elif a.action_type == ActionType.DELAYED_RETRY:
                workflows["delayed_retry"]["total"] += 1
                if a.status == "COMPLETED":
                    workflows["delayed_retry"]["succeeded"] += 1
            elif a.action_type in (ActionType.CUSTOMER_NOTIFICATION, ActionType.PAYMENT_LINK):
                workflows["customer_recovery"]["total"] += 1
                if a.status == "COMPLETED":
                    workflows["customer_recovery"]["succeeded"] += 1

        return ExecutionMetricsResponse(
            total_executions=total_actions,
            successful_executions=succeeded,
            failed_executions=failed,
            scheduled_executions=scheduled,
            overall_recovery_rate=recovery_rate,
            total_recovered_amount=recovered_amount,
            by_workflow=workflows,
        )


# Singleton Engine Instance
recovery_execution_engine = RecoveryExecutionEngine()
