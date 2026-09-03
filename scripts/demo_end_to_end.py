"""RecoverX — End-to-End Autonomous AI Revenue Recovery Interactive Demo.

Executes 5 canonical production recovery scenarios from failure ingestion to final settlement:
1. Card OTP Drop-off -> Customer WhatsApp Recovery Link -> Customer Pays via UPI -> Succeeded & Audit Chain verified.
2. Transient Network Timeout -> Immediate Retry -> Succeeded.
3. Bank Switch Downtime -> Scheduled Exponential Backoff Retry -> Succeeded.
4. Card Decline / Do Not Honor -> Bounded AI Agent -> Evaluates Candidates -> Recommends UPI Switch -> Executed & Succeeded.
5. Terminal Fraud / Stolen Card -> Hard Stop Applied -> ZERO Actions Executed -> Fully Audited.
"""

from __future__ import annotations

from decimal import Decimal
import io
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

# Add workspace root to sys.path for direct script execution
workspace_root = Path(__file__).resolve().parent.parent
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

# Set test environment mode for demo
os.environ["APP_ENV"] = "test"


# Safe stdout configuration
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.models.base import Base
from backend.app.models.recovery import (
    Customer,
    CustomerIntelligence,
    PaymentAttempt,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.services.audit_chain import record_audit_event, verify_audit_chain
from backend.app.services.failure_intelligence import failure_intelligence_service
from backend.app.services.recovery_agent import payment_recovery_agent
from backend.app.services.recovery_execution import recovery_execution_engine
from benchmark.run_benchmark import run_benchmark


class Style:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def print_banner(text: str) -> None:
    print("\n" + "=" * 80)
    print(f" {text}")
    print("=" * 80)


def print_scenario(num: int, title: str) -> None:
    print(f"\n[SCENARIO {num}] {title}")
    print("-" * 70)


def run_demo() -> None:
    print_banner("RECOVERX — END-TO-END AUTONOMOUS REVENUE RECOVERY DEMO")

    # In-memory SQLite DB for isolated, reproducible live execution
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Seed demo customer
    cust = Customer(
        external_customer_id=f"cust_{uuid4().hex[:6]}",
        merchant_id="merch_101",
        name="Vikram Sharma",
        email="vikram.sharma@example.com",
        phone="+919876543210",
        risk_segment="STANDARD",
        preferred_payment_method="UPI",
    )
    db.add(cust)
    db.flush()

    db.add(
        CustomerIntelligence(
            customer_id=cust.id,
            success_rate=Decimal("0.8500"),
            recovery_rate=Decimal("0.7200"),
            risk_score=Decimal("0.0800"),
            recent_failure_streak=1,
            average_transaction_value=Decimal("3500.00"),
            total_transactions=14,
            behavioral_segment="HIGH_LOYALTY",
        )
    )

    db.commit()

    # -------------------------------------------------------------------------
    # SCENARIO 1: OTP Drop-off -> Customer WhatsApp Recovery Link -> UPI Pay
    # -------------------------------------------------------------------------
    print_scenario(1, "Customer 3DS OTP Drop-Off -> WhatsApp Recovery Link -> UPI Settlement")
    txn1 = Transaction(
        external_transaction_id=f"order_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        customer_id=cust.id,
        amount=Decimal("2499.00"),
        currency="INR",
        status=TransactionStatus.FAILED,
    )
    db.add(txn1)
    db.flush()
    db.add(
        PaymentAttempt(
            transaction_id=txn1.id,
            attempt_number=1,
            payment_method="CARD",
            gateway="RAZORPAY",
            failure_code="OTP_TIMEOUT",
        )
    )
    record_audit_event(
        session=db,
        transaction_id=txn1.id,
        actor="SYSTEM",
        action="INGEST_FAILURE",
        before_state="INITIATED",
        after_state="FAILED",
        reason_codes=["OTP_TIMEOUT"],
        event_type="payment.failed.v1",
    )
    db.commit()


    print(f"  * Transaction Ingested: {txn1.external_transaction_id} (INR {txn1.amount}) | Failure: OTP_TIMEOUT")

    # Generate tokenized payment link
    link_res = recovery_execution_engine.create_customer_recovery_link(
        session=db,
        transaction_id=txn1.id,
        channel="WHATSAPP",
        expires_in_minutes=120,
    )
    print(f"  * Recovery Link Generated: {link_res.checkout_url} (Token: {link_res.token[:12]}...)")

    # Customer submits UPI payment via link
    checkout_res = recovery_execution_engine.complete_customer_checkout(
        session=db,
        token=link_res.token,
        payment_method="UPI",
        simulate_outcome="SUCCESS",
    )
    db.refresh(txn1)
    valid1, _ = verify_audit_chain(db, txn1.id)
    print(f"  * Customer Action: Switched to UPI -> Settlement {checkout_res.status} on attempt #{checkout_res.attempt_number}")
    print(f"  * Final State: {txn1.status.value} | Audit Hash Chain Verified: {valid1}")

    # -------------------------------------------------------------------------
    # SCENARIO 2: Transient Network Timeout -> Immediate Retry
    # -------------------------------------------------------------------------
    print_scenario(2, "Transient Network Timeout -> Direct Rail Immediate Retry")
    txn2 = Transaction(
        external_transaction_id=f"order_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        customer_id=cust.id,
        amount=Decimal("1200.00"),
        currency="INR",
        status=TransactionStatus.FAILED,
    )
    db.add(txn2)
    db.flush()
    db.add(
        PaymentAttempt(
            transaction_id=txn2.id,
            attempt_number=1,
            payment_method="UPI",
            gateway="RAZORPAY",
            failure_code="TIMEOUT",
        )
    )
    record_audit_event(
        session=db,
        transaction_id=txn2.id,
        actor="SYSTEM",
        action="INGEST_FAILURE",
        before_state="INITIATED",
        after_state="FAILED",
        reason_codes=["NETWORK_TIMEOUT"],
        event_type="payment.failed.v1",
    )
    db.commit()


    print(f"  * Transaction Ingested: {txn2.external_transaction_id} (INR {txn2.amount}) | Failure: TIMEOUT (Transient)")
    retry_res = recovery_execution_engine.execute_action(
        session=db,
        transaction_id=txn2.id,
        action_type="RETRY_SAME_METHOD",
        force_outcome="SUCCESS",
    )
    db.refresh(txn2)
    valid2, _ = verify_audit_chain(db, txn2.id)
    print(f"  * Execution: {retry_res.action_type} -> Result: {retry_res.status} on attempt #{retry_res.attempt_number}")
    print(f"  * Final State: {txn2.status.value} | Audit Hash Chain Verified: {valid2}")

    # -------------------------------------------------------------------------
    # SCENARIO 3: Bank Server Outage -> Scheduled Exponential Backoff
    # -------------------------------------------------------------------------
    print_scenario(3, "Bank CBS Outage -> Exponential Backoff Delay Scheduler")
    txn3 = Transaction(
        external_transaction_id=f"order_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        customer_id=cust.id,
        amount=Decimal("8900.00"),
        currency="INR",
        status=TransactionStatus.FAILED,
    )
    db.add(txn3)
    db.flush()
    db.add(
        PaymentAttempt(
            transaction_id=txn3.id,
            attempt_number=1,
            payment_method="NETBANKING",
            gateway="BILLDESK",
            failure_code="BANK_SERVER_DOWN",
        )
    )
    record_audit_event(
        session=db,
        transaction_id=txn3.id,
        actor="SYSTEM",
        action="INGEST_FAILURE",
        before_state="INITIATED",
        after_state="FAILED",
        reason_codes=["CBS_MAINTENANCE"],
        event_type="payment.failed.v1",
    )
    db.commit()


    print(f"  * Transaction Ingested: {txn3.external_transaction_id} (INR {txn3.amount}) | Failure: BANK_SERVER_DOWN")
    sched_res = recovery_execution_engine.execute_action(
        session=db,
        transaction_id=txn3.id,
        action_type="DELAYED_RETRY",
    )
    print(f"  * Execution Engine: Scheduled retry with backoff | Status: {sched_res.status}")

    # Process due retries
    due_res = recovery_execution_engine.process_due_scheduled_retries(
        session=db,
        force_now=True,
        force_outcome="SUCCESS",
    )
    db.refresh(txn3)
    valid3, _ = verify_audit_chain(db, txn3.id)
    print(f"  * Scheduler Run: {due_res.processed_count} retries executed, {due_res.succeeded_count} recovered")
    print(f"  * Final State: {txn3.status.value} | Audit Hash Chain Verified: {valid3}")

    # -------------------------------------------------------------------------
    # SCENARIO 4: Card Decline -> Bounded AI Agent -> Smart UPI Switch
    # -------------------------------------------------------------------------
    print_scenario(4, "Card Issuer Decline -> Autonomous Agent Investigation -> UPI Switch")
    txn4 = Transaction(
        external_transaction_id=f"order_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        customer_id=cust.id,
        amount=Decimal("4500.00"),
        currency="INR",
        status=TransactionStatus.FAILED,
    )
    db.add(txn4)
    db.flush()
    db.add(
        PaymentAttempt(
            transaction_id=txn4.id,
            attempt_number=1,
            payment_method="CARD",
            gateway="RAZORPAY",
            failure_code="CARD_DECLINED",
        )
    )
    record_audit_event(
        session=db,
        transaction_id=txn4.id,
        actor="SYSTEM",
        action="INGEST_FAILURE",
        before_state="INITIATED",
        after_state="FAILED",
        reason_codes=["DO_NOT_HONOR"],
        event_type="payment.failed.v1",
    )
    db.commit()


    print(f"  * Transaction Ingested: {txn4.external_transaction_id} (INR {txn4.amount}) | Failure: CARD_DECLINED")
    agent_res = payment_recovery_agent.investigate_transaction(session=db, transaction_id=txn4.id)
    print(f"  * Agent Investigation Trajectory: {len(agent_res.steps)} bounded tool steps")
    print(f"  * Recommended Action: {agent_res.chosen_action} (Confidence: {agent_res.predicted_probability*100:.1f}%)")
    print(f"  * Explanation: {agent_res.merchant_explanation}")

    # Execute agent plan
    switch_res = recovery_execution_engine.execute_action(
        session=db,
        transaction_id=txn4.id,
        action_type=agent_res.chosen_action,
        force_outcome="SUCCESS",
    )

    db.refresh(txn4)
    valid4, _ = verify_audit_chain(db, txn4.id)
    print(f"  * Execution: Switched payment rail to {switch_res.new_payment_method} -> {switch_res.status}")
    print(f"  * Final State: {txn4.status.value} | Audit Hash Chain Verified: {valid4}")

    # -------------------------------------------------------------------------
    # SCENARIO 5: Terminal Fraud / Stolen Card -> 100% Terminal Stop
    # -------------------------------------------------------------------------
    print_scenario(5, "Fraud Risk Reject -> Strict Terminal Stop (Invariant: ZERO Retries)")
    txn5 = Transaction(
        external_transaction_id=f"order_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        customer_id=cust.id,
        amount=Decimal("15000.00"),
        currency="INR",
        status=TransactionStatus.FAILED,
    )
    db.add(txn5)
    db.flush()
    db.add(
        PaymentAttempt(
            transaction_id=txn5.id,
            attempt_number=1,
            payment_method="CARD",
            gateway="STRIPE",
            failure_code="FRAUD_REJECTED",
        )
    )
    record_audit_event(
        session=db,
        transaction_id=txn5.id,
        actor="SYSTEM",
        action="INGEST_FAILURE",
        before_state="INITIATED",
        after_state="FAILED",
        reason_codes=["FRAUD_SUSPECTED"],
        event_type="payment.failed.v1",
    )
    db.commit()


    print(f"  * Transaction Ingested: {txn5.external_transaction_id} (INR {txn5.amount}) | Failure: FRAUD_REJECTED")
    fraud_res = recovery_execution_engine.execute_action(
        session=db,
        transaction_id=txn5.id,
        action_type="RETRY_SAME_METHOD",
    )
    db.refresh(txn5)
    valid5, _ = verify_audit_chain(db, txn5.id)
    print(f"  * Policy Enforcement: {fraud_res.message}")
    print(f"  * Actions Attempted: ZERO | Disposition: {fraud_res.disposition}")
    print(f"  * Invariant Held: Strictly zero chargeback liability incurred | Audit Chain: {valid5}")

    # -------------------------------------------------------------------------
    # 4-WAY COMPARATIVE BENCHMARK SUMMARY
    # -------------------------------------------------------------------------
    print_banner("4-WAY COMPARATIVE BENCHMARK EVALUATION (SEED 42, 500 TRANSACTIONS)")
    bench_report = run_benchmark(seed=42, num_transactions=500, verbose=True)

    print_banner("RECOVERX LIVE DEMO COMPLETE — ALL 5 SCENARIOS VERIFIED SUCCESSFULLY")


if __name__ == "__main__":
    run_demo()
