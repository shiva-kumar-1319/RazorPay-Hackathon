"""Unit tests for Failure Intelligence classification, gateway mapping, semantic parsing, and taxonomy."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.app.models.recovery import (
    Customer,
    FailureEvent,
    PaymentAttempt,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.failure import FailureCategory, FailureClassificationRequest
from backend.app.services.failure_intelligence import (
    CUSTOMER_ACTION_CODES,
    GATEWAY_CODE_MAPPINGS,
    HARD_STOP_CODES,
    PAYMENT_METHOD_CODES,
    TAXONOMY_CATALOG,
    TEMPORARY_CODES,
    failure_intelligence_service,
)
from backend.app.services.recovery_policy import evaluate_failure_policy


def test_four_canonical_categories_defined():
    """Verify all 4 canonical failure categories have registered failure codes."""
    assert len(HARD_STOP_CODES) >= 5
    assert len(CUSTOMER_ACTION_CODES) >= 5
    assert len(PAYMENT_METHOD_CODES) >= 5
    assert len(TEMPORARY_CODES) >= 5

    # Check representative codes
    assert "BLOCKED_CARD" in HARD_STOP_CODES
    assert "FRAUD_REJECTED" in HARD_STOP_CODES
    assert "OTP_TIMEOUT" in CUSTOMER_ACTION_CODES
    assert "INSUFFICIENT_FUNDS" in CUSTOMER_ACTION_CODES
    assert "CARD_DECLINED" in PAYMENT_METHOD_CODES
    assert "MANDATE_FAILED" in PAYMENT_METHOD_CODES
    assert "TIMEOUT" in TEMPORARY_CODES
    assert "BANK_SERVER_DOWN" in TEMPORARY_CODES


def test_exact_code_classification():
    """Test exact codebook lookup for each category."""
    # 1. Hard Failure
    res_hard = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(failure_code="BLOCKED_CARD")
    )
    assert res_hard.category == FailureCategory.HARD_FAILURE
    assert res_hard.recoverable is False
    assert res_hard.confidence == Decimal("1.0000")
    assert res_hard.max_retries_permitted == 0
    assert "STOP_RECOVERY" in res_hard.suggested_action

    # 2. Customer Action
    res_cust = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(failure_code="OTP_TIMEOUT")
    )
    assert res_cust.category == FailureCategory.CUSTOMER_ACTION
    assert res_cust.recoverable is True
    assert res_cust.confidence == Decimal("1.0000")
    assert res_cust.max_retries_permitted == 2
    assert "CUSTOMER_NOTIFICATION" in res_cust.permitted_actions

    # 3. Payment Method
    res_pm = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(failure_code="CARD_DECLINED")
    )
    assert res_pm.category == FailureCategory.PAYMENT_METHOD
    assert res_pm.recoverable is True
    assert res_pm.confidence == Decimal("1.0000")
    assert "SWITCH_TO_UPI" in res_pm.permitted_actions

    # 4. Temporary
    res_temp = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(failure_code="TIMEOUT")
    )
    assert res_temp.category == FailureCategory.TEMPORARY
    assert res_temp.recoverable is True
    assert res_temp.confidence == Decimal("1.0000")
    assert res_temp.retry_delay_seconds > 0
    assert "DELAYED_RETRY" in res_temp.permitted_actions


def test_gateway_error_code_translations():
    """Test translation from Razorpay, Stripe, NPCI, and ISO8583 gateway error codes."""
    # Razorpay -> CARD_DECLINED
    res_rzp = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(
            gateway="RAZORPAY",
            gateway_code="BAD_REQUEST_PAYMENT_DECLINED_BY_BANK",
        )
    )
    assert res_rzp.normalized_code == "CARD_DECLINED"
    assert res_rzp.category == FailureCategory.PAYMENT_METHOD

    # Stripe -> INSUFFICIENT_FUNDS
    res_stripe = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(
            gateway="STRIPE",
            gateway_code="insufficient_funds",
        )
    )
    assert res_stripe.normalized_code == "INSUFFICIENT_FUNDS"
    assert res_stripe.category == FailureCategory.CUSTOMER_ACTION

    # Stripe -> BLOCKED_CARD (lost_card)
    res_stripe_lost = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(
            gateway="STRIPE",
            gateway_code="lost_card",
        )
    )
    assert res_stripe_lost.normalized_code == "BLOCKED_CARD"
    assert res_stripe_lost.category == FailureCategory.HARD_FAILURE

    # NPCI -> INCORRECT_PIN (ZM)
    res_npci_pin = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(
            gateway="NPCI",
            gateway_code="ZM",
        )
    )
    assert res_npci_pin.normalized_code == "INCORRECT_PIN"
    assert res_npci_pin.category == FailureCategory.CUSTOMER_ACTION

    # NPCI -> BANK_SERVER_DOWN (ZH)
    res_npci_bank = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(
            gateway="NPCI",
            gateway_code="ZH",
        )
    )
    assert res_npci_bank.normalized_code == "BANK_SERVER_DOWN"
    assert res_npci_bank.category == FailureCategory.TEMPORARY

    # ISO8583 -> 05 (CARD_DECLINED)
    res_iso = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(
            gateway_code="05",
        )
    )
    assert res_iso.normalized_code == "CARD_DECLINED"
    assert res_iso.category == FailureCategory.PAYMENT_METHOD


def test_semantic_nlp_regex_parser():
    """Test classification from unstructured, natural language bank error messages."""
    # "Your card has expired" -> EXPIRED_CARD (HARD_FAILURE)
    res1 = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(raw_message="Transaction rejected because customer card has expired.")
    )
    assert res1.normalized_code == "EXPIRED_CARD"
    assert res1.category == FailureCategory.HARD_FAILURE
    assert res1.match_source == "SEMANTIC_PARSER"
    assert res1.confidence >= Decimal("0.9000")

    # "insufficient balance in account" -> INSUFFICIENT_FUNDS (CUSTOMER_ACTION)
    res2 = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(raw_message="Payer account has insufficient balance to complete ₹4,999 charge")
    )
    assert res2.normalized_code == "INSUFFICIENT_FUNDS"
    assert res2.category == FailureCategory.CUSTOMER_ACTION
    assert res2.recoverable is True

    # "online e-commerce usage disabled" -> ECOMMERCE_DISABLED (PAYMENT_METHOD)
    res3 = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(raw_message="Card issuer reported online usage off for this debit card")
    )
    assert res3.normalized_code == "ECOMMERCE_DISABLED"
    assert res3.category == FailureCategory.PAYMENT_METHOD

    # "bank server unavailable down" -> BANK_SERVER_DOWN (TEMPORARY)
    res4 = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(raw_message="Core banking system maintenance window: bank server unavailable")
    )
    assert res4.normalized_code == "BANK_SERVER_DOWN"
    assert res4.category == FailureCategory.TEMPORARY


def test_fallback_for_completely_unknown_error():
    """Test safe fallback when error cannot be parsed or matched."""
    res_unknown = failure_intelligence_service.classify_failure(
        FailureClassificationRequest(raw_message="XYZ_ABERRATION_UNKNOWN_9999")
    )
    assert res_unknown.normalized_code == "UNKNOWN_FAILURE"
    assert res_unknown.category == FailureCategory.UNKNOWN
    assert res_unknown.recoverable is False
    assert res_unknown.match_source == "FALLBACK"
    assert res_unknown.suggested_action == "STOP_RECOVERY"


def test_taxonomy_catalog_endpoint_integrity():
    """Verify taxonomy structure and completeness."""
    tax = failure_intelligence_service.get_taxonomy()
    assert tax.codes_count == len(TAXONOMY_CATALOG)
    assert len(tax.categories) == 4
    assert "RAZORPAY" in tax.gateway_mappings
    assert "STRIPE" in tax.gateway_mappings
    assert "NPCI" in tax.gateway_mappings
    assert "ISO8583" in tax.gateway_mappings


def test_recovery_policy_integration():
    """Test that evaluate_failure_policy correctly resolves through Failure Intelligence."""
    pol_hard = evaluate_failure_policy("FRAUD_REJECTED")
    assert pol_hard.category == "HARD_FAILURE"
    assert pol_hard.recoverable is False

    pol_cust = evaluate_failure_policy("3DS_FAILURE")
    assert pol_cust.category == "CUSTOMER_ACTION"
    assert pol_cust.recoverable is True

    pol_pm = evaluate_failure_policy("MANDATE_FAILED")
    assert pol_pm.category == "PAYMENT_METHOD"
    assert pol_pm.recoverable is True

    pol_temp = evaluate_failure_policy("GATEWAY_ERROR")
    assert pol_temp.category == "TEMPORARY"
    assert pol_temp.recoverable is True


def test_failure_analytics_calculation(db_session: Session):
    """Test live calculation of failure analytics across transactional data."""
    # Create test transactions with failures across categories
    txn1 = Transaction(
        external_transaction_id=f"tx_fail_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        amount=Decimal("1500.00"),
        status=TransactionStatus.FAILED,
    )
    txn2 = Transaction(
        external_transaction_id=f"tx_fail_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        amount=Decimal("2500.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add_all([txn1, txn2])
    db_session.flush()

    # Attempt 1 on Txn 1: CARD_DECLINED (PAYMENT_METHOD)
    att1 = PaymentAttempt(
        transaction_id=txn1.id,
        attempt_number=1,
        payment_method="CARD",
        gateway="RAZORPAY",
        failure_code="CARD_DECLINED",
    )
    # Attempt 1 on Txn 2: TIMEOUT (TEMPORARY)
    att2 = PaymentAttempt(
        transaction_id=txn2.id,
        attempt_number=1,
        payment_method="UPI",
        gateway="NPCI",
        failure_code="TIMEOUT",
    )
    db_session.add_all([att1, att2])
    db_session.flush()

    fe1 = FailureEvent(
        source_event_id=f"evt_{uuid4().hex[:8]}",
        transaction_id=txn1.id,
        attempt_id=att1.id,
        failure_code="CARD_DECLINED",
        category=FailureCategory.PAYMENT_METHOD.value,
        recoverable=True,
    )
    fe2 = FailureEvent(
        source_event_id=f"evt_{uuid4().hex[:8]}",
        transaction_id=txn2.id,
        attempt_id=att2.id,
        failure_code="TIMEOUT",
        category=FailureCategory.TEMPORARY.value,
        recoverable=True,
    )
    db_session.add_all([fe1, fe2])
    db_session.commit()

    # Calculate analytics
    analytics = failure_intelligence_service.calculate_analytics(db_session)
    assert analytics["total_failures_recorded"] >= 2
    assert len(analytics["category_breakdown"]) == 4

    pm_metric = next(m for m in analytics["category_breakdown"] if m.category == FailureCategory.PAYMENT_METHOD)
    assert pm_metric.count >= 1

    temp_metric = next(m for m in analytics["category_breakdown"] if m.category == FailureCategory.TEMPORARY)
    assert temp_metric.count >= 1
