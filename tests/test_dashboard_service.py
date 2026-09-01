"""Unit & projection tests for Dashboard Service."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    ActionType,
    Customer,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.simulator import CreateSimulatedPaymentRequest
from backend.app.services.dashboard_service import dashboard_service, mask_email
from backend.app.simulator.engine import PaymentSimulator


def test_mask_email_utility():
    """Verify email PII masking preserving domain structure."""
    assert mask_email("john.doe@example.com") == "j***e@example.com"
    assert mask_email("a@b.com") == "a***@b.com"
    assert mask_email(None) is None
    assert mask_email("invalid-email") == "invalid-email"


def test_dashboard_overview_metrics_calculation(db_session: Session):
    """Test calculation of failed GMV, recovered GMV, recovery rate, and friction scores."""
    merchant_id = f"merch_test_{uuid4().hex[:6]}"
    simulator = PaymentSimulator(db_session)

    # Create 1 failed transaction without recovery
    sim1 = simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id=merchant_id,
            amount=Decimal("5000.00"),
            currency="INR",
            payment_method="CARD",
            target_outcome="FAIL",
            target_failure_code="CARD_DECLINED",
        )
    )

    # Create 1 recovered transaction
    sim2 = simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id=merchant_id,
            amount=Decimal("3000.00"),
            currency="INR",
            payment_method="CARD",
            target_outcome="FAIL",
            target_failure_code="CARD_DECLINED",
        )
    )
    t2_id = sim2.transaction_id
    t2 = db_session.get(Transaction, t2_id)
    t2.status = TransactionStatus.SUCCEEDED

    # Link recovery case marked RECOVERED
    case2 = RecoveryCase(
        transaction_id=t2_id,
        state=RecoveryState.RECOVERED,
        policy_version="v1.0",
    )
    db_session.add(case2)
    db_session.flush()

    act2 = RecoveryAction(
        recovery_case_id=case2.id,
        action_type=ActionType.SWITCH_TO_UPI,
        idempotency_key=f"idemp_test_{uuid4().hex}",
        selected=True,
        probability=Decimal("0.8500"),
        expected_value=Decimal("2550.00"),
        status="COMPLETED",
    )
    db_session.add(act2)
    db_session.commit()

    overview = dashboard_service.get_overview_metrics(
        session=db_session,
        merchant_id=merchant_id,
    )

    assert overview.merchant_id == merchant_id
    assert overview.total_recovered_count >= 1
    assert overview.total_recovered_gmv >= Decimal("3000.00")
    assert overview.recovery_rate_pct > Decimal("0.00")
    assert overview.incremental_recovery_gmv == overview.total_recovered_gmv
    assert len(overview.hourly_trends) > 0
    assert len(overview.category_breakdown) > 0


def test_dashboard_funnel_stages(db_session: Session):
    """Test 4-stage funnel conversion rates and category segmentation."""
    merchant_id = f"merch_funnel_{uuid4().hex[:6]}"
    simulator = PaymentSimulator(db_session)

    # Simulate 3 failures
    for amt, code in [(1000, "TIMEOUT"), (2000, "CARD_DECLINED"), (5000, "FRAUD_REJECTED")]:
        simulator.simulate_payment(
            CreateSimulatedPaymentRequest(
                merchant_id=merchant_id,
                amount=Decimal(str(amt)),
                currency="INR",
                payment_method="CARD",
                target_outcome="FAIL",
                target_failure_code=code,
            )
        )

    funnel = dashboard_service.get_recovery_funnel(
        session=db_session,
        merchant_id=merchant_id,
    )

    assert funnel.merchant_id == merchant_id
    assert len(funnel.stages) == 4
    assert funnel.stages[0].stage == "FAILED_PAYMENTS"
    assert funnel.stages[1].stage == "ELIGIBLE_FOR_RECOVERY"
    assert funnel.stages[2].stage == "ACTION_INITIATED"
    assert funnel.stages[3].stage == "REVENUE_RECOVERED"
    assert "TEMPORARY" in funnel.category_funnels
    assert "PAYMENT_METHOD" in funnel.category_funnels
    assert len(funnel.method_conversion_matrix) > 0


def test_live_failed_payments_and_filters(db_session: Session):
    """Test live failed payments feed query with category and state filters."""
    merchant_id = f"merch_live_{uuid4().hex[:6]}"
    simulator = PaymentSimulator(db_session)

    # Create customer
    cust = Customer(
        external_customer_id=f"cust_{uuid4().hex[:6]}",
        merchant_id=merchant_id,
        name="Rahul Verma",
        email="rahul.verma@example.com",
    )
    db_session.add(cust)
    db_session.commit()

    # Simulate payment failure
    sim = simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id=merchant_id,
            amount=Decimal("4999.00"),
            currency="INR",
            payment_method="CARD",
            target_outcome="FAIL",
            target_failure_code="CARD_DECLINED",
            external_customer_id=cust.external_customer_id,
        )
    )

    # 1. Fetch unfiltered
    feed = dashboard_service.get_live_failed_payments(
        session=db_session,
        merchant_id=merchant_id,
    )
    assert feed.total >= 1
    assert feed.items[0].customer_email_masked == "r***a@example.com"
    assert feed.items[0].failure_category == "PAYMENT_METHOD"

    # 2. Filter by matching category
    feed_filtered = dashboard_service.get_live_failed_payments(
        session=db_session,
        merchant_id=merchant_id,
        category="PAYMENT_METHOD",
    )
    assert feed_filtered.total >= 1

    # 3. Filter by non-matching category
    feed_empty = dashboard_service.get_live_failed_payments(
        session=db_session,
        merchant_id=merchant_id,
        category="HARD_FAILURE",
    )
    assert feed_empty.total == 0


def test_agent_decisions_and_recovery_attempts_feed(db_session: Session):
    """Test agent decision log feed and recovery workflow attempts."""
    merchant_id = f"merch_agent_feed_{uuid4().hex[:6]}"
    simulator = PaymentSimulator(db_session)

    sim = simulator.simulate_payment(
        CreateSimulatedPaymentRequest(
            merchant_id=merchant_id,
            amount=Decimal("1500.00"),
            currency="INR",
            payment_method="UPI",
            target_outcome="FAIL",
            target_failure_code="TIMEOUT",
        )
    )
    txn_id = sim.transaction_id

    case = RecoveryCase(
        transaction_id=txn_id,
        state=RecoveryState.SCHEDULED,
        policy_version="v1.0",
    )
    db_session.add(case)
    db_session.flush()

    act = RecoveryAction(
        recovery_case_id=case.id,
        action_type=ActionType.DELAYED_RETRY,
        idempotency_key=f"idemp_act_{uuid4().hex}",
        selected=True,
        probability=Decimal("0.7800"),
        expected_value=Decimal("1170.00"),
        status="SCHEDULED",
        scheduled_at=datetime.now(timezone.utc),
    )
    db_session.add(act)
    db_session.commit()

    decisions = dashboard_service.get_agent_decisions_feed(
        session=db_session,
        merchant_id=merchant_id,
    )
    assert decisions.total >= 1
    assert decisions.items[0].selected_action == "DELAYED_RETRY"
    assert len(decisions.items[0].tool_calls_executed) > 0

    attempts = dashboard_service.get_recovery_attempts_feed(
        session=db_session,
        merchant_id=merchant_id,
    )
    assert attempts.total >= 1
    assert attempts.items[0].workflow_type == "DELAYED_RETRY"
    assert attempts.items[0].status == "SCHEDULED"


def test_model_health_projection(db_session: Session):
    """Test model health projection output."""
    mh = dashboard_service.get_model_health_projections(
        session=db_session,
        merchant_id="merch_101",
    )
    assert mh.auc_roc > 0.8
    assert mh.accuracy > 0.7
    assert len(mh.feature_importances) > 0
    assert len(mh.score_distribution) > 0
    assert len(mh.calibration_curve) > 0


def test_simulate_live_batch(db_session: Session):
    """Test running end-to-end batch simulation."""
    merchant_id = f"merch_sim_batch_{uuid4().hex[:6]}"
    batch_res = dashboard_service.simulate_live_batch(
        session=db_session,
        merchant_id=merchant_id,
        count=3,
        auto_investigate=True,
        auto_execute=True,
    )
    assert batch_res.generated_count == 3
    assert batch_res.investigated_count == 3
    assert len(batch_res.summary_messages) >= 3
