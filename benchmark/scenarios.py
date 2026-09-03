"""Benchmark Scenarios with strict separation between Observable Features and Hidden Ground Truth."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random
from typing import Any

from backend.app.canonical_failure_taxonomy import CANONICAL_FAILURE_TAXONOMY, CanonicalCategory


@dataclass(frozen=True)
class HiddenGroundTruth:
    """True latent state of the payment environment, inaccessible to agents/decision engine."""

    customer_willingness_to_retry: float  # 0.0 to 1.0 probability customer complies with link/action
    has_sufficient_balance: bool           # True if customer actually has liquid funds
    has_active_alternate_instrument: bool # True if customer holds UPI handle or valid alternate card
    system_transient_degradation: float    # Probability that immediate retry on same rail fails due to server load
    is_terminal_fraud_or_hotlisted: bool   # Terminal flag: any retry is 100% declined and causes compliance violation


@dataclass(frozen=True)
class ObservableFailureEvent:
    """Observable facts provided to the decision engine, baseline, or agent."""

    transaction_id: str
    external_transaction_id: str
    amount: float
    payment_method: str
    failure_code: str
    failure_category: str
    gateway: str
    hour_of_day: int
    customer_history: dict[str, Any]


@dataclass(frozen=True)
class BenchmarkScenarioItem:
    """A benchmark scenario pairing observable input with strictly hidden ground truth."""

    scenario_id: str
    name: str
    observable: ObservableFailureEvent
    hidden_truth: HiddenGroundTruth


def generate_scenarios(count: int = 1000, seed: int = 42) -> list[BenchmarkScenarioItem]:
    """Generate a reproducible, grounded sequence of payment failure events."""
    rng = random.Random(seed)
    scenarios: list[BenchmarkScenarioItem] = []

    # Probability mix matching Indian payment ecosystem breakdown
    archetypes = [
        # (Weight, Name, Category, FailureCode, DefaultMethod, Gateway)
        (0.20, "OTP Drop-off", "CUSTOMER_ACTION", "OTP_TIMEOUT", "CARD", "RAZORPAY"),
        (0.10, "3DS Challenge Interrupted", "CUSTOMER_ACTION", "3DS_FAILURE", "CARD", "STRIPE"),
        (0.05, "User Cancelled Checkout", "CUSTOMER_ACTION", "USER_CANCELLED", "UPI", "PHONEPE"),
        (0.15, "Card Declined / Do Not Honor", "PAYMENT_METHOD", "CARD_DECLINED", "CARD", "HDFC_SMARTHUB"),
        (0.10, "Card Insufficient Funds", "CUSTOMER_ACTION", "INSUFFICIENT_FUNDS", "CARD", "PAYU"),
        (0.05, "Recurring Mandate Presentation Failed", "PAYMENT_METHOD", "MANDATE_FAILED", "CARD", "BILLDESK"),
        (0.05, "Unsupported Card BIN", "PAYMENT_METHOD", "CARD_TYPE_NOT_SUPPORTED", "CARD", "RAZORPAY"),
        (0.12, "Gateway Network Timeout", "TEMPORARY", "TIMEOUT", "UPI", "RAZORPAY"),
        (0.08, "UPI Switch Degradation", "TEMPORARY", "UPI_FAILURE", "UPI", "NPCI"),
        (0.05, "Bank Core Server Maintenance", "TEMPORARY", "BANK_SERVER_DOWN", "NETBANKING", "SBI_GATEWAY"),
        (0.03, "Fraud Risk Reject", "HARD_FAILURE", "FRAUD_REJECTED", "CARD", "STRIPE"),
        (0.02, "Hotlisted / Blocked Card", "HARD_FAILURE", "BLOCKED_CARD", "CARD", "VISA"),
    ]

    total_weight = sum(w for w, *_ in archetypes)
    normalized_weights = [w / total_weight for w, *_ in archetypes]

    segments = ["HIGH_LOYALTY", "FREQUENT_BUYER", "STANDARD", "HIGH_RISK_NEW"]

    for i in range(count):
        chosen_idx = rng.choices(range(len(archetypes)), weights=normalized_weights, k=1)[0]
        _, arch_name, category, failure_code, payment_method, gateway = archetypes[chosen_idx]

        txn_id = f"txn_bench_{seed}_{i:05d}"
        ext_hash = hashlib.sha256(f"pay:{seed}:{i}".encode("utf-8")).hexdigest()[:12]
        ext_id = f"pay_{ext_hash}"

        # Ground truth modeling based on failure characteristics
        if category == "HARD_FAILURE":
            amount = round(rng.uniform(1500.0, 45000.0), 2)
            hidden = HiddenGroundTruth(
                customer_willingness_to_retry=rng.uniform(0.0, 0.1),
                has_sufficient_balance=rng.choice([True, False]),
                has_active_alternate_instrument=False,
                system_transient_degradation=0.0,
                is_terminal_fraud_or_hotlisted=True,
            )
        elif category == "TEMPORARY":
            amount = round(rng.uniform(250.0, 12000.0), 2)
            hidden = HiddenGroundTruth(
                customer_willingness_to_retry=rng.uniform(0.70, 0.98),
                has_sufficient_balance=True,
                has_active_alternate_instrument=True,
                system_transient_degradation=rng.uniform(0.40, 0.85),
                is_terminal_fraud_or_hotlisted=False,
            )
        elif category == "CUSTOMER_ACTION":
            amount = round(rng.uniform(199.0, 8500.0), 2)
            has_balance = False if failure_code == "INSUFFICIENT_FUNDS" else (rng.random() < 0.85)
            hidden = HiddenGroundTruth(
                customer_willingness_to_retry=rng.uniform(0.45, 0.90),
                has_sufficient_balance=has_balance,
                has_active_alternate_instrument=rng.random() < 0.75,
                system_transient_degradation=rng.uniform(0.05, 0.20),
                is_terminal_fraud_or_hotlisted=False,
            )
        else:  # PAYMENT_METHOD
            amount = round(rng.uniform(499.0, 18000.0), 2)
            hidden = HiddenGroundTruth(
                customer_willingness_to_retry=rng.uniform(0.60, 0.95),
                has_sufficient_balance=True,
                has_active_alternate_instrument=rng.random() < 0.90,
                system_transient_degradation=rng.uniform(0.0, 0.15),
                is_terminal_fraud_or_hotlisted=False,
            )

        segment = rng.choice(segments)
        base_success_rate = {
            "HIGH_LOYALTY": rng.uniform(0.85, 0.98),
            "FREQUENT_BUYER": rng.uniform(0.70, 0.90),
            "STANDARD": rng.uniform(0.50, 0.75),
            "HIGH_RISK_NEW": rng.uniform(0.20, 0.45),
        }[segment]

        customer_history = {
            "success_rate": round(base_success_rate, 4),
            "recovery_rate": round(base_success_rate * rng.uniform(0.5, 0.8), 4),
            "risk_score": round(rng.uniform(0.01, 0.20) if category != "HARD_FAILURE" else rng.uniform(0.70, 0.99), 4),
            "failure_streak": rng.randint(0, 4) if category != "HARD_FAILURE" else rng.randint(3, 8),
            "avg_txn_value": round(amount * rng.uniform(0.8, 1.4), 2),
            "total_txns": rng.randint(1, 45),
            "behavioral_segment": segment,
        }

        observable = ObservableFailureEvent(
            transaction_id=txn_id,
            external_transaction_id=ext_id,
            amount=amount,
            payment_method=payment_method,
            failure_code=failure_code,
            failure_category=category,
            gateway=gateway,
            hour_of_day=rng.randint(0, 23),
            customer_history=customer_history,
        )

        scenarios.append(
            BenchmarkScenarioItem(
                scenario_id=f"scen_{i+1:05d}",
                name=f"{arch_name} (#{i+1})",
                observable=observable,
                hidden_truth=hidden,
            )
        )

    return scenarios
