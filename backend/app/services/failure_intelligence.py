"""Failure Intelligence classification engine, taxonomy resolver, semantic parser, and recovery strategist."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.recovery import ActionType, FailureEvent, PaymentAttempt, RecoveryCase, RecoveryState, Transaction
from backend.app.schemas.failure import (
    CategoryMetric,
    FailureAnomalyAlert,
    FailureCategory,
    FailureClassificationRequest,
    FailureIntelligenceDetail,
    FailureTaxonomyItem,
    FailureTaxonomyResponse,
)

logger = logging.getLogger("recoverx.failure_intelligence")


# ============================================================================
# 1. CORE CANONICAL TAXONOMY CATALOG
# ============================================================================

TAXONOMY_CATALOG: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------------------
    # HARD FAILURES (Unrecoverable terminal failures - strictly stop recovery)
    # ------------------------------------------------------------------------
    "BLOCKED_CARD": {
        "category": FailureCategory.HARD_FAILURE,
        "recoverable": False,
        "description": "Card has been reported lost, stolen, frozen, or permanently blocked by issuing bank.",
        "typical_gateways": ["RAZORPAY", "STRIPE", "PAYU", "VISA_MASTERCARD"],
        "suggested_action": ActionType.STOP_RECOVERY.value,
        "permitted_actions": [ActionType.STOP_RECOVERY.value],
        "max_retries": 0,
        "default_delay_seconds": 0,
        "customer_explanation": "Your card has been blocked by your bank. Please use an alternative card or payment method.",
        "merchant_explanation": "Issuing bank reported card as lost, stolen, or frozen. Immediate terminal stop mandated to prevent chargebacks.",
        "alternative_methods": ["UPI", "NETBANKING"],
        "compliance_notes": ["Card network rule: Do not re-attempt transactions on hotlisted or stolen cards.", "Zero retry tolerance."],
    },
    "INVALID_ACCOUNT": {
        "category": FailureCategory.HARD_FAILURE,
        "recoverable": False,
        "description": "Bank account number or VPA handle does not exist or has been permanently closed.",
        "typical_gateways": ["NPCI", "RAZORPAY", "CASHFREE", "BILLDESK"],
        "suggested_action": ActionType.STOP_RECOVERY.value,
        "permitted_actions": [ActionType.STOP_RECOVERY.value],
        "max_retries": 0,
        "default_delay_seconds": 0,
        "customer_explanation": "The destination or payment account could not be found. Please verify your details or use another payment method.",
        "merchant_explanation": "Account identifier rejected by core banking switch or NPCI as non-existent.",
        "alternative_methods": ["UPI", "CARD"],
        "compliance_notes": ["Account verification failed. Ensure valid beneficiary details."],
    },
    "FRAUD_REJECTED": {
        "category": FailureCategory.HARD_FAILURE,
        "recoverable": False,
        "description": "Transaction flagged and rejected by fraud detection system, risk scoring engine, or AML filter.",
        "typical_gateways": ["STRIPE", "RAZORPAY", "VISA_RISK", "CYBERSOURCE"],
        "suggested_action": ActionType.STOP_RECOVERY.value,
        "permitted_actions": [ActionType.STOP_RECOVERY.value],
        "max_retries": 0,
        "default_delay_seconds": 0,
        "customer_explanation": "This payment could not be processed due to security and risk verification policies.",
        "merchant_explanation": "Risk engine flagged high-probability anomaly or blacklisted entity. Recovery attempts suppressed.",
        "alternative_methods": [],
        "compliance_notes": ["PCI-DSS and AML compliance stop: suppress automated recovery triggers."],
    },
    "EXPIRED_CARD": {
        "category": FailureCategory.HARD_FAILURE,
        "recoverable": False,
        "description": "Card validity date is in the past.",
        "typical_gateways": ["STRIPE", "RAZORPAY", "PAYU", "HDFC_SMARTHUB"],
        "suggested_action": ActionType.STOP_RECOVERY.value,
        "permitted_actions": [ActionType.STOP_RECOVERY.value],
        "max_retries": 0,
        "default_delay_seconds": 0,
        "customer_explanation": "Your card has expired. Please enter details of a valid card or pay via UPI.",
        "merchant_explanation": "Card expiry date passed. Retry on same instrument is impossible.",
        "alternative_methods": ["UPI", "CARD", "NETBANKING"],
        "compliance_notes": ["RBI tokenization guidelines require valid active card metadata."],
    },
    "LIMIT_EXCEEDED_HARD": {
        "category": FailureCategory.HARD_FAILURE,
        "recoverable": False,
        "description": "Permanent credit line exhausted or monthly maximum transaction limit reached.",
        "typical_gateways": ["RAZORPAY", "STRIPE", "PAYU"],
        "suggested_action": ActionType.STOP_RECOVERY.value,
        "permitted_actions": [ActionType.STOP_RECOVERY.value],
        "max_retries": 0,
        "default_delay_seconds": 0,
        "customer_explanation": "The maximum permissible spending limit for this account has been reached.",
        "merchant_explanation": "Permanent card credit ceiling or bank account lifecycle cap reached.",
        "alternative_methods": ["NETBANKING", "UPI"],
        "compliance_notes": ["Hard ceiling decline. Re-attempts will be consistently rejected."],
    },
    "ACCOUNT_CLOSED": {
        "category": FailureCategory.HARD_FAILURE,
        "recoverable": False,
        "description": "The payer bank account is closed or dormant.",
        "typical_gateways": ["NPCI", "RAZORPAY", "BILLDESK"],
        "suggested_action": ActionType.STOP_RECOVERY.value,
        "permitted_actions": [ActionType.STOP_RECOVERY.value],
        "max_retries": 0,
        "default_delay_seconds": 0,
        "customer_explanation": "The specified bank account is inactive or closed. Please select a different bank account.",
        "merchant_explanation": "Bank returned account inactive/closed state code.",
        "alternative_methods": ["UPI", "CARD"],
        "compliance_notes": ["Terminal account status."],
    },
    "BLACKLISTED_VPA": {
        "category": FailureCategory.HARD_FAILURE,
        "recoverable": False,
        "description": "UPI VPA handle has been blacklisted by NPCI or bank for spam/abuse.",
        "typical_gateways": ["NPCI", "BHIM"],
        "suggested_action": ActionType.STOP_RECOVERY.value,
        "permitted_actions": [ActionType.STOP_RECOVERY.value],
        "max_retries": 0,
        "default_delay_seconds": 0,
        "customer_explanation": "This UPI handle cannot be used. Please provide a different UPI ID or card.",
        "merchant_explanation": "UPI VPA blacklisted at NPCI central switch.",
        "alternative_methods": ["CARD", "NETBANKING"],
        "compliance_notes": ["NPCI security flag."],
    },

    # ------------------------------------------------------------------------
    # CUSTOMER_ACTION (Recoverable through customer interaction / intervention)
    # ------------------------------------------------------------------------
    "OTP_TIMEOUT": {
        "category": FailureCategory.CUSTOMER_ACTION,
        "recoverable": True,
        "description": "SMS or in-app One Time Password expired before submission.",
        "typical_gateways": ["RAZORPAY", "PAYU", "CASHFREE", "HDFC_SMARTHUB"],
        "suggested_action": ActionType.CUSTOMER_NOTIFICATION.value,
        "permitted_actions": [ActionType.CUSTOMER_NOTIFICATION.value, ActionType.PAYMENT_LINK.value],
        "max_retries": 2,
        "default_delay_seconds": 15,
        "customer_explanation": "The OTP entered has expired or was not submitted in time. We've sent a quick retry link.",
        "merchant_explanation": "Customer missed the OTP verification window. High recovery potential with instant push/SMS prompt.",
        "alternative_methods": ["UPI", "CARD"],
        "compliance_notes": ["RBI 2-Factor Authentication (2FA) verification window timeout."],
    },
    "3DS_FAILURE": {
        "category": FailureCategory.CUSTOMER_ACTION,
        "recoverable": True,
        "description": "3D Secure authentication dropped, biometric failed, or challenge canceled by customer.",
        "typical_gateways": ["STRIPE", "RAZORPAY", "VISA_3DS", "MASTERCARD_ID_CHECK"],
        "suggested_action": ActionType.CUSTOMER_NOTIFICATION.value,
        "permitted_actions": [ActionType.CUSTOMER_NOTIFICATION.value, ActionType.PAYMENT_LINK.value],
        "max_retries": 2,
        "default_delay_seconds": 20,
        "customer_explanation": "Your card authentication step was interrupted. Please complete verification on your bank app or try again.",
        "merchant_explanation": "ACS server challenge not completed. Triggering smart notification or hosted recovery link.",
        "alternative_methods": ["UPI", "NETBANKING"],
        "compliance_notes": ["EMV 3DS 2.x authentication drop-off."],
    },
    "INSUFFICIENT_FUNDS": {
        "category": FailureCategory.CUSTOMER_ACTION,
        "recoverable": True,
        "description": "Payer account or credit limit currently lacks adequate balance.",
        "typical_gateways": ["NPCI", "RAZORPAY", "STRIPE", "PAYU"],
        "suggested_action": ActionType.CUSTOMER_NOTIFICATION.value,
        "permitted_actions": [ActionType.CUSTOMER_NOTIFICATION.value, ActionType.PAYMENT_LINK.value],
        "max_retries": 2,
        "default_delay_seconds": 60,
        "customer_explanation": "There was insufficient balance in the selected account. Please use another account or card.",
        "merchant_explanation": "Payer account balance check failed. Prompting user with flexible multi-option payment link.",
        "alternative_methods": ["UPI", "CARD", "NETBANKING", "BNPL"],
        "compliance_notes": ["Ensure respectful customer notification without broadcasting balance details."],
    },
    "INCORRECT_PIN": {
        "category": FailureCategory.CUSTOMER_ACTION,
        "recoverable": True,
        "description": "Incorrect UPI MPIN or ATM PIN entered by customer.",
        "typical_gateways": ["NPCI", "BHIM", "PHONEPE", "GPAY"],
        "suggested_action": ActionType.CUSTOMER_NOTIFICATION.value,
        "permitted_actions": [ActionType.CUSTOMER_NOTIFICATION.value, ActionType.PAYMENT_LINK.value],
        "max_retries": 2,
        "default_delay_seconds": 30,
        "customer_explanation": "The UPI PIN or MPIN entered was incorrect. Please try again with the correct PIN.",
        "merchant_explanation": "NPCI rejected due to MPIN mismatch. Customer must re-authenticate.",
        "alternative_methods": ["CARD", "NETBANKING"],
        "compliance_notes": ["NPCI PIN retry policy: multiple incorrect attempts lock handle for 24h."],
    },
    "USER_CANCELLED": {
        "category": FailureCategory.CUSTOMER_ACTION,
        "recoverable": True,
        "description": "Customer explicitly backed out or dismissed payment checkout sheet.",
        "typical_gateways": ["RAZORPAY", "STRIPE", "PAYU", "CASHFREE"],
        "suggested_action": ActionType.PAYMENT_LINK.value,
        "permitted_actions": [ActionType.PAYMENT_LINK.value, ActionType.CUSTOMER_NOTIFICATION.value],
        "max_retries": 2,
        "default_delay_seconds": 300,
        "customer_explanation": "You cancelled your recent transaction. You can complete your order anytime using this secure link.",
        "merchant_explanation": "User initiated checkout cancellation. Send gentle recovery link with order summary.",
        "alternative_methods": ["UPI", "CARD", "WALLET"],
        "compliance_notes": ["Cart abandonment recovery communication rules apply."],
    },
    "INVALID_CVV": {
        "category": FailureCategory.CUSTOMER_ACTION,
        "recoverable": True,
        "description": "Card Verification Value (CVV/CVC) did not match issuer records.",
        "typical_gateways": ["STRIPE", "RAZORPAY", "PAYU"],
        "suggested_action": ActionType.CUSTOMER_NOTIFICATION.value,
        "permitted_actions": [ActionType.CUSTOMER_NOTIFICATION.value, ActionType.PAYMENT_LINK.value],
        "max_retries": 2,
        "default_delay_seconds": 10,
        "customer_explanation": "The CVV code entered was incorrect. Please re-enter your card details.",
        "merchant_explanation": "CVV validation mismatch at gateway level.",
        "alternative_methods": ["UPI", "CARD"],
        "compliance_notes": ["Do not store or log raw CVV values (PCI-DSS requirement)."],
    },

    # ------------------------------------------------------------------------
    # PAYMENT_METHOD (Recoverable by switching payment instrument / channel)
    # ------------------------------------------------------------------------
    "CARD_DECLINED": {
        "category": FailureCategory.PAYMENT_METHOD,
        "recoverable": True,
        "description": "Card issuing bank generic decline (e-commerce not enabled, issuer policy, or card tier limit).",
        "typical_gateways": ["RAZORPAY", "STRIPE", "PAYU", "HDFC_SMARTHUB"],
        "suggested_action": ActionType.SWITCH_TO_UPI.value,
        "permitted_actions": [ActionType.SWITCH_TO_UPI.value, ActionType.PAYMENT_LINK.value, ActionType.SWITCH_TO_NETBANKING.value],
        "max_retries": 1,
        "default_delay_seconds": 0,
        "customer_explanation": "Your card issuer declined the transaction. Switching to UPI or NetBanking will complete your purchase instantly.",
        "merchant_explanation": "Bank issuer decline (ISO 05 Do Not Honor). Avoid re-hammering same card; switch to high-success UPI channel.",
        "alternative_methods": ["UPI", "NETBANKING", "WALLET"],
        "compliance_notes": ["RBI guidelines on card domestic/international e-commerce flags."],
    },
    "CARD_TYPE_NOT_SUPPORTED": {
        "category": FailureCategory.PAYMENT_METHOD,
        "recoverable": True,
        "description": "Commercial, prepaid, or corporate card tier not permitted by merchant account or acquirer.",
        "typical_gateways": ["RAZORPAY", "STRIPE", "PAYU"],
        "suggested_action": ActionType.SWITCH_TO_UPI.value,
        "permitted_actions": [ActionType.SWITCH_TO_UPI.value, ActionType.PAYMENT_LINK.value, ActionType.SWITCH_TO_NETBANKING.value],
        "max_retries": 1,
        "default_delay_seconds": 0,
        "customer_explanation": "This specific card type is not accepted for this merchant. Please try with UPI or another card.",
        "merchant_explanation": "Card BIN tier rejected by acquiring rules (e.g. prepaid or non-3DS commercial).",
        "alternative_methods": ["UPI", "NETBANKING"],
        "compliance_notes": ["Routing policy: enforce supported instrument filter."],
    },
    "MANDATE_FAILED": {
        "category": FailureCategory.PAYMENT_METHOD,
        "recoverable": True,
        "description": "Recurring subscription e-mandate debit rejected or mandate authorization expired.",
        "typical_gateways": ["RAZORPAY", "STRIPE", "BILLDESK"],
        "suggested_action": ActionType.PAYMENT_LINK.value,
        "permitted_actions": [ActionType.PAYMENT_LINK.value, ActionType.SWITCH_TO_UPI.value],
        "max_retries": 2,
        "default_delay_seconds": 86400,
        "customer_explanation": "Your auto-debit subscription payment could not be processed. Please settle with a one-time link or update your mandate.",
        "merchant_explanation": "Recurring mandate execution failed. Dispatching one-click invoice / payment link.",
        "alternative_methods": ["UPI", "CARD"],
        "compliance_notes": ["RBI e-Mandate circular: Pre-debit notification required 24h prior to retry."],
    },
    "INTERNATIONAL_NOT_ALLOWED": {
        "category": FailureCategory.PAYMENT_METHOD,
        "recoverable": True,
        "description": "International transactions or cross-border currency conversion disabled on payer card.",
        "typical_gateways": ["STRIPE", "RAZORPAY"],
        "suggested_action": ActionType.SWITCH_TO_UPI.value,
        "permitted_actions": [ActionType.SWITCH_TO_UPI.value, ActionType.PAYMENT_LINK.value],
        "max_retries": 1,
        "default_delay_seconds": 0,
        "customer_explanation": "International/cross-border transactions are not enabled on your card. Please use a domestic card or UPI.",
        "merchant_explanation": "Payer card lacks international e-commerce activation.",
        "alternative_methods": ["UPI", "DOMESTIC_CARD"],
        "compliance_notes": ["FEMA & cross-border merchant category constraints."],
    },
    "ECOMMERCE_DISABLED": {
        "category": FailureCategory.PAYMENT_METHOD,
        "recoverable": True,
        "description": "Online e-commerce transactions are toggled off in payer's mobile banking app.",
        "typical_gateways": ["RAZORPAY", "PAYU", "HDFC_SMARTHUB"],
        "suggested_action": ActionType.SWITCH_TO_UPI.value,
        "permitted_actions": [ActionType.SWITCH_TO_UPI.value, ActionType.PAYMENT_LINK.value],
        "max_retries": 1,
        "default_delay_seconds": 0,
        "customer_explanation": "Online transactions are disabled for your card. Enable it in your bank app or pay instantly via UPI.",
        "merchant_explanation": "RBI e-commerce card control toggle is off. UPI switch provides frictionless conversion.",
        "alternative_methods": ["UPI", "NETBANKING"],
        "compliance_notes": ["RBI Card Controls Mandate 2020."],
    },
    "TOKENIZATION_ERROR": {
        "category": FailureCategory.PAYMENT_METHOD,
        "recoverable": True,
        "description": "Card token (CoF) expired, deleted, or cryptogram validation failed.",
        "typical_gateways": ["RAZORPAY", "STRIPE", "PAYU"],
        "suggested_action": ActionType.PAYMENT_LINK.value,
        "permitted_actions": [ActionType.PAYMENT_LINK.value, ActionType.SWITCH_TO_UPI.value],
        "max_retries": 1,
        "default_delay_seconds": 0,
        "customer_explanation": "Saved card security token expired. Please enter your card details again or use UPI.",
        "merchant_explanation": "Card-on-File token invalid. Customer must re-tokenize or use alternative method.",
        "alternative_methods": ["UPI", "CARD"],
        "compliance_notes": ["RBI Card-on-File Tokenization (CoFT) protocol."],
    },

    # ------------------------------------------------------------------------
    # TEMPORARY (Transient infrastructure blips - recoverable via smart retry)
    # ------------------------------------------------------------------------
    "TIMEOUT": {
        "category": FailureCategory.TEMPORARY,
        "recoverable": True,
        "description": "Acquiring gateway or upstream banking switch timed out waiting for response.",
        "typical_gateways": ["RAZORPAY", "STRIPE", "PAYU", "NPCI", "CASHFREE"],
        "suggested_action": ActionType.DELAYED_RETRY.value,
        "permitted_actions": [ActionType.DELAYED_RETRY.value, ActionType.RETRY_SAME_METHOD.value],
        "max_retries": 3,
        "default_delay_seconds": 60,
        "customer_explanation": "The payment took longer than expected to connect to your bank. We are verifying and retrying.",
        "merchant_explanation": "Upstream gateway/bank HTTP socket timeout. Safe for automated backoff retry.",
        "alternative_methods": ["UPI", "NETBANKING"],
        "compliance_notes": ["Check transaction status inquiry before firing live retry to prevent double debits."],
    },
    "NETWORK_ERROR": {
        "category": FailureCategory.TEMPORARY,
        "recoverable": True,
        "description": "Transient TCP/TLS network error or connection reset during transaction processing.",
        "typical_gateways": ["RAZORPAY", "STRIPE", "PAYU", "NPCI"],
        "suggested_action": ActionType.DELAYED_RETRY.value,
        "permitted_actions": [ActionType.DELAYED_RETRY.value, ActionType.RETRY_SAME_METHOD.value],
        "max_retries": 3,
        "default_delay_seconds": 45,
        "customer_explanation": "A temporary network issue occurred. Your payment is being retried securely.",
        "merchant_explanation": "Transient packet drop or network reset between merchant and PSP switch.",
        "alternative_methods": ["UPI", "CARD"],
        "compliance_notes": ["Exponential backoff with jitter recommended."],
    },
    "UPI_FAILURE": {
        "category": FailureCategory.TEMPORARY,
        "recoverable": True,
        "description": "NPCI switch degradation or PSP UPI application latency.",
        "typical_gateways": ["NPCI", "PHONEPE", "GPAY", "PAYTM"],
        "suggested_action": ActionType.DELAYED_RETRY.value,
        "permitted_actions": [ActionType.DELAYED_RETRY.value, ActionType.RETRY_SAME_METHOD.value],
        "max_retries": 3,
        "default_delay_seconds": 60,
        "customer_explanation": "UPI network is experiencing high traffic. Retrying in a few moments.",
        "merchant_explanation": "NPCI UPI switch response timeout / temporary degradation.",
        "alternative_methods": ["NETBANKING", "CARD"],
        "compliance_notes": ["Monitor NPCI central heartbeat status."],
    },
    "GATEWAY_ERROR": {
        "category": FailureCategory.TEMPORARY,
        "recoverable": True,
        "description": "Aggregator 500/502/503 internal server or routing error.",
        "typical_gateways": ["RAZORPAY", "STRIPE", "PAYU", "CASHFREE"],
        "suggested_action": ActionType.DELAYED_RETRY.value,
        "permitted_actions": [ActionType.DELAYED_RETRY.value, ActionType.RETRY_SAME_METHOD.value],
        "max_retries": 3,
        "default_delay_seconds": 90,
        "customer_explanation": "Payment service temporarily unavailable. We are retrying automatically.",
        "merchant_explanation": "Aggregator returned HTTP 5xx error code.",
        "alternative_methods": ["UPI", "PAYMENT_LINK"],
        "compliance_notes": ["Circuit breaker pattern enabled for gateway failure spikes."],
    },
    "BANK_SERVER_DOWN": {
        "category": FailureCategory.TEMPORARY,
        "recoverable": True,
        "description": "Core banking system (CBS) undergoing scheduled maintenance or experiencing downtime.",
        "typical_gateways": ["HDFC_SMARTHUB", "SBI_GATEWAY", "ICICI_PG", "NPCI"],
        "suggested_action": ActionType.DELAYED_RETRY.value,
        "permitted_actions": [ActionType.DELAYED_RETRY.value, ActionType.SWITCH_TO_UPI.value],
        "max_retries": 3,
        "default_delay_seconds": 120,
        "customer_explanation": "Your bank's server is temporarily down for maintenance. We will retry once service resumes.",
        "merchant_explanation": "Issuer CBS (Core Banking Solution) returned 91/System Error. Schedule delayed retry.",
        "alternative_methods": ["UPI", "PAYMENT_LINK"],
        "compliance_notes": ["Bank maintenance window backoff required."],
    },
    "RATE_LIMITED": {
        "category": FailureCategory.TEMPORARY,
        "recoverable": True,
        "description": "Payment gateway HTTP 429 Too Many Requests rate limit hit.",
        "typical_gateways": ["STRIPE", "RAZORPAY"],
        "suggested_action": ActionType.DELAYED_RETRY.value,
        "permitted_actions": [ActionType.DELAYED_RETRY.value],
        "max_retries": 3,
        "default_delay_seconds": 60,
        "customer_explanation": "Payment requests are processing. Please wait a moment while your payment completes.",
        "merchant_explanation": "Upstream rate limit throttling. Apply cool-off period.",
        "alternative_methods": [],
        "compliance_notes": ["Honor Retry-After response header."],
    },
}

HARD_STOP_CODES: set[str] = {k for k, v in TAXONOMY_CATALOG.items() if v["category"] == FailureCategory.HARD_FAILURE}
CUSTOMER_ACTION_CODES: set[str] = {k for k, v in TAXONOMY_CATALOG.items() if v["category"] == FailureCategory.CUSTOMER_ACTION}
PAYMENT_METHOD_CODES: set[str] = {k for k, v in TAXONOMY_CATALOG.items() if v["category"] == FailureCategory.PAYMENT_METHOD}
TEMPORARY_CODES: set[str] = {k for k, v in TAXONOMY_CATALOG.items() if v["category"] == FailureCategory.TEMPORARY}


# ============================================================================
# 2. GATEWAY & STANDARD ERROR CODE MAPPER DICTIONARIES
# ============================================================================

GATEWAY_CODE_MAPPINGS: dict[str, dict[str, str]] = {
    "RAZORPAY": {
        "BAD_REQUEST_PAYMENT_DECLINED_BY_BANK": "CARD_DECLINED",
        "BAD_REQUEST_PAYMENT_CARD_EXPIRED": "EXPIRED_CARD",
        "BAD_REQUEST_PAYMENT_CARD_INVALID": "INVALID_ACCOUNT",
        "BAD_REQUEST_PAYMENT_OTP_VALIDATION_FAILED": "OTP_TIMEOUT",
        "BAD_REQUEST_PAYMENT_AUTHENTICATION_FAILED": "3DS_FAILURE",
        "BAD_REQUEST_PAYMENT_INSUFFICIENT_FUNDS": "INSUFFICIENT_FUNDS",
        "BAD_REQUEST_PAYMENT_ACCOUNT_LIMIT_EXCEEDED": "LIMIT_EXCEEDED_HARD",
        "BAD_REQUEST_PAYMENT_FRAUD_DETECTED": "FRAUD_REJECTED",
        "BAD_REQUEST_PAYMENT_TIMED_OUT": "TIMEOUT",
        "BAD_REQUEST_PAYMENT_UPI_COLLECT_EXPIRED": "OTP_TIMEOUT",
        "BAD_REQUEST_PAYMENT_UPI_PIN_INVALID": "INCORRECT_PIN",
        "BAD_REQUEST_PAYMENT_CARD_NOT_SUPPORTED": "CARD_TYPE_NOT_SUPPORTED",
        "BAD_REQUEST_PAYMENT_MANDATE_FAILED": "MANDATE_FAILED",
        "BAD_REQUEST_PAYMENT_INTERNATIONAL_NOT_ALLOWED": "INTERNATIONAL_NOT_ALLOWED",
        "BAD_REQUEST_PAYMENT_ECOMMERCE_NOT_ALLOWED": "ECOMMERCE_DISABLED",
        "PAYMENT_CANCELLED_BY_USER": "USER_CANCELLED",
        "GATEWAY_ERROR": "GATEWAY_ERROR",
        "GATEWAY_TIMEOUT": "TIMEOUT",
        "SERVER_ERROR": "GATEWAY_ERROR",
    },
    "STRIPE": {
        "card_declined": "CARD_DECLINED",
        "generic_decline": "CARD_DECLINED",
        "do_not_honor": "CARD_DECLINED",
        "insufficient_funds": "INSUFFICIENT_FUNDS",
        "lost_card": "BLOCKED_CARD",
        "stolen_card": "BLOCKED_CARD",
        "pickup_card": "BLOCKED_CARD",
        "expired_card": "EXPIRED_CARD",
        "incorrect_cvc": "INVALID_CVV",
        "incorrect_pin": "INCORRECT_PIN",
        "incorrect_number": "INVALID_ACCOUNT",
        "invalid_account": "INVALID_ACCOUNT",
        "currency_not_supported": "CARD_TYPE_NOT_SUPPORTED",
        "fraudulent": "FRAUD_REJECTED",
        "processing_error": "GATEWAY_ERROR",
        "rate_limit": "RATE_LIMITED",
        "call_issuer": "CARD_DECLINED",
        "card_velocity_exceeded": "LIMIT_EXCEEDED_HARD",
        "transaction_not_allowed": "CARD_TYPE_NOT_SUPPORTED",
        "try_again_later": "TIMEOUT",
    },
    "NPCI": {
        "U30": "TIMEOUT",
        "U69": "INSUFFICIENT_FUNDS",
        "ZM": "INCORRECT_PIN",
        "ZA": "USER_CANCELLED",
        "ZH": "BANK_SERVER_DOWN",
        "XB": "BANK_SERVER_DOWN",
        "XC": "TIMEOUT",
        "XI": "GATEWAY_ERROR",
        "UT": "TIMEOUT",
        "U28": "INVALID_ACCOUNT",
        "U29": "INVALID_ACCOUNT",
        "U16": "FRAUD_REJECTED",
        "U54": "LIMIT_EXCEEDED_HARD",
        "XY": "BLOCKED_CARD",
    },
    "ISO8583": {
        "05": "CARD_DECLINED",          # Do Not Honor
        "14": "INVALID_ACCOUNT",        # Invalid Card / Account
        "41": "BLOCKED_CARD",           # Lost Card - Pick Up
        "43": "BLOCKED_CARD",           # Stolen Card - Pick Up
        "51": "INSUFFICIENT_FUNDS",     # Insufficient Funds
        "54": "EXPIRED_CARD",           # Expired Card
        "57": "CARD_TYPE_NOT_SUPPORTED",# Transaction Not Permitted to Cardholder
        "61": "LIMIT_EXCEEDED_HARD",    # Exceeds Withdrawal Amount Limit
        "65": "LIMIT_EXCEEDED_HARD",    # Exceeds Withdrawal Frequency Limit
        "82": "INVALID_CVV",            # Incorrect CVV
        "75": "INCORRECT_PIN",          # Allowable Number of PIN Tries Exceeded
        "91": "BANK_SERVER_DOWN",       # Issuer Switch Inoperative
        "96": "GATEWAY_ERROR",          # System Malfunction
    },
}


# ============================================================================
# 3. NLP & SEMANTIC REGEX FAILURE PARSER
# ============================================================================

SEMANTIC_REGEX_PATTERNS: list[tuple[re.Pattern, str, Decimal]] = [
    # HARD FAILURE PATTERNS
    (re.compile(r"\b(lost\s*card|stolen\s*card|blocked\s*card|card\s*is\s*frozen|hotlisted)\b", re.I), "BLOCKED_CARD", Decimal("0.9600")),
    (re.compile(r"\b(fraud|risk\s*engine|aml|blacklisted|security\s*anomaly)\b", re.I), "FRAUD_REJECTED", Decimal("0.9500")),
    (re.compile(r"\b(expired\s*card|card\s*validity\s*expired|card\s*has\s*expired)\b", re.I), "EXPIRED_CARD", Decimal("0.9800")),
    (re.compile(r"\b(account\s*closed|dormant\s*account|invalid\s*account|vpa\s*not\s*found)\b", re.I), "INVALID_ACCOUNT", Decimal("0.9200")),
    (re.compile(r"\b(credit\s*limit\s*breached|maximum\s*limit\s*exceeded|hard\s*limit)\b", re.I), "LIMIT_EXCEEDED_HARD", Decimal("0.9000")),

    # CUSTOMER ACTION PATTERNS
    (re.compile(r"\b(otp\s*timed?\s*out|otp\s*expired|otp\s*not\s*entered|sms\s*timeout)\b", re.I), "OTP_TIMEOUT", Decimal("0.9500")),
    (re.compile(r"\b(3-?d\s*secure|3ds|acs|biometric|authentication\s*failed|challenge\s*failed)\b", re.I), "3DS_FAILURE", Decimal("0.9200")),
    (re.compile(r"\b(insufficient\s*(funds|balance)|not\s*enough\s*balance|low\s*balance)\b", re.I), "INSUFFICIENT_FUNDS", Decimal("0.9800")),
    (re.compile(r"\b(incorrect\s*(pin|mpin)|wrong\s*(pin|mpin)|invalid\s*upi\s*pin|pin\s*mismatch)\b", re.I), "INCORRECT_PIN", Decimal("0.9600")),
    (re.compile(r"\b(user\s*cancell?ed|dismissed|backed\s*out|checkout\s*aborted)\b", re.I), "USER_CANCELLED", Decimal("0.9500")),
    (re.compile(r"\b(invalid\s*cvv|cvc\s*mismatch|wrong\s*security\s*code)\b", re.I), "INVALID_CVV", Decimal("0.9500")),

    # PAYMENT METHOD PATTERNS
    (re.compile(r"\b(card\s*declined|issuer\s*declined|do\s*not\s*honor|transaction\s*declined\s*by\s*bank)\b", re.I), "CARD_DECLINED", Decimal("0.9200")),
    (re.compile(r"\b(card\s*type\s*not\s*supported|prepaid\s*card\s*not\s*allowed|commercial\s*card)\b", re.I), "CARD_TYPE_NOT_SUPPORTED", Decimal("0.9200")),
    (re.compile(r"\b(mandate\s*failed|subscription\s*auto\s*debit\s*rejected|recurring\s*declined)\b", re.I), "MANDATE_FAILED", Decimal("0.9400")),
    (re.compile(r"\b(international\s*(transaction|payment)\s*disabled|cross\s*border\s*not\s*permitted)\b", re.I), "INTERNATIONAL_NOT_ALLOWED", Decimal("0.9400")),
    (re.compile(r"\b(e[\s-]?commerce\s*(disabled|not\s*allowed|inactive)|online\s*(usage|transactions?|payments?|e[\s-]?commerce)?\s*(off|disabled|inactive))\b", re.I), "ECOMMERCE_DISABLED", Decimal("0.9500")),
    (re.compile(r"\b(tokenization\s*error|token\s*cryptogram|cof\s*failed)\b", re.I), "TOKENIZATION_ERROR", Decimal("0.9000")),

    # TEMPORARY PATTERNS
    (re.compile(r"\b(timeout|timed?\s*out|gateway\s*timeout|socket\s*timeout|deadline\s*exceeded)\b", re.I), "TIMEOUT", Decimal("0.9400")),
    (re.compile(r"\b(network\s*error|connection\s*reset|connection\s*refused|connection\s*dropped)\b", re.I), "NETWORK_ERROR", Decimal("0.9500")),
    (re.compile(r"\b(upi\s*(failure|error|degraded|switch\s*issue)|npci\s*down)\b", re.I), "UPI_FAILURE", Decimal("0.9400")),
    (re.compile(r"\b(gateway\s*error|500\s*internal|502\s*bad\s*gateway|503\s*service\s*unavailable|504\s*gateway)\b", re.I), "GATEWAY_ERROR", Decimal("0.9500")),
    (re.compile(r"\b(bank\s*server\s*(down|unavailable|inoperative)|cbs\s*down|maintenance\s*window)\b", re.I), "BANK_SERVER_DOWN", Decimal("0.9500")),
    (re.compile(r"\b(rate\s*limited?|too\s*many\s*requests|429\s*too\s*many)\b", re.I), "RATE_LIMITED", Decimal("0.9600")),
]



# ============================================================================
# 4. FAILURE INTELLIGENCE SERVICE IMPLEMENTATION
# ============================================================================

class FailureIntelligenceService:
    """Core intelligence engine to classify, diagnose, explain, and benchmark payment failures."""

    def classify_failure(self, request: FailureClassificationRequest) -> FailureIntelligenceDetail:
        """Classify a failure using exact taxonomy lookup, gateway translation, or semantic NLP regex."""
        # 1. Check exact canonical code lookup
        if request.failure_code:
            code_upper = request.failure_code.strip().upper()
            if code_upper in TAXONOMY_CATALOG:
                return self._build_intelligence_detail(
                    normalized_code=code_upper,
                    confidence=Decimal("1.0000"),
                    match_source="EXACT_CODE",
                )

        # 2. Check Gateway-Specific Code Mapping (Razorpay, Stripe, NPCI, ISO8583)
        if request.gateway_code:
            gw_clean = request.gateway_code.strip()
            # Try specified gateway first if provided
            if request.gateway:
                gw_name = request.gateway.strip().upper()
                if gw_name in GATEWAY_CODE_MAPPINGS:
                    mapped = GATEWAY_CODE_MAPPINGS[gw_name].get(gw_clean) or GATEWAY_CODE_MAPPINGS[gw_name].get(gw_clean.lower()) or GATEWAY_CODE_MAPPINGS[gw_name].get(gw_clean.upper())
                    if mapped and mapped in TAXONOMY_CATALOG:
                        return self._build_intelligence_detail(
                            normalized_code=mapped,
                            confidence=Decimal("0.9800"),
                            match_source=f"GATEWAY_MAPPER_{gw_name}",
                        )

            # Search across all gateway tables
            for gw_name, code_map in GATEWAY_CODE_MAPPINGS.items():
                mapped = code_map.get(gw_clean) or code_map.get(gw_clean.lower()) or code_map.get(gw_clean.upper())
                if mapped and mapped in TAXONOMY_CATALOG:
                    return self._build_intelligence_detail(
                        normalized_code=mapped,
                        confidence=Decimal("0.9500"),
                        match_source=f"GATEWAY_MAPPER_{gw_name}",
                    )

        # 3. Check Semantic NLP / Regex Parser on raw error message or raw code string
        text_to_scan = f"{request.raw_message or ''} {request.failure_code or ''} {request.gateway_code or ''}".strip()
        if text_to_scan:
            for pattern, target_code, confidence in SEMANTIC_REGEX_PATTERNS:
                if pattern.search(text_to_scan):
                    return self._build_intelligence_detail(
                        normalized_code=target_code,
                        confidence=confidence,
                        match_source="SEMANTIC_PARSER",
                    )

        # 4. Fallback for unclassified failure
        return self._build_fallback_detail(
            raw_input=request.failure_code or request.gateway_code or request.raw_message or "UNKNOWN"
        )

    def _build_intelligence_detail(
        self, normalized_code: str, confidence: Decimal, match_source: str
    ) -> FailureIntelligenceDetail:
        """Construct full intelligence detail model from catalog entry."""
        info = TAXONOMY_CATALOG[normalized_code]
        category: FailureCategory = info["category"]
        recoverable: bool = info["recoverable"]

        reason_codes = [
            f"REASON_{normalized_code}",
            f"CATEGORY_{category.value}",
            "RECOVERABLE" if recoverable else "UNRECOVERABLE_HARD_STOP",
            match_source,
        ]

        return FailureIntelligenceDetail(
            normalized_code=normalized_code,
            category=category,
            recoverable=recoverable,
            confidence=confidence,
            match_source=match_source,
            suggested_action=info["suggested_action"],
            permitted_actions=info.get("permitted_actions", [info["suggested_action"]]),
            reason_codes=reason_codes,
            retry_delay_seconds=info.get("default_delay_seconds", 0),
            max_retries_permitted=info.get("max_retries", 0),
            customer_explanation=info["customer_explanation"],
            merchant_explanation=info["merchant_explanation"],
            alternative_payment_methods=info.get("alternative_methods", []),
            compliance_notes=info.get("compliance_notes", []),
        )

    def _build_fallback_detail(self, raw_input: str) -> FailureIntelligenceDetail:
        """Construct a safe fallback detail when failure code cannot be recognized."""
        return FailureIntelligenceDetail(
            normalized_code="UNKNOWN_FAILURE",
            category=FailureCategory.UNKNOWN,
            recoverable=False,
            confidence=Decimal("0.2000"),
            match_source="FALLBACK",
            suggested_action=ActionType.STOP_RECOVERY.value,
            permitted_actions=[ActionType.STOP_RECOVERY.value],
            reason_codes=["UNCLASSIFIED_FAILURE", f"RAW_{raw_input}"],
            retry_delay_seconds=0,
            max_retries_permitted=0,
            customer_explanation="Your payment could not be processed. Please check with your bank or try an alternative method.",
            merchant_explanation=f"Unrecognized error format or code: '{raw_input}'. Defaulting to stop recovery to avoid unsafe loops.",
            alternative_payment_methods=["UPI", "CARD"],
            compliance_notes=["Safety guardrail: unclassified failures are treated as non-retryable by default."],
        )

    def get_taxonomy(self) -> FailureTaxonomyResponse:
        """Retrieve full taxonomy catalog, categories, gateway mappings, and retry limits."""
        items: list[FailureTaxonomyItem] = []
        for code, data in TAXONOMY_CATALOG.items():
            items.append(
                FailureTaxonomyItem(
                    failure_code=code,
                    category=data["category"],
                    recoverable=data["recoverable"],
                    description=data["description"],
                    typical_gateways=data["typical_gateways"],
                    suggested_action=data["suggested_action"],
                    max_retries=data["max_retries"],
                    default_delay_seconds=data["default_delay_seconds"],
                    alternative_methods=data["alternative_methods"],
                )
            )

        return FailureTaxonomyResponse(
            version="taxonomy.v1",
            categories=[
                FailureCategory.TEMPORARY,
                FailureCategory.PAYMENT_METHOD,
                FailureCategory.CUSTOMER_ACTION,
                FailureCategory.HARD_FAILURE,
            ],
            codes_count=len(items),
            taxonomy=items,
            gateway_mappings=GATEWAY_CODE_MAPPINGS,
        )

    def explain_code(self, failure_code: str) -> FailureIntelligenceDetail:
        """Deep explanation for a specific failure code."""
        req = FailureClassificationRequest(failure_code=failure_code)
        return self.classify_failure(req)

    def calculate_analytics(self, session: Session) -> dict[str, Any]:
        """Aggregate failure intelligence analytics across all failure events and payment attempts."""
        total_failures = session.scalar(select(func.count()).select_from(FailureEvent)) or 0

        # Category Breakdown
        cat_counts: dict[str, int] = {
            FailureCategory.TEMPORARY.value: 0,
            FailureCategory.PAYMENT_METHOD.value: 0,
            FailureCategory.CUSTOMER_ACTION.value: 0,
            FailureCategory.HARD_FAILURE.value: 0,
        }

        cat_rows = session.execute(
            select(FailureEvent.category, func.count(FailureEvent.id))
            .group_by(FailureEvent.category)
        ).all()

        for cat, cnt in cat_rows:
            if cat in cat_counts:
                cat_counts[cat] = cnt

        # Recovery stats per category
        # A category is deemed recovered if associated transaction state is SUCCEEDED or recovery case is RECOVERED
        cat_metrics: list[CategoryMetric] = []
        for cat_name, cnt in cat_counts.items():
            pct = Decimal(f"{(cnt / total_failures * 100):.2f}") if total_failures > 0 else Decimal("0.00")
            
            # Find top failure code in this category
            top_code = session.scalar(
                select(FailureEvent.failure_code)
                .where(FailureEvent.category == cat_name)
                .group_by(FailureEvent.failure_code)
                .order_by(func.count(FailureEvent.id).desc())
                .limit(1)
            )

            # Calculate recovery conversion for this category
            recovered_count = session.scalar(
                select(func.count(func.distinct(FailureEvent.transaction_id)))
                .join(RecoveryCase, FailureEvent.transaction_id == RecoveryCase.transaction_id)
                .where(FailureEvent.category == cat_name, RecoveryCase.state == RecoveryState.RECOVERED)
            ) or 0

            rec_rate = Decimal(f"{(recovered_count / cnt):.4f}") if cnt > 0 else Decimal("0.0000")

            cat_metrics.append(
                CategoryMetric(
                    category=FailureCategory(cat_name),
                    count=cnt,
                    percentage=pct,
                    recovery_rate=rec_rate,
                    top_failure_code=top_code,
                )
            )

        # Top 5 Failure Codes
        top_codes_rows = session.execute(
            select(FailureEvent.failure_code, FailureEvent.category, func.count(FailureEvent.id).label("cnt"))
            .group_by(FailureEvent.failure_code, FailureEvent.category)
            .order_by(func.count(FailureEvent.id).desc())
            .limit(5)
        ).all()

        top_codes = [
            {"failure_code": r[0], "category": r[1], "count": r[2]}
            for r in top_codes_rows
        ]

        # Gateway Failure Rates
        gw_rows = session.execute(
            select(PaymentAttempt.gateway, func.count(PaymentAttempt.id))
            .where(PaymentAttempt.failure_code.is_not(None))
            .group_by(PaymentAttempt.gateway)
            .order_by(func.count(PaymentAttempt.id).desc())
        ).all()

        gw_failures = [
            {"gateway": r[0] or "UNKNOWN", "failure_count": r[1]}
            for r in gw_rows
        ]

        # Method Failure Rates
        method_rows = session.execute(
            select(PaymentAttempt.payment_method, func.count(PaymentAttempt.id))
            .where(PaymentAttempt.failure_code.is_not(None))
            .group_by(PaymentAttempt.payment_method)
            .order_by(func.count(PaymentAttempt.id).desc())
        ).all()

        method_failures = [
            {"payment_method": r[0], "failure_count": r[1]}
            for r in method_rows
        ]

        # Anomaly Detection
        anomalies: list[FailureAnomalyAlert] = []
        if total_failures > 10:
            temp_ratio = cat_counts[FailureCategory.TEMPORARY.value] / total_failures
            if temp_ratio > 0.60:
                anomalies.append(
                    FailureAnomalyAlert(
                        alert_type="TRANSIENT_SPIKE_DETECTED",
                        severity="WARNING",
                        category=FailureCategory.TEMPORARY,
                        message=f"Temporary failures account for {temp_ratio*100:.1f}% of total failures (threshold 60%). Upstream bank CBS or network degradation suspected.",
                        recommended_action="Enable automated delayed retries with exponential backoff.",
                    )
                )

            hard_ratio = cat_counts[FailureCategory.HARD_FAILURE.value] / total_failures
            if hard_ratio > 0.35:
                anomalies.append(
                    FailureAnomalyAlert(
                        alert_type="FRAUD_RISK_SURGE",
                        severity="CRITICAL",
                        category=FailureCategory.HARD_FAILURE,
                        message=f"Hard failures account for {hard_ratio*100:.1f}% of total failures. Potential card testing attack or BIN velocity block.",
                        recommended_action="Activate merchant fraud throttling and restrict repeated checkout attempts.",
                    )
                )

        return {
            "total_failures_recorded": total_failures,
            "category_breakdown": cat_metrics,
            "top_failure_codes": top_codes,
            "gateway_failure_rates": gw_failures,
            "method_failure_rates": method_failures,
            "anomalies_detected": anomalies,
        }


# Singleton service instance
failure_intelligence_service = FailureIntelligenceService()
