"""Core simulation engine for generating realistic payment transactions and attempts."""

from __future__ import annotations

from decimal import Decimal
import random
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    AuditLog,
    Customer,
    FailureEvent,
    OutboxEvent,
    PaymentAttempt,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.simulator import (
    BatchSimulationResponse,
    CreateSimulatedPaymentRequest,
    PaymentSimulationResponse,
    SimulateAttemptRequest,
    SimulateBatchRequest,
)
from backend.app.services.recovery_policy import evaluate_failure_policy
from backend.app.simulator.constants import (
    FAILURE_CATALOG,
    Gateway,
    PaymentMethod,
    SAMPLE_ISSUER_BANKS,
    SAMPLE_UPI_APPS,
    SCENARIO_PROFILES,
    SimulationScenario,
)


def _sample_weighted(weights_dict: dict[Any, float]) -> Any:
    """Sample a key from a dictionary using its values as relative weights."""
    items = list(weights_dict.keys())
    weights = list(weights_dict.values())
    return random.choices(items, weights=weights, k=1)[0]


def _generate_realistic_amount() -> Decimal:
    """Generate a realistic consumer transaction amount in INR."""
    buckets = [
        (99, 499, 0.35),
        (500, 1999, 0.40),
        (2000, 7999, 0.18),
        (8000, 24999, 0.05),
        (25000, 49999, 0.02),
    ]
    bucket_choices = range(len(buckets))
    bucket_weights = [b[2] for b in buckets]
    selected_idx = random.choices(bucket_choices, weights=bucket_weights, k=1)[0]
    min_val, max_val, _ = buckets[selected_idx]
    
    # Common price points ending in .00, .50, .99
    base_val = random.randint(min_val, max_val)
    cents = random.choice([0.0, 0.0, 0.0, 0.5, 0.99])
    return Decimal(f"{base_val + cents:.2f}")


def _generate_masked_instrument(payment_method: str) -> dict[str, str]:
    """Generate safe, masked reference metadata without sensitive data."""
    if payment_method == PaymentMethod.CARD.value:
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
    if payment_method == PaymentMethod.UPI.value:
        app = random.choice(SAMPLE_UPI_APPS)
        handle = random.choice(["okhdfcbank", "oksbi", "paytm", "apl", "ybl"])
        return {
            "upi_app": app,
            "vpa_handle": f"cust_{random.randint(100, 999)}@{handle}",
            "remitter_bank": random.choice(SAMPLE_ISSUER_BANKS),
        }
    if payment_method == PaymentMethod.NETBANKING.value:
        return {
            "bank_name": random.choice(SAMPLE_ISSUER_BANKS),
            "channel": "Retail NetBanking",
        }
    if payment_method == PaymentMethod.WALLET.value:
        return {
            "wallet_provider": random.choice(["Paytm Wallet", "Amazon Pay", "Mobikwik"]),
        }
    return {
        "bnpl_provider": random.choice(["LazyPay", "Simpl", "ZestMoney"]),
    }


