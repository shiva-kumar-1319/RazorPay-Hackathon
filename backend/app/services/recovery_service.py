"""Recovery Orchestrator and Service for processing failed-payment events."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_current_session, get_session_factory
from backend.app.models.recovery import (
    ActionType,
    AuditLog,
    Customer,
    CustomerIntelligence,
    FailureEvent,
    OutboxEvent,
    PaymentAttempt,
    ProcessedEvent,
    QuarantineEvent,
    RecoveryAction,
    RecoveryCase,
    RecoveryState,
    Transaction,
)
from backend.app.schemas.events import DomainEventEnvelope
from backend.app.services.customer_intelligence import compute_customer_intelligence
from backend.app.services.event_bus import EventBus, get_event_bus
from backend.app.services.recovery_policy import evaluate_failure_policy

logger = logging.getLogger("recoverx.recovery_service")


class RecoveryOrchestrator:
    """Consumes payment.failed.v1 events, enforces policy gates, creates recovery cases & candidate actions."""

    CONSUMER_NAME = "recovery_orchestrator"

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or get_event_bus()
        self._register_subscriptions()

    def _register_subscriptions(self) -> None:
        """Subscribe to payment failure domain events on the event bus."""
        self.event_bus.subscribe("payment.failed.v1", self.handle_payment_failed_event)

    def handle_payment_failed_event(self, event: DomainEventEnvelope) -> RecoveryCase | None:
        """Handle a payment.failed.v1 event with idempotent consumer semantics."""
        active_session = get_current_session()
        if active_session is not None:
            return self.process_payment_failure(active_session, event)

        session_factory = get_session_factory()
        with session_factory() as session:
            return self.process_payment_failure(session, event)


    def process_payment_failure(self, session: Session, event: DomainEventEnvelope) -> RecoveryCase | None:
        """Core idempotent processor for a single payment failure event."""
        event_id_str = str(event.event_id)

        # 1. Idempotency Check: deduplicate via processed_events table
        existing_processed = session.scalar(
            select(ProcessedEvent).where(
                ProcessedEvent.consumer_name == self.CONSUMER_NAME,
                ProcessedEvent.event_id == event_id_str,
            )
        )
        if existing_processed:
            logger.info("Duplicate event %s already processed by %s. Skipping.", event_id_str, self.CONSUMER_NAME)
            # Find and return existing recovery case for transaction if any
            txn_id_str = event.aggregate_id or event.payload.get("transaction_id")
            if txn_id_str:
                try:
                    return session.scalar(
                        select(RecoveryCase).where(RecoveryCase.transaction_id == UUID(str(txn_id_str)))
                    )
                except Exception:
                    pass
            return None

        # 2. Locate Transaction
        txn_id_str = event.aggregate_id or event.payload.get("transaction_id")
        if not txn_id_str:
            quarantine = QuarantineEvent(
                source_event_id=event_id_str,
                event_type=event.event_type,
                consumer_name=self.CONSUMER_NAME,
                reason="Missing aggregate_id / transaction_id in event envelope",
                payload=event.model_dump(mode="json"),
                status="QUARANTINED",
            )
            session.add(quarantine)
            session.commit()
            return None

        try:
            txn_uuid = UUID(str(txn_id_str))
        except (ValueError, TypeError):
            quarantine = QuarantineEvent(
                source_event_id=event_id_str,
                event_type=event.event_type,
                consumer_name=self.CONSUMER_NAME,
                reason=f"Invalid transaction UUID format: {txn_id_str}",
                payload=event.model_dump(mode="json"),
                status="QUARANTINED",
            )
            session.add(quarantine)
            session.commit()
            return None

        transaction = session.scalar(
            select(Transaction)
            .options(
                joinedload(Transaction.attempts),
                joinedload(Transaction.recovery_cases),
                joinedload(Transaction.customer).joinedload(Customer.intelligence),
                joinedload(Transaction.customer).joinedload(Customer.transactions),
            )
            .where(Transaction.id == txn_uuid)
        )
        if not transaction:
            quarantine = QuarantineEvent(
                source_event_id=event_id_str,
                event_type=event.event_type,
                consumer_name=self.CONSUMER_NAME,
                reason=f"Transaction {txn_id_str} not found in database",
                payload=event.model_dump(mode="json"),
                status="QUARANTINED",
            )
            session.add(quarantine)
            session.commit()
            return None

        # 3. Extract failure details & Customer Intelligence Context
        failure_code = event.payload.get("failure_code", "UNKNOWN")
        policy = evaluate_failure_policy(failure_code)
        amount = Decimal(str(transaction.amount))

        # Retrieve or compute customer intelligence if customer is present
        customer_intel = None
        if transaction.customer:
            try:
                customer_intel = compute_customer_intelligence(session, transaction.customer.id, persist=False)
            except Exception as ex:
                logger.warning("Could not compute customer intelligence for %s: %s", transaction.customer.id, ex)

        # 4. Create or Update Recovery Case
        existing_case = session.scalar(
            select(RecoveryCase)
            .options(joinedload(RecoveryCase.actions))
            .where(RecoveryCase.transaction_id == transaction.id)
        )

        if existing_case is None:
            initial_state = RecoveryState.STOPPED if not policy.recoverable else RecoveryState.OPEN
            recovery_case = RecoveryCase(
                transaction_id=transaction.id,
                state=initial_state,
                policy_version="policy.v1",
                version=1,
            )
            session.add(recovery_case)
            session.flush()
        else:
            recovery_case = existing_case
            if not policy.recoverable:
                recovery_case.state = RecoveryState.STOPPED
            recovery_case.version += 1

        # 5. Generate Candidate Actions based on Failure Code Taxonomy & Customer Intelligence
        actions: list[RecoveryAction] = []
        now = datetime.now(timezone.utc)

        if not policy.recoverable:
            # Hard failure: STOP_RECOVERY
            stop_idempotency = f"act_{recovery_case.id}_stop_{uuid4().hex[:8]}"
            stop_action = RecoveryAction(
                recovery_case_id=recovery_case.id,
                action_type=ActionType.STOP_RECOVERY,
                idempotency_key=stop_idempotency,
                selected=True,
                probability=Decimal("0.0000"),
                expected_value=Decimal("0.00"),
                reason_codes=list(policy.reason_codes),
            )
            session.add(stop_action)
            actions.append(stop_action)
        else:
            # Recoverable Failures: Map taxonomy to permitted candidate actions with customer intelligence
            candidates = self._generate_candidate_actions(
                recovery_case_id=recovery_case.id,
                failure_code=failure_code,
                category=policy.category,
                amount=amount,
                reason_codes=list(policy.reason_codes),
                customer_intel=customer_intel,
            )
            for act in candidates:
                session.add(act)
                actions.append(act)

        session.flush()

        # 6. Append Immutable Audit Log with Customer Context
        audit_meta = {
            "recovery_case_id": str(recovery_case.id),
            "state": recovery_case.state.value,
            "category": policy.category,
            "recoverable": policy.recoverable,
            "actions_generated": [a.action_type.value for a in actions],
            "source_event_id": event_id_str,
        }
        if customer_intel:
            audit_meta.update({
                "customer_id": str(customer_intel.customer_id),
                "customer_behavioral_segment": customer_intel.behavioral_segment,
                "customer_preferred_method": customer_intel.preferred_payment_method,
                "customer_risk_score": float(customer_intel.risk_score),
            })

        session.add(
            AuditLog(
                transaction_id=transaction.id,
                event_type="recovery.case_opened.v1",
                actor=self.CONSUMER_NAME,
                reason_codes=list(policy.reason_codes),
                metadata_=audit_meta,
            )
        )

        # 7. Record in processed_events (Consumer Idempotency Guard)
        processed_record = ProcessedEvent(
            consumer_name=self.CONSUMER_NAME,
            event_id=event_id_str,
            event_type=event.event_type,
            processed_at=now,
        )
        session.add(processed_record)

        # 8. Emit Outbox Events (failure.classified.v1 & recovery.case_opened.v1)
        session.add(
            OutboxEvent(
                event_type="failure.classified.v1",
                aggregate_type="transaction",
                aggregate_id=str(transaction.id),
                payload={
                    "event_id": str(uuid4()),
                    "correlation_id": str(event.correlation_id),
                    "transaction_id": str(transaction.id),
                    "failure_code": failure_code,
                    "category": policy.category,
                    "recoverable": policy.recoverable,
                    "reason_codes": list(policy.reason_codes),
                },
            )
        )
        session.add(
            OutboxEvent(
                event_type="recovery.case_opened.v1",
                aggregate_type="recovery_case",
                aggregate_id=str(recovery_case.id),
                payload={
                    "event_id": str(uuid4()),
                    "correlation_id": str(event.correlation_id),
                    "recovery_case_id": str(recovery_case.id),
                    "transaction_id": str(transaction.id),
                    "merchant_id": transaction.merchant_id,
                    "state": recovery_case.state.value,
                    "policy_version": recovery_case.policy_version,
                    "candidate_actions": [a.action_type.value for a in actions],
                },
            )
        )

        session.commit()
        session.refresh(recovery_case)
        logger.info(
            "Processed payment failure for txn %s -> case %s (%s, %d actions)",
            transaction.id,
            recovery_case.id,
            recovery_case.state.value,
            len(actions),
        )
        return recovery_case

    def _generate_candidate_actions(
        self,
        recovery_case_id: UUID,
        failure_code: str,
        category: str,
        amount: Decimal,
        reason_codes: list[str],
        customer_intel: CustomerIntelligence | None = None,
    ) -> list[RecoveryAction]:
        """Generate ranked candidate recovery actions adhering to deterministic recovery taxonomy and customer context."""
        actions: list[RecoveryAction] = []
        customer_reasons: list[str] = []

        # Customer behavioral boosts & tags
        upi_prob_boost = Decimal("0.00")
        card_prob_boost = Decimal("0.00")
        link_prob_boost = Decimal("0.00")

        if customer_intel:
            seg = customer_intel.behavioral_segment
            pref = (customer_intel.preferred_payment_method or "").upper()
            
            if seg == "VIP_HIGH_VALUE":
                customer_reasons.append("CUSTOMER_VIP_TIER_PRIORITY")
                upi_prob_boost += Decimal("0.05")
                link_prob_boost += Decimal("0.05")
            elif seg == "UPI_MOBILE_PREFERRED" or pref == "UPI":
                customer_reasons.append("CUSTOMER_HISTORICAL_UPI_AFFINITY")
                upi_prob_boost += Decimal("0.07")
            elif seg == "CARD_DECLINE_PRONE_RECOVERABLE":
                customer_reasons.append("CUSTOMER_REPEATED_CARD_DECLINE_HISTORY")
                # Lower retry same method probability
                card_prob_boost -= Decimal("0.10")
            elif seg == "HIGH_FAILURE_RISK":
                customer_reasons.append("CUSTOMER_HIGH_FAILURE_STREAK_GUARD")
            elif seg == "FIRST_TIME_SHOPPER" or seg == "NEW_CUSTOMER":
                customer_reasons.append("CUSTOMER_NEW_PROFILE_BASELINE")

        effective_reasons = reason_codes + customer_reasons

        if category == "PAYMENT_METHOD" or failure_code in ("CARD_DECLINED", "CARD_TYPE_NOT_SUPPORTED", "MANDATE_FAILED"):
            upi_prob = min(Decimal("0.9800"), Decimal("0.8500") + upi_prob_boost)
            link_prob = min(Decimal("0.9000"), Decimal("0.6500") + link_prob_boost)
            
            actions.append(
                RecoveryAction(
                    recovery_case_id=recovery_case_id,
                    action_type=ActionType.SWITCH_TO_UPI,
                    idempotency_key=f"act_{recovery_case_id}_upi_{uuid4().hex[:8]}",
                    selected=True,
                    probability=upi_prob,
                    expected_value=(amount * upi_prob).quantize(Decimal("0.01")),
                    reason_codes=effective_reasons + ["RECOMMENDED_SAFE_UPI", "ISSUER_DECLINE_BYPASS"],
                )
            )
            actions.append(
                RecoveryAction(
                    recovery_case_id=recovery_case_id,
                    action_type=ActionType.PAYMENT_LINK,
                    idempotency_key=f"act_{recovery_case_id}_link_{uuid4().hex[:8]}",
                    selected=False,
                    probability=link_prob,
                    expected_value=(amount * link_prob).quantize(Decimal("0.01")),
                    reason_codes=effective_reasons + ["FALLBACK_CHECKOUT_LINK"],
                )
            )

        elif category == "CUSTOMER_ACTION" or failure_code in ("OTP_TIMEOUT", "3DS_FAILURE", "INSUFFICIENT_FUNDS", "INCORRECT_PIN", "USER_CANCELLED"):
            notif_prob = min(Decimal("0.9500"), Decimal("0.7200") + (Decimal("0.05") if customer_intel and customer_intel.behavioral_segment == "VIP_HIGH_VALUE" else Decimal("0.00")))
            link_prob = min(Decimal("0.9000"), Decimal("0.6000") + link_prob_boost)

            actions.append(
                RecoveryAction(
                    recovery_case_id=recovery_case_id,
                    action_type=ActionType.CUSTOMER_NOTIFICATION,
                    idempotency_key=f"act_{recovery_case_id}_notif_{uuid4().hex[:8]}",
                    selected=True,
                    probability=notif_prob,
                    expected_value=(amount * notif_prob).quantize(Decimal("0.01")),
                    reason_codes=effective_reasons + ["FRICTIONLESS_APP_NOTIFICATION", "PROMPT_USER_RETRY"],
                )
            )
            actions.append(
                RecoveryAction(
                    recovery_case_id=recovery_case_id,
                    action_type=ActionType.PAYMENT_LINK,
                    idempotency_key=f"act_{recovery_case_id}_link_{uuid4().hex[:8]}",
                    selected=False,
                    probability=link_prob,
                    expected_value=(amount * link_prob).quantize(Decimal("0.01")),
                    reason_codes=effective_reasons + ["PERSISTENT_PAYMENT_URL"],
                )
            )

        elif category == "TEMPORARY" or failure_code in ("TIMEOUT", "NETWORK_ERROR", "UPI_FAILURE", "GATEWAY_ERROR", "BANK_SERVER_DOWN"):
            delay_prob = Decimal("0.7800")
            same_prob = max(Decimal("0.2000"), Decimal("0.5500") + card_prob_boost)

            actions.append(
                RecoveryAction(
                    recovery_case_id=recovery_case_id,
                    action_type=ActionType.DELAYED_RETRY,
                    idempotency_key=f"act_{recovery_case_id}_delretry_{uuid4().hex[:8]}",
                    selected=True,
                    probability=delay_prob,
                    expected_value=(amount * delay_prob).quantize(Decimal("0.01")),
                    reason_codes=effective_reasons + ["TEMPORARY_NETWORK_BACKOFF", "EXPONENTIAL_RETRY_SCHEDULE"],
                )
            )
            actions.append(
                RecoveryAction(
                    recovery_case_id=recovery_case_id,
                    action_type=ActionType.RETRY_SAME_METHOD,
                    idempotency_key=f"act_{recovery_case_id}_sameretry_{uuid4().hex[:8]}",
                    selected=False,
                    probability=same_prob,
                    expected_value=(amount * same_prob).quantize(Decimal("0.01")),
                    reason_codes=effective_reasons + ["IMMEDIATE_RETRY_FALLBACK"],
                )
            )

        else:
            # Default fallback
            link_prob = Decimal("0.6000")
            actions.append(
                RecoveryAction(
                    recovery_case_id=recovery_case_id,
                    action_type=ActionType.PAYMENT_LINK,
                    idempotency_key=f"act_{recovery_case_id}_link_{uuid4().hex[:8]}",
                    selected=True,
                    probability=link_prob,
                    expected_value=(amount * link_prob).quantize(Decimal("0.01")),
                    reason_codes=effective_reasons + ["GENERIC_RECOVERY_LINK"],
                )
            )

        return actions


# Query & Pipeline Inspection Functions


def list_recovery_cases(
    session: Session,
    merchant_id: str | None = None,
    state: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[RecoveryCase]]:
    """List recovery cases with optional merchant and state filters."""
    query = (
        select(RecoveryCase)
        .join(Transaction, RecoveryCase.transaction_id == Transaction.id)
        .options(joinedload(RecoveryCase.actions), joinedload(RecoveryCase.transaction))
    )

    if merchant_id:
        query = query.where(Transaction.merchant_id == merchant_id)
    if state:
        try:
            state_enum = RecoveryState(state.upper())
            query = query.where(RecoveryCase.state == state_enum)
        except ValueError:
            pass

    count_stmt = select(func.count()).select_from(query.subquery())
    total = session.scalar(count_stmt) or 0

    items = list(
        session.scalars(
            query.order_by(RecoveryCase.created_at.desc()).limit(limit).offset(offset)
        ).unique().all()
    )

    return total, items


def get_recovery_case_by_id(session: Session, case_id: UUID) -> RecoveryCase | None:
    """Fetch single recovery case with full action set and transaction relationship."""
    return session.scalar(
        select(RecoveryCase)
        .options(
            joinedload(RecoveryCase.actions),
            joinedload(RecoveryCase.transaction).joinedload(Transaction.attempts),
        )
        .where(RecoveryCase.id == case_id)
    )


def get_pipeline_metrics(session: Session) -> dict[str, Any]:
    """Calculate pipeline operational health metrics."""
    outbox_pending = session.scalar(
        select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))
    ) or 0

    outbox_published = session.scalar(
        select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_not(None))
    ) or 0

    processed_events = session.scalar(
        select(func.count()).select_from(ProcessedEvent)
    ) or 0

    quarantine_events = session.scalar(
        select(func.count()).select_from(QuarantineEvent)
    ) or 0

    total_cases = session.scalar(
        select(func.count()).select_from(RecoveryCase)
    ) or 0

    open_cases = session.scalar(
        select(func.count()).select_from(RecoveryCase).where(RecoveryCase.state == RecoveryState.OPEN)
    ) or 0

    stopped_cases = session.scalar(
        select(func.count()).select_from(RecoveryCase).where(RecoveryCase.state == RecoveryState.STOPPED)
    ) or 0

    return {
        "outbox_pending_count": outbox_pending,
        "outbox_published_count": outbox_published,
        "processed_events_count": processed_events,
        "quarantine_events_count": quarantine_events,
        "total_recovery_cases": total_cases,
        "open_recovery_cases": open_cases,
        "stopped_recovery_cases": stopped_cases,
        "pipeline_healthy": quarantine_events == 0 or (quarantine_events / max(1, processed_events)) < 0.05,
    }


# Singleton orchestrator instance
recovery_orchestrator = RecoveryOrchestrator()
