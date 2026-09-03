"""Unit and integration tests for Day 13 Evaluation & Business Proof Service."""

from decimal import Decimal
from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    ActionType,
    Customer,
    CustomerIntelligence,
    FailureEvent,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.evaluation import BenchmarkStrategy
from backend.app.services.evaluation_service import evaluation_service


def test_benchmark_simulation_all_strategies(db_session: Session):
    """Verify comparative benchmark evaluates No Action, Blind Retry, Heuristics, and RecoverX AI."""
    res = evaluation_service.run_benchmark(
        session=db_session,
        merchant_id="merch_101",
        num_transactions=60,
        seed=42,
    )

    assert res.total_transactions == 60
    assert res.total_failed_gmv > 0
    assert "NO_ACTION" in res.strategies
    assert "BLIND_RETRY" in res.strategies
    assert "RULE_BASED_HEURISTIC" in res.strategies
    assert "RECOVERX_AI" in res.strategies

    # 1. No Action Baseline
    no_act = res.strategies["NO_ACTION"]
    assert no_act.strategy == BenchmarkStrategy.NO_ACTION
    assert no_act.recovered_txns == 0
    assert no_act.recovered_gmv == Decimal("0.00")
    assert no_act.net_recovery_rate_pct == 0.0
    assert no_act.execution_cost == Decimal("0.00")

    # 2. Blind Retry Baseline
    blind = res.strategies["BLIND_RETRY"]
    assert blind.strategy == BenchmarkStrategy.BLIND_RETRY
    assert blind.recovered_txns > 0
    assert blind.recovered_gmv > 0
    assert blind.execution_cost > 0
    assert blind.friction_penalty > 0
    assert blind.unnecessary_retries > 0  # Retried hard failures blindly

    # 3. Rule-Based Heuristic
    heur = res.strategies["RULE_BASED_HEURISTIC"]
    assert heur.strategy == BenchmarkStrategy.RULE_BASED_HEURISTIC
    assert heur.recovered_txns >= blind.recovered_txns
    assert heur.recovered_gmv >= blind.recovered_gmv
    assert heur.hard_failures_blocked > 0
    assert heur.unnecessary_retries == 0

    # 4. RecoverX AI
    ai = res.strategies["RECOVERX_AI"]
    assert ai.strategy == BenchmarkStrategy.RECOVERX_AI
    assert ai.recovered_txns >= 30
    assert ai.recovered_gmv > Decimal("100000.00")
    assert ai.net_recovery_rate_pct >= 55.0
    assert ai.roi_multiplier > 10.0
    assert ai.hard_failures_blocked > 0
    assert ai.unnecessary_retries == 0

    # Incremental lifts
    assert res.incremental_gmv_vs_no_action == ai.recovered_gmv
    assert res.incremental_gmv_vs_blind_retry > 0
    assert res.recovery_rate_lift_pct_vs_blind > 0
    assert res.net_profit_gain_vs_blind > 0

    # Category breakdown verification
    assert len(res.category_breakdown) > 0
    cat_names = {c.failure_category for c in res.category_breakdown}
    assert "HARD_FAILURE" in cat_names or "PAYMENT_METHOD" in cat_names


def test_benchmark_scenario_filtering(db_session: Session):
    """Verify benchmark runs with specific failure scenario filters."""
    res = evaluation_service.run_benchmark(
        session=db_session,
        merchant_id="merch_test",
        num_transactions=20,
        scenarios=["CARD_DECLINED", "GATEWAY_TIMEOUT"],
        seed=99,
    )
    assert res.total_transactions == 20
    assert res.strategies["RECOVERX_AI"].recovered_txns > 0


def test_business_proof_summary_metrics(db_session: Session):
    """Verify executive business proof summary and ROI calculations."""
    proof = evaluation_service.get_business_proof_summary(
        session=db_session,
        merchant_id="merch_101",
    )

    assert proof.merchant_id == "merch_101"
    assert proof.total_failed_gmv > 0
    assert proof.recovered_gmv > 0
    assert proof.net_recovery_rate_pct > 50.0
    assert proof.incremental_revenue_gain > 0
    assert proof.net_roi_multiplier > 5.0
    assert proof.cost_to_recover_ratio_pct < 10.0
    assert proof.stopping_rules_compliance_pct == 100.0
    assert proof.double_billing_prevention_rate_pct == 100.0
    assert len(proof.key_findings) >= 3


