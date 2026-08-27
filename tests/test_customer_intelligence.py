"""Unit tests for Customer Intelligence calculations, behavioral segmentation, and ML features."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    Customer,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.services.customer_intelligence import (
    compute_customer_intelligence,
    extract_customer_features,
    get_customer_payment_behavior,
    get_customer_recovery_history,
)


def test_customer_intelligence_new_user(db_session: Session) -> None:
    """Test intelligence computation on a brand new customer with 0 transactions."""
    customer = Customer(
        external_customer_id=f"cust_new_{uuid4().hex[:6]}",
        merchant_id="merch_test",
        name="New Buyer",
        risk_segment="NEW",
    )
    db_session.add(customer)
    db_session.commit()

    intel = compute_customer_intelligence(db_session, customer.id, persist=True)

    assert intel.total_transactions == 0
    assert intel.successful_transactions == 0
    assert intel.total_spent == Decimal("0.00")
    assert intel.success_rate == Decimal("0.0000")
    assert intel.behavioral_segment == "NEW_CUSTOMER"
    assert intel.preferred_payment_method == "UPI"
    assert intel.recent_failure_streak == 0


def test_customer_intelligence_vip_persona(db_session: Session) -> None:
    """Test intelligence computation for a high-value VIP customer."""
    customer = Customer(
        external_customer_id=f"cust_vip_{uuid4().hex[:6]}",
        merchant_id="merch_test",
        name="VIP Priya",
        risk_segment="VIP",
        preferred_payment_method="CARD",
    )
    db_session.add(customer)
    db_session.commit()

    # Add 5 successful high-value transactions
    amounts = [Decimal("12000.00"), Decimal("8500.00"), Decimal("15000.00"), Decimal("4500.00"), Decimal("22000.00")]
    for amt in amounts:
        txn = Transaction(
            external_transaction_id=f"txn_{uuid4().hex[:8]}",
            merchant_id="merch_test",
            customer_id=customer.id,
            amount=amt,
            currency="INR",
            status=TransactionStatus.SUCCEEDED,
        )
        db_session.add(txn)
        db_session.flush()

        att = PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            gateway="RAZORPAY",
            failure_code=None,
        )
        db_session.add(att)

    db_session.commit()

    intel = compute_customer_intelligence(db_session, customer.id, persist=True)

    assert intel.total_transactions == 5
    assert intel.successful_transactions == 5
    assert intel.total_spent == Decimal("62000.00")
    assert intel.success_rate == Decimal("1.0000")
    assert intel.behavioral_segment == "VIP_HIGH_VALUE"
    assert intel.preferred_payment_method == "CARD"
    assert intel.recent_failure_streak == 0
    assert intel.average_transaction_value == Decimal("12400.00")


def test_customer_intelligence_decline_prone_and_recovery(db_session: Session) -> None:
    """Test intelligence computation for card-decline prone customer with recoveries."""
    customer = Customer(
        external_customer_id=f"cust_decline_{uuid4().hex[:6]}",
        merchant_id="merch_test",
        name="Vikram Card",
        risk_segment="STANDARD",
        preferred_payment_method="CARD",
    )
    db_session.add(customer)
    db_session.commit()

    # Txn 1: Succeeded with CARD
    t1 = Transaction(
        external_transaction_id=f"txn_{uuid4().hex[:8]}",
        merchant_id="merch_test",
        customer_id=customer.id,
        amount=Decimal("3000.00"),
        status=TransactionStatus.SUCCEEDED,
    )
    db_session.add(t1)
    db_session.flush()
    db_session.add(PaymentAttempt(transaction_id=t1.id, attempt_number=1, payment_method="CARD", failure_code=None))

    # Txn 2: Failed CARD -> Recovered via UPI
    t2 = Transaction(
        external_transaction_id=f"txn_{uuid4().hex[:8]}",
        merchant_id="merch_test",
        customer_id=customer.id,
        amount=Decimal("4999.00"),
        status=TransactionStatus.SUCCEEDED,
    )
    db_session.add(t2)
    db_session.flush()
    db_session.add(PaymentAttempt(transaction_id=t2.id, attempt_number=1, payment_method="CARD", failure_code="CARD_DECLINED"))
    db_session.add(PaymentAttempt(transaction_id=t2.id, attempt_number=2, payment_method="UPI", failure_code=None))

    case = RecoveryCase(transaction_id=t2.id, state=RecoveryState.RECOVERED, policy_version="policy.v1")
    db_session.add(case)

    # Txn 3: Failed CARD
    t3 = Transaction(
        external_transaction_id=f"txn_{uuid4().hex[:8]}",
        merchant_id="merch_test",
        customer_id=customer.id,
        amount=Decimal("5000.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(t3)
    db_session.flush()
    db_session.add(PaymentAttempt(transaction_id=t3.id, attempt_number=1, payment_method="CARD", failure_code="CARD_DECLINED"))

    db_session.commit()

    intel = compute_customer_intelligence(db_session, customer.id, persist=True)

    assert intel.total_transactions == 3
    assert intel.successful_transactions == 2
    assert intel.failed_transactions == 1
    assert intel.recovered_transactions == 1
    assert intel.total_recovered_amount == Decimal("4999.00")
    assert intel.behavioral_segment == "CARD_DECLINE_PRONE_RECOVERABLE"
    assert intel.recent_failure_streak == 1
    assert intel.method_success_rates["CARD"] == 0.3333 or intel.method_success_rates["CARD"] == 0.3333
    assert intel.method_success_rates["UPI"] == 1.0


def test_customer_features_extraction_for_ml(db_session: Session) -> None:
    """Test extracting normalized point-in-time ML feature snapshot vector."""
    customer = Customer(
        external_customer_id=f"cust_feat_{uuid4().hex[:6]}",
        merchant_id="merch_test",
        name="ML Feature Test",
        risk_segment="STANDARD",
    )
    db_session.add(customer)
    db_session.commit()

    snapshot = extract_customer_features(db_session, customer.id)

    assert snapshot.customer_id == customer.id
    assert snapshot.feature_version == "v1"
    assert "customer_total_transactions" in snapshot.features
    assert "customer_success_rate" in snapshot.features
    assert len(snapshot.feature_vector) == 9
    assert isinstance(snapshot.feature_vector[0], float)


def test_customer_payment_behavior_and_recovery_history(db_session: Session) -> None:
    """Test payment behavior breakdown and recovery history helpers."""
    customer = Customer(
        external_customer_id=f"cust_hist_{uuid4().hex[:6]}",
        merchant_id="merch_test",
        name="History Test",
        risk_segment="STANDARD",
    )
    db_session.add(customer)
    db_session.commit()

    txn = Transaction(
        external_transaction_id=f"txn_{uuid4().hex[:8]}",
        merchant_id="merch_test",
        customer_id=customer.id,
        amount=Decimal("1500.00"),
        status=TransactionStatus.SUCCEEDED,
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add(PaymentAttempt(transaction_id=txn.id, attempt_number=1, payment_method="UPI", failure_code=None))
    db_session.commit()

    behavior = get_customer_payment_behavior(db_session, customer.id)
    assert behavior.customer_id == customer.id
    assert len(behavior.methods) >= 1
    assert behavior.methods[0].method == "UPI"
    assert behavior.methods[0].successful_attempts == 1

    recovery = get_customer_recovery_history(db_session, customer.id)
    assert recovery.customer_id == customer.id
    assert recovery.total_recovery_cases == 0