class PaymentSimulator:
    """Service to generate realistic simulated transactions and attempt lifecycles."""

    def __init__(self, session: Session):
        self.session = session

    def simulate_payment(self, request: CreateSimulatedPaymentRequest) -> PaymentSimulationResponse:
        """Simulate a new payment transaction with attempt 1."""
        scenario_config = SCENARIO_PROFILES.get(
            request.scenario, SCENARIO_PROFILES[SimulationScenario.NORMAL_BALANCED]
        )

        # 1. Determine Payment Method
        if request.payment_method:
            method = request.payment_method.upper()
        else:
            method = _sample_weighted(scenario_config["method_weights"]).value

        # 2. Determine Gateway
        if request.gateway:
            gateway = request.gateway.upper()
        else:
            gateway = random.choice(list(Gateway)).value

        # 3. Determine Amount & Merchant
        amount = request.amount or _generate_realistic_amount()
        currency = request.currency.upper()
        merchant_id = request.merchant_id or f"merch_{random.randint(101, 109)}"

        # 4. Resolve or create Customer
        ext_cust_id = request.external_customer_id or f"cust_{uuid4().hex[:8]}"
        customer = self.session.scalar(
            select(Customer).where(Customer.external_customer_id == ext_cust_id)
        )
        if customer is None:
            customer = Customer(
                external_customer_id=ext_cust_id,
                merchant_id=merchant_id,
                preferred_payment_method=request.customer_preferred_method or method,
            )
            self.session.add(customer)
            self.session.flush()

        # 5. Determine Outcome (Deterministic vs Probabilistic)
        effective_success_rate = (
            request.success_rate_override
            if request.success_rate_override is not None
            else scenario_config["success_rate"]
        )

        if request.target_outcome:
            outcome = request.target_outcome.upper()
        elif request.target_failure_code:
            outcome = "FAIL"
        else:
            outcome = "SUCCESS" if random.random() < effective_success_rate else "FAIL"

        # 6. Create Transaction
        ext_txn_id = f"txn_sim_{uuid4().hex[:14]}"
        correlation_id = uuid4()

        transaction = Transaction(
            external_transaction_id=ext_txn_id,
            merchant_id=merchant_id,
            customer_id=customer.id,
            amount=amount,
            currency=currency,
            status=TransactionStatus.PROCESSING,
            version=1,
        )
        self.session.add(transaction)
        self.session.flush()

        # 7. Process Attempt 1
        return self._process_attempt(
            transaction=transaction,
            attempt_number=1,
            payment_method=method,
            gateway=gateway,
            outcome=outcome,
            target_failure_code=request.target_failure_code,
            scenario_config=scenario_config,
            correlation_id=correlation_id,
        )

    def simulate_attempt(
        self, transaction_id: UUID, request: SimulateAttemptRequest
    ) -> PaymentSimulationResponse:
        """Simulate a subsequent attempt on an existing transaction."""
        transaction = self.session.scalar(
            select(Transaction).where(Transaction.id == transaction_id)
        )
        if not transaction:
            raise ValueError(f"Transaction {transaction_id} not found")

        if transaction.status == TransactionStatus.SUCCEEDED:
            raise ValueError(f"Transaction {transaction_id} has already SUCCEEDED; cannot execute further attempts")

        # Find current highest attempt number
        attempts = self.session.scalars(
            select(PaymentAttempt).where(PaymentAttempt.transaction_id == transaction_id)
        ).all()
        next_attempt_number = len(attempts) + 1

        scenario_config = SCENARIO_PROFILES[SimulationScenario.NORMAL_BALANCED]

        # Use requested method or fallback to last attempt's method / UPI
        if request.payment_method:
            method = request.payment_method.upper()
        elif attempts:
            method = attempts[-1].payment_method
        else:
            method = PaymentMethod.UPI.value

        gateway = request.gateway.upper() if request.gateway else (attempts[-1].gateway if attempts else Gateway.RAZORPAY.value)

        # Determine outcome
        if request.target_outcome:
            outcome = request.target_outcome.upper()
        elif request.target_failure_code:
            outcome = "FAIL"
        else:
            outcome = "SUCCESS" if random.random() < 0.75 else "FAIL"

        correlation_id = uuid4()
        transaction.version += 1

        return self._process_attempt(
            transaction=transaction,
            attempt_number=next_attempt_number,
            payment_method=method,
            gateway=gateway,
            outcome=outcome,
            target_failure_code=request.target_failure_code,
            scenario_config=scenario_config,
            correlation_id=correlation_id,
        )

    def simulate_batch(self, request: SimulateBatchRequest) -> BatchSimulationResponse:
        """Generate a batch of simulated transactions with summary metrics."""
        results: list[PaymentSimulationResponse] = []
        success_count = 0
        failure_count = 0
        recoverable_count = 0
        hard_count = 0
        total_amount = Decimal("0.00")
        failure_codes: dict[str, int] = {}
        categories: dict[str, int] = {}

        for _ in range(request.count):
            item_req = CreateSimulatedPaymentRequest(
                merchant_id=request.merchant_id,
                scenario=request.scenario,
                success_rate_override=request.success_rate_override,
            )
            sim_res = self.simulate_payment(item_req)
            results.append(sim_res)
            total_amount += sim_res.amount

            if sim_res.outcome == "SUCCESS":
                success_count += 1
            else:
                failure_count += 1
                if sim_res.recoverable:
                    recoverable_count += 1
                else:
                    hard_count += 1

                code = sim_res.failure_code or "UNKNOWN"
                failure_codes[code] = failure_codes.get(code, 0) + 1

                cat = sim_res.failure_category or "UNKNOWN"
                categories[cat] = categories.get(cat, 0) + 1

        success_rate = round(success_count / request.count, 4) if request.count > 0 else 0.0

        return BatchSimulationResponse(
            total_simulated=request.count,
            success_count=success_count,
            failure_count=failure_count,
            success_rate=success_rate,
            total_amount=total_amount,
            recoverable_failure_count=recoverable_count,
            hard_failure_count=hard_count,
            failure_code_breakdown=failure_codes,
            category_breakdown=categories,
            transactions=results,
        )

    def _process_attempt(
        self,
        transaction: Transaction,
        attempt_number: int,
        payment_method: str,
        gateway: str | None,
        outcome: str,
        target_failure_code: str | None,
        scenario_config: dict[str, Any],
        correlation_id: UUID,
    ) -> PaymentSimulationResponse:
        """Internal helper to record attempt, failure facts, outbox publication, and audit log."""
        instrument_meta = _generate_masked_instrument(payment_method)
        latency_ms = random.randint(180, 1400) if outcome == "SUCCESS" else random.randint(400, 3200)

        if outcome == "SUCCESS":
            failure_code = None
            failure_def = None
            policy = None
            transaction.status = TransactionStatus.SUCCEEDED

            attempt = PaymentAttempt(
                transaction_id=transaction.id,
                attempt_number=attempt_number,
                payment_method=payment_method,
                gateway=gateway,
                failure_code=None,
            )
            self.session.add(attempt)
            self.session.flush()

            # Record Success Audit
            self.session.add(
                AuditLog(
                    transaction_id=transaction.id,
                    event_type="payment.succeeded.v1",
                    actor="payment_simulator",
                    reason_codes=["PAYMENT_COMPLETED_SUCCESSFULLY"],
                    metadata_={
                        "attempt_number": attempt_number,
                        "payment_method": payment_method,
                        "gateway": gateway,
                        "latency_ms": latency_ms,
                        "correlation_id": str(correlation_id),
                        "instrument": instrument_meta,
                    },
                )
            )

            # Record Outbox Event
            outbox_evt = OutboxEvent(
                event_type="payment.succeeded.v1",
                aggregate_type="transaction",
                aggregate_id=str(transaction.id),
                payload={
                    "event_id": str(uuid4()),
                    "correlation_id": str(correlation_id),
                    "transaction_id": str(transaction.id),
                    "external_transaction_id": transaction.external_transaction_id,
                    "attempt_number": attempt_number,
                    "amount": str(transaction.amount),
                    "currency": transaction.currency,
                    "payment_method": payment_method,
                    "gateway": gateway,
                },
            )
            self.session.add(outbox_evt)
            self.session.commit()
            self.session.refresh(transaction)

            return PaymentSimulationResponse(
                transaction_id=transaction.id,
                external_transaction_id=transaction.external_transaction_id,
                merchant_id=transaction.merchant_id,
                customer_id=transaction.customer_id,
                amount=transaction.amount,
                currency=transaction.currency,
                status=transaction.status.value,
                attempt_number=attempt_number,
                payment_method=payment_method,
                gateway=gateway,
                outcome="SUCCESS",
                outbox_event_id=outbox_evt.id,
                correlation_id=correlation_id,
                metadata={
                    "latency_ms": latency_ms,
                    "instrument": instrument_meta,
                },
                created_at=transaction.created_at,
            )

        # FAILED branch
        transaction.status = TransactionStatus.FAILED

        if target_failure_code:
            failure_code = target_failure_code.upper()
        else:
            failure_code = _sample_weighted(scenario_config["failure_weights"])

        failure_def = FAILURE_CATALOG.get(
            failure_code,
            FAILURE_CATALOG["TIMEOUT"],
        )
        policy = evaluate_failure_policy(failure_code)

        attempt = PaymentAttempt(
            transaction_id=transaction.id,
            attempt_number=attempt_number,
            payment_method=payment_method,
            gateway=gateway,
            failure_code=failure_code,
        )
        self.session.add(attempt)
        self.session.flush()

        source_event_id = f"evt_sim_{uuid4().hex[:12]}"
        failure_event = FailureEvent(
            source_event_id=source_event_id,
            transaction_id=transaction.id,
            attempt_id=attempt.id,
            failure_code=failure_code,
            category=policy.category,
            recoverable=policy.recoverable,
            payload={
                "error_message": failure_def.default_error_message,
                "description": failure_def.description,
                "payment_method": payment_method,
                "gateway": gateway,
                "latency_ms": latency_ms,
                "instrument": instrument_meta,
                "correlation_id": str(correlation_id),
            },
        )
        self.session.add(failure_event)
        self.session.flush()

        # Audit Log
        self.session.add(
            AuditLog(
                transaction_id=transaction.id,
                event_type="payment.failed.v1",
                actor="payment_simulator",
                reason_codes=list(policy.reason_codes),
                metadata_={
                    "attempt_number": attempt_number,
                    "failure_code": failure_code,
                    "category": policy.category,
                    "recoverable": policy.recoverable,
                    "source_event_id": source_event_id,
                    "correlation_id": str(correlation_id),
                    "instrument": instrument_meta,
                },
            )
        )

        # Outbox Event
        outbox_evt = OutboxEvent(
            event_type="payment.failed.v1",
            aggregate_type="transaction",
            aggregate_id=str(transaction.id),
            payload={
                "event_id": source_event_id,
                "correlation_id": str(correlation_id),
                "transaction_id": str(transaction.id),
                "external_transaction_id": transaction.external_transaction_id,
                "failure_event_id": str(failure_event.id),
                "attempt_number": attempt_number,
                "amount": str(transaction.amount),
                "currency": transaction.currency,
                "payment_method": payment_method,
                "gateway": gateway,
                "failure_code": failure_code,
                "category": policy.category,
                "recoverable": policy.recoverable,
            },
        )
        self.session.add(outbox_evt)
        self.session.commit()
        self.session.refresh(transaction)

        return PaymentSimulationResponse(
            transaction_id=transaction.id,
            external_transaction_id=transaction.external_transaction_id,
            merchant_id=transaction.merchant_id,
            customer_id=transaction.customer_id,
            amount=transaction.amount,
            currency=transaction.currency,
            status=transaction.status.value,
            attempt_number=attempt_number,
            payment_method=payment_method,
            gateway=gateway,
            outcome="FAIL",
            failure_code=failure_code,
            failure_category=policy.category,
            recoverable=policy.recoverable,
            error_message=failure_def.default_error_message,
            outbox_event_id=outbox_evt.id,
            correlation_id=correlation_id,
            metadata={
                "latency_ms": latency_ms,
                "instrument": instrument_meta,
                "permitted_actions": [a.value for a in policy.permitted_actions],
                "reason_codes": list(policy.reason_codes),
            },
            created_at=transaction.created_at,
        )