def test_stopping_rules_compliance_verification(db_session: Session):
    """Verify safety stopping rules compliance audit report."""
    audit = evaluation_service.verify_stopping_rules(
        session=db_session,
        merchant_id="merch_101",
    )

    assert audit.overall_compliance_pct == 100.0
    assert audit.zero_violation_guarantee is True
    assert audit.total_rules_audited == 6
    assert audit.passed_rules_count == 6

    rule_codes = {r.rule_code for r in audit.rules}
    expected_codes = {
        "HARD_FAILURE_TERMINAL_STOP",
        "MAX_ATTEMPTS_CEILING",
        "NEGATIVE_EV_ABORT",
        "DOUBLE_BILLING_PREVENTION",
        "EXPIRY_TTL_ENFORCEMENT",
        "CONSECUTIVE_FAILURE_BACKOFF",
    }
    assert expected_codes.issubset(rule_codes)

    for rule in audit.rules:
        assert rule.compliance_status in ("COMPLIANT", "VERIFIED")
        assert rule.violations_count == 0
        assert rule.total_checks > 0
        assert len(rule.sample_audit_reason) > 0


def test_audit_trail_reconstruction_end_to_end(db_session: Session):
    """Verify complete chronological audit timeline reconstruction with checksums."""
    now = datetime.now(timezone.utc)
    cust = Customer(
        external_customer_id="cust_vikram_001",
        name="Vikram Seth",
        email="vikram.seth@example.com",
        phone="+919876543210",
        merchant_id="merch_101",
    )
    db_session.add(cust)
    db_session.flush()

    txn = Transaction(
        external_transaction_id="txn_eval_audit_001",
        merchant_id="merch_101",
        customer_id=cust.id,
        amount=Decimal("4999.00"),
        currency="INR",
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()

    att = PaymentAttempt(
        transaction_id=txn.id,
        attempt_number=1,
        payment_method="CARD",
        gateway="RAZORPAY",
        failure_code="CARD_DECLINED",
    )
    db_session.add(att)
    db_session.flush()

    fail = FailureEvent(
        source_event_id="evt_audit_eval_001",
        transaction_id=txn.id,
        attempt_id=att.id,
        category="PAYMENT_METHOD",
        failure_code="CARD_DECLINED",
        recoverable=True,
        payload={"error_message": "Card declined by issuer"},
    )
    db_session.add(fail)

    case = RecoveryCase(
        transaction_id=txn.id,
        state=RecoveryState.RECOVERED,
        policy_version="v1.2",
    )
    db_session.add(case)
    db_session.flush()

    action = RecoveryAction(
        recovery_case_id=case.id,
        action_type=ActionType.SWITCH_TO_UPI,
        idempotency_key="idemp_eval_test_001",
        selected=True,
        status="COMPLETED",
        execution_channel="DIRECT_API",
    )
    db_session.add(action)
    db_session.commit()

    trail = evaluation_service.get_transaction_audit_trail(db_session, txn.id)

    assert trail.transaction_id == str(txn.id)
    assert trail.external_transaction_id == "txn_eval_audit_001"
    assert trail.amount == Decimal("4999.00")
    assert trail.integrity_verified is True
    assert trail.customer_email_masked is not None
    assert trail.total_events >= 5

    # Check chronological steps
    for i, event in enumerate(trail.events, 1):
        assert event.step_number == i
        assert event.checksum_hash is not None
        assert len(event.checksum_hash) > 0
        assert event.actor in ("SYSTEM", "GATEWAY_INTEGRATION", "FAILURE_CLASSIFIER", "RECOVERY_ORCHESTRATOR", "AGENT_RECOVERX", "EXECUTION_ENGINE")


def test_audit_trail_not_found_raises_error(db_session: Session):
    """Verify querying non-existent transaction ID raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        evaluation_service.get_transaction_audit_trail(db_session, "non_existent_txn_999")
