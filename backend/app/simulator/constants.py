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


from backend.app.canonical_failure_taxonomy import (
    CANONICAL_FAILURE_TAXONOMY,
    CanonicalCategory,
    FailureDefinition,
)

# Canonical taxonomy shared across the platform
FAILURE_CATALOG: dict[str, FailureDefinition] = CANONICAL_FAILURE_TAXONOMY


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
