"""Constants, failure definitions, supported payment methods, and presets for the payment simulator."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PaymentMethod(str, Enum):
    UPI = "UPI"
    CARD = "CARD"
    NETBANKING = "NETBANKING"
    WALLET = "WALLET"
    BNPL = "BNPL"


class Gateway(str, Enum):
    RAZORPAY = "RAZORPAY"
    PAYU = "PAYU"
    CASHFREE = "CASHFREE"
    BILLDESK = "BILLDESK"
    STRIPE = "STRIPE"
    HDFC_SMARTHUB = "HDFC_SMARTHUB"


class SimulationScenario(str, Enum):
    NORMAL_BALANCED = "NORMAL_BALANCED"
    UPI_OUTAGE = "UPI_OUTAGE"
    CARD_AUTH_DEGRADATION = "CARD_AUTH_DEGRADATION"
    HIGH_RISK_FRAUD_SURGE = "HIGH_RISK_FRAUD_SURGE"
    OTP_DROPOFF_PEAK = "OTP_DROPOFF_PEAK"
    GATEWAY_TIMEOUT_BURST = "GATEWAY_TIMEOUT_BURST"


@dataclass(frozen=True)
class FailureDefinition:
    code: str
    category: str
    description: str
    recoverable: bool
    typical_methods: tuple[str, ...]
    default_error_message: str


FAILURE_CATALOG: dict[str, FailureDefinition] = {
    # Hard Failures (Non-recoverable)
    "BLOCKED_CARD": FailureDefinition(
        code="BLOCKED_CARD",
        category="HARD_FAILURE",
        description="Card reported lost, stolen, or frozen by the issuing bank",
        recoverable=False,
        typical_methods=("CARD",),
        default_error_message="The card has been blocked by the issuing bank. Please use another payment method.",
    ),
    "INVALID_ACCOUNT": FailureDefinition(
        code="INVALID_ACCOUNT",
        category="HARD_FAILURE",
        description="The customer bank account or VPA does not exist or has been terminated",
        recoverable=False,
        typical_methods=("UPI", "NETBANKING"),
        default_error_message="Invalid account details or VPA handle.",
    ),
    "FRAUD_REJECTED": FailureDefinition(
        code="FRAUD_REJECTED",
        category="HARD_FAILURE",
        description="Transaction rejected by risk engine due to suspicious anomaly",
        recoverable=False,
        typical_methods=("CARD", "UPI", "WALLET", "NETBANKING", "BNPL"),
        default_error_message="Transaction declined by security risk checks.",
    ),
    "EXPIRED_CARD": FailureDefinition(
        code="EXPIRED_CARD",
        category="HARD_FAILURE",
        description="Card validity date is in the past",
        recoverable=False,
        typical_methods=("CARD",),
        default_error_message="The payment card has expired.",
    ),
    "LIMIT_EXCEEDED_HARD": FailureDefinition(
        code="LIMIT_EXCEEDED_HARD",
        category="HARD_FAILURE",
        description="Daily or per-transaction regulatory limit exceeded on the instrument",
        recoverable=False,
        typical_methods=("CARD", "UPI"),
        default_error_message="Account limits exceeded for this cycle.",
    ),

    # Customer Action Required
    "OTP_TIMEOUT": FailureDefinition(
        code="OTP_TIMEOUT",
        category="CUSTOMER_ACTION",
        description="Customer failed to enter OTP within the allowed window",
        recoverable=True,
        typical_methods=("CARD", "NETBANKING"),
        default_error_message="Authentication OTP expired or was not entered in time.",
    ),
    "3DS_FAILURE": FailureDefinition(
        code="3DS_FAILURE",
        category="CUSTOMER_ACTION",
        description="3D Secure / ACS authentication failed due to incorrect password/biometric",
        recoverable=True,
        typical_methods=("CARD",),
        default_error_message="3D Secure verification failed.",
    ),
    "INSUFFICIENT_FUNDS": FailureDefinition(
        code="INSUFFICIENT_FUNDS",
        category="CUSTOMER_ACTION",
        description="Customer account or credit limit has insufficient balance for transaction",
        recoverable=True,
        typical_methods=("CARD", "UPI", "NETBANKING", "WALLET"),
        default_error_message="Insufficient funds in the selected account.",
    ),
    "INCORRECT_PIN": FailureDefinition(
        code="INCORRECT_PIN",
        category="CUSTOMER_ACTION",
        description="Incorrect UPI MPIN or ATM PIN entered by user",
        recoverable=True,
        typical_methods=("UPI", "CARD"),
        default_error_message="Incorrect UPI PIN / security PIN entered.",
    ),
    "USER_CANCELLED": FailureDefinition(
        code="USER_CANCELLED",
        category="CUSTOMER_ACTION",
        description="Customer actively dismissed the checkout sheet or payment intent",
        recoverable=True,
        typical_methods=("UPI", "CARD", "NETBANKING", "WALLET", "BNPL"),
        default_error_message="Transaction was cancelled by the customer.",
    ),

    # Transient / Temporary Network & System Failures
    "TIMEOUT": FailureDefinition(
        code="TIMEOUT",
        category="TEMPORARY",
        description="Gateway or switch did not return a response within timeout window",
        recoverable=True,
        typical_methods=("UPI", "CARD", "NETBANKING", "WALLET"),
        default_error_message="Gateway connection timed out while processing payment.",
    ),
    "NETWORK_ERROR": FailureDefinition(
        code="NETWORK_ERROR",
        category="TEMPORARY",
        description="Transient network disruption or socket disconnect during transmission",
        recoverable=True,
        typical_methods=("UPI", "CARD", "NETBANKING", "WALLET", "BNPL"),
        default_error_message="Network communication error between gateway and processor.",
    ),
    "UPI_FAILURE": FailureDefinition(
        code="UPI_FAILURE",
        category="TEMPORARY",
        description="NPCI UPI switch degradation or remitter PSP service downtime",
        recoverable=True,
        typical_methods=("UPI",),
        default_error_message="UPI switch is currently experiencing elevated degradation.",
    ),
    "GATEWAY_ERROR": FailureDefinition(
        code="GATEWAY_ERROR",
        category="TEMPORARY",
        description="Payment aggregator internal 5xx error or downstream failure",
        recoverable=True,
        typical_methods=("UPI", "CARD", "NETBANKING", "WALLET", "BNPL"),
        default_error_message="Payment provider internal processing error.",
    ),
    "BANK_SERVER_DOWN": FailureDefinition(
        code="BANK_SERVER_DOWN",
        category="TEMPORARY",
        description="Issuer core banking system (CBS) temporarily unavailable for maintenance",
        recoverable=True,
        typical_methods=("UPI", "NETBANKING", "CARD"),
        default_error_message="Issuer bank servers are currently undergoing maintenance.",
    ),

    # Payment Method Specific
    "CARD_DECLINED": FailureDefinition(
        code="CARD_DECLINED",
        category="PAYMENT_METHOD",
        description="Generic issuer decline, e.g. international transactions or e-commerce disabled",
        recoverable=True,
        typical_methods=("CARD",),
        default_error_message="Card declined by issuer. Online transactions may be disabled.",
    ),
    "CARD_TYPE_NOT_SUPPORTED": FailureDefinition(
        code="CARD_TYPE_NOT_SUPPORTED",
        category="PAYMENT_METHOD",
        description="Card brand or commercial sub-type not supported by merchant terminal",
        recoverable=True,
        typical_methods=("CARD",),
        default_error_message="This specific card brand/type is not supported for this checkout.",
    ),
    "MANDATE_FAILED": FailureDefinition(
        code="MANDATE_FAILED",
        category="PAYMENT_METHOD",
        description="Auto-debit recurring subscription mandate presentation declined",
        recoverable=True,
        typical_methods=("CARD", "UPI", "NETBANKING"),
        default_error_message="Recurring mandate setup or presentation failed.",
    ),
}

# Realistic scenario configurations: (success_rate, method_weights, failure_weights)
SCENARIO_PROFILES: dict[SimulationScenario, dict[str, Any]] = {
    SimulationScenario.NORMAL_BALANCED: {
        "description": "Standard production distribution with ~82% success rate and balanced errors",
        "success_rate": 0.82,
        "method_weights": {
            PaymentMethod.UPI: 0.55,
            PaymentMethod.CARD: 0.30,
            PaymentMethod.NETBANKING: 0.10,
            PaymentMethod.WALLET: 0.03,
            PaymentMethod.BNPL: 0.02,
        },
        "failure_weights": {
            "CARD_DECLINED": 0.20,
            "OTP_TIMEOUT": 0.20,
            "INSUFFICIENT_FUNDS": 0.18,
            "USER_CANCELLED": 0.15,
            "TIMEOUT": 0.10,
            "3DS_FAILURE": 0.07,
            "INCORRECT_PIN": 0.05,
            "BLOCKED_CARD": 0.03,
            "FRAUD_REJECTED": 0.02,
        },
    },
    SimulationScenario.UPI_OUTAGE: {
        "description": "Major NPCI / UPI PSP outage causing severe UPI drop-offs",
        "success_rate": 0.45,
        "method_weights": {
            PaymentMethod.UPI: 0.70,
            PaymentMethod.CARD: 0.20,
            PaymentMethod.NETBANKING: 0.08,
            PaymentMethod.WALLET: 0.02,
        },
        "failure_weights": {
            "UPI_FAILURE": 0.50,
            "TIMEOUT": 0.25,
            "BANK_SERVER_DOWN": 0.15,
            "USER_CANCELLED": 0.10,
        },
    },
    SimulationScenario.CARD_AUTH_DEGRADATION: {
        "description": "Issuing bank 3DS ACS failure surge affecting card transactions",
        "success_rate": 0.50,
        "method_weights": {
            PaymentMethod.CARD: 0.65,
            PaymentMethod.UPI: 0.25,
            PaymentMethod.NETBANKING: 0.10,
        },
        "failure_weights": {
            "3DS_FAILURE": 0.40,
            "OTP_TIMEOUT": 0.30,
            "CARD_DECLINED": 0.20,
            "TIMEOUT": 0.10,
        },
    },
    SimulationScenario.HIGH_RISK_FRAUD_SURGE: {
        "description": "Elevated fraud attack triggering risk engine hard stops and declines",
        "success_rate": 0.55,
        "method_weights": {
            PaymentMethod.CARD: 0.50,
            PaymentMethod.UPI: 0.35,
            PaymentMethod.WALLET: 0.15,
        },
        "failure_weights": {
            "FRAUD_REJECTED": 0.45,
            "BLOCKED_CARD": 0.25,
            "LIMIT_EXCEEDED_HARD": 0.15,
            "CARD_DECLINED": 0.15,
        },
    },
    SimulationScenario.OTP_DROPOFF_PEAK: {
        "description": "SMS gateway latency causing high customer OTP timeouts and abandonment",
        "success_rate": 0.60,
        "method_weights": {
            PaymentMethod.CARD: 0.50,
            PaymentMethod.NETBANKING: 0.30,
            PaymentMethod.UPI: 0.20,
        },
        "failure_weights": {
            "OTP_TIMEOUT": 0.55,
            "USER_CANCELLED": 0.25,
            "3DS_FAILURE": 0.15,
            "TIMEOUT": 0.05,
        },
    },
    SimulationScenario.GATEWAY_TIMEOUT_BURST: {
        "description": "Aggregator gateway degradation causing severe latency and 504 timeouts",
        "success_rate": 0.40,
        "method_weights": {
            PaymentMethod.UPI: 0.45,
            PaymentMethod.CARD: 0.35,
            PaymentMethod.NETBANKING: 0.20,
        },
        "failure_weights": {
            "TIMEOUT": 0.45,
            "GATEWAY_ERROR": 0.30,
            "NETWORK_ERROR": 0.15,
            "BANK_SERVER_DOWN": 0.10,
        },
    },
}

SAMPLE_ISSUER_BANKS = [
    "HDFC Bank",
    "State Bank of India",
    "ICICI Bank",
    "Axis Bank",
    "Kotak Mahindra Bank",
    "Punjab National Bank",
]

SAMPLE_UPI_APPS = [
    "Google Pay",
    "PhonePe",
    "Paytm",
    "BHIM UPI",
    "CRED",
    "Amazon Pay",
]
