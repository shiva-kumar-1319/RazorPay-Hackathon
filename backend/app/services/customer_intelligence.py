"""Customer Intelligence Service for computing behavioral analytics, method preferences, and ML features."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from backend.app.models.recovery import (
    Customer,
    CustomerIntelligence,
    PaymentAttempt,
    RecoveryCase,
    RecoveryState,
    Transaction,
    TransactionStatus,
)
from backend.app.schemas.customers import (
    CustomerCreateRequest,
    CustomerDetailResponse,
    CustomerFeaturesSnapshot,
    CustomerIntelligenceDetail,
    CustomerPaymentBehaviorResponse,
    CustomerRecoveryHistoryItem,
    CustomerRecoveryHistoryResponse,
    CustomerSummaryItem,
    CustomerUpdateRequest,
    PaymentMethodStat,
)

logger = logging.getLogger("recoverx.customer_intelligence")


def _normalize_dt(dt: datetime | None) -> datetime:
    """Normalize datetime to UTC for timezone-safe comparisons."""
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def compute_customer_intelligence(
    session: Session, customer_id: UUID, persist: bool = True
) -> CustomerIntelligence:
    """Dynamically aggregate customer transaction history, payment attempts, and recovery performance."""
    customer = session.scalar(
        select(Customer)
        .options(
            joinedload(Customer.transactions).joinedload(Transaction.attempts),
            joinedload(Customer.transactions).joinedload(Transaction.recovery_cases),
            joinedload(Customer.intelligence),
        )
        .where(Customer.id == customer_id)
    )
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    transactions = customer.transactions or []
    total_txns = len(transactions)

    successful_txns = 0
    failed_txns = 0
    recovered_txns = 0
    total_spent = Decimal("0.00")
    total_recovered_amount = Decimal("0.00")

    method_attempts: dict[str, int] = {}
    method_successes: dict[str, int] = {}
    method_failures: dict[str, int] = {}
    method_volumes: dict[str, Decimal] = {}
    method_last_used: dict[str, datetime] = {}
    hourly_counts: dict[str, int] = {str(h): 0 for h in range(24)}

    all_attempts_chronological: list[tuple[datetime, PaymentAttempt, Transaction]] = []

    last_active_at: datetime | None = None
    last_successful_method: str | None = None
    last_failure_code: str | None = None

    for txn in sorted(transactions, key=lambda t: _normalize_dt(t.created_at)):
        txn_created_norm = _normalize_dt(txn.created_at)
        if last_active_at is None or txn_created_norm > _normalize_dt(last_active_at):
            last_active_at = txn.created_at

        # Check transaction state
        if txn.status == TransactionStatus.SUCCEEDED:
            successful_txns += 1
            total_spent += Decimal(str(txn.amount))
            # Check if this succeeded after prior failure / recovery
            if len(txn.attempts) > 1 or txn.recovery_cases:
                recovered_txns += 1
                total_recovered_amount += Decimal(str(txn.amount))
        elif txn.status == TransactionStatus.FAILED:
            failed_txns += 1

        for att in sorted(txn.attempts, key=lambda a: (a.attempt_number or 1, _normalize_dt(a.created_at))):
            m = (att.payment_method or "UNKNOWN").upper()
            method_attempts[m] = method_attempts.get(m, 0) + 1
            method_volumes[m] = method_volumes.get(m, Decimal("0.00")) + Decimal(str(txn.amount))
            
            att_time = att.created_at or txn.created_at or datetime.now(timezone.utc)
            att_created_norm = _normalize_dt(att_time)
            if m not in method_last_used or att_created_norm > _normalize_dt(method_last_used[m]):
                method_last_used[m] = att_time
            h_key = str(att_time.hour)
            hourly_counts[h_key] = hourly_counts.get(h_key, 0) + 1
            all_attempts_chronological.append((att_time, att, txn))

            if att.failure_code:
                method_failures[m] = method_failures.get(m, 0) + 1
                last_failure_code = att.failure_code
            else:
                method_successes[m] = method_successes.get(m, 0) + 1
                last_successful_method = m

    # Calculate success rate & recovery rate
    success_rate = (
        Decimal(str(round(successful_txns / total_txns, 4)))
        if total_txns > 0
        else Decimal("0.0000")
    )
    
    # Cases where recovery was applicable
    recovery_candidate_cases = [
        c for txn in transactions for c in txn.recovery_cases
    ]
    recovered_cases_count = len([
        c for c in recovery_candidate_cases if c.state == RecoveryState.RECOVERED or (c.transaction and c.transaction.status == TransactionStatus.SUCCEEDED)
    ])
    
    recovery_rate = (
        Decimal(str(round(recovered_cases_count / len(recovery_candidate_cases), 4)))
        if recovery_candidate_cases
        else Decimal("0.0000")
    )

    # Method success rates
    method_success_rates: dict[str, float] = {}
    for m, att_count in method_attempts.items():
        succ = method_successes.get(m, 0)
        method_success_rates[m] = round(succ / att_count, 4) if att_count > 0 else 0.0

    # Determine preferred method
    if customer.preferred_payment_method:
        preferred_method = customer.preferred_payment_method.upper()
    elif method_attempts:
        # Prefer method with highest success count, then highest volume
        preferred_method = max(
            method_attempts.keys(),
            key=lambda k: (method_successes.get(k, 0), method_volumes.get(k, Decimal("0.00"))),
        )
    else:
        preferred_method = "UPI"

    # Calculate recent failure streak
    all_attempts_chronological.sort(
        key=lambda x: (_normalize_dt(x[0]), _normalize_dt(x[2].created_at), str(x[2].id), x[1].attempt_number or 1),
        reverse=True,
    )
    recent_failure_streak = 0
    for _, att, _ in all_attempts_chronological:
        if att.failure_code:
            recent_failure_streak += 1
        else:
            break

    # Average transaction value
    avg_txn_value = (
        (total_spent / Decimal(str(successful_txns))).quantize(Decimal("0.01"))
        if successful_txns > 0
        else (
            (sum((Decimal(str(t.amount)) for t in transactions), Decimal("0.00")) / Decimal(str(max(1, total_txns)))).quantize(Decimal("0.01"))
        )
    )

    # Behavioral Segmentation
    behavioral_segment = _classify_behavioral_segment(
        total_txns=total_txns,
        total_spent=total_spent,
        success_rate=float(success_rate),
        preferred_method=preferred_method,
        method_attempts=method_attempts,
        failed_txns=failed_txns,
        recovered_txns=recovered_txns,
        recent_failure_streak=recent_failure_streak,
        risk_tier=customer.risk_segment,
    )

    # Calculate Risk Score (0.0000 - 1.0000)
    risk_score = _calculate_risk_score(
        success_rate=float(success_rate),
        recent_failure_streak=recent_failure_streak,
        last_failure_code=last_failure_code,
        risk_tier=customer.risk_segment,
        total_txns=total_txns,
    )

    # Build standardized ML feature snapshot
    now = datetime.now(timezone.utc)
    recency_days = (
        (now - _normalize_dt(last_active_at)).total_seconds() / 86400.0
        if last_active_at
        else 999.0
    )
    upi_affinity = method_success_rates.get("UPI", 0.5) if "UPI" in method_attempts else 0.5
    card_affinity = method_success_rates.get("CARD", 0.5) if "CARD" in method_attempts else 0.5
    avg_amt_log = math.log(max(1.0, float(avg_txn_value)))

    features_dict = {
        "customer_total_transactions": total_txns,
        "customer_successful_transactions": successful_txns,
        "customer_failed_transactions": failed_txns,
        "customer_recovered_transactions": recovered_txns,
        "customer_success_rate": float(success_rate),
        "customer_recovery_rate": float(recovery_rate),
        "customer_recency_days": round(recency_days, 2),
        "customer_upi_affinity": round(upi_affinity, 4),
        "customer_card_affinity": round(card_affinity, 4),
        "customer_avg_amount_log": round(avg_amt_log, 4),
        "customer_failure_streak": recent_failure_streak,
        "customer_risk_score": float(risk_score),
        "customer_preferred_method": preferred_method,
        "customer_behavioral_segment": behavioral_segment,
    }

    feature_vector = [
        float(total_txns),
        float(success_rate),
        min(365.0, recency_days),
        float(upi_affinity),
        float(card_affinity),
        float(avg_amt_log),
        float(recent_failure_streak),
        float(recovery_rate),
        float(risk_score),
    ]

    intel = session.scalar(
        select(CustomerIntelligence).where(CustomerIntelligence.customer_id == customer.id)
    )
    if intel is None:
        intel = CustomerIntelligence(customer_id=customer.id)
        session.add(intel)
        session.flush()

    intel.total_transactions = total_txns
    intel.successful_transactions = successful_txns
    intel.failed_transactions = failed_txns
    intel.recovered_transactions = recovered_txns
    intel.total_spent = total_spent
    intel.total_recovered_amount = total_recovered_amount
    intel.success_rate = success_rate
    intel.recovery_rate = recovery_rate
    intel.preferred_payment_method = preferred_method
    intel.method_success_rates = method_success_rates
    intel.method_usage_counts = method_attempts
    intel.recent_failure_streak = recent_failure_streak
    intel.average_transaction_value = avg_txn_value
    intel.last_active_at = last_active_at
    intel.last_successful_method = last_successful_method
    intel.last_failure_code = last_failure_code
    intel.risk_score = risk_score
    intel.behavioral_segment = behavioral_segment
    intel.features = {
        "metrics": features_dict,
        "feature_vector": feature_vector,
        "hourly_distribution": hourly_counts,
    }
    intel.computed_at = now

    if persist:
        session.commit()
        session.refresh(intel)

    return intel


def _classify_behavioral_segment(
    total_txns: int,
    total_spent: Decimal,
    success_rate: float,
    preferred_method: str,
    method_attempts: dict[str, int],
    failed_txns: int,
    recovered_txns: int,
    recent_failure_streak: int,
    risk_tier: str,
) -> str:
    """Classify customer into actionable business & recovery personas."""
    if total_txns == 0:
        return "NEW_CUSTOMER"
    if risk_tier.upper() == "VIP" or total_spent >= Decimal("15000.00") or (total_txns >= 5 and success_rate >= 0.85):
        return "VIP_HIGH_VALUE"
    if recent_failure_streak >= 3 or (total_txns >= 3 and success_rate < 0.25):
        return "HIGH_FAILURE_RISK"
    if method_attempts.get("UPI", 0) / max(1, sum(method_attempts.values())) >= 0.60:
        return "UPI_MOBILE_PREFERRED"
    if method_attempts.get("CARD", 0) / max(1, sum(method_attempts.values())) >= 0.50 and failed_txns >= 1:
        return "CARD_DECLINE_PRONE_RECOVERABLE"
    if recovered_txns >= 1 and success_rate >= 0.50:
        return "RECOVERY_RESPONSIVE"
    if total_txns <= 2:
        return "FIRST_TIME_SHOPPER"
    return "STANDARD_RELIABLE"


def _calculate_risk_score(
    success_rate: float,
    recent_failure_streak: int,
    last_failure_code: str | None,
    risk_tier: str,
    total_txns: int,
) -> Decimal:
    """Compute financial & recovery risk score between 0.0000 and 1.0000."""
    base_score = 0.20

    if risk_tier.upper() == "VIP":
        base_score -= 0.15
    elif risk_tier.upper() == "HIGH_RISK":
        base_score += 0.40

    if total_txns == 0:
        base_score += 0.10
    else:
        # High success reduces risk
        base_score -= (success_rate * 0.20)

    # Streak penalty
    base_score += min(0.35, recent_failure_streak * 0.10)

    # Hard stop failure history penalty
    if last_failure_code in ("FRAUD_REJECTED", "BLOCKED_CARD", "INVALID_ACCOUNT"):
        base_score += 0.40

    clamped = max(0.01, min(0.99, base_score))
    return Decimal(str(round(clamped, 4)))


def get_customer_payment_behavior(
    session: Session, customer_id: UUID
) -> CustomerPaymentBehaviorResponse:
    """Return detailed payment behavior breakdown, method statistics, and channel responsiveness."""
    intel = compute_customer_intelligence(session, customer_id, persist=True)
    customer = session.scalar(
        select(Customer)
        .options(joinedload(Customer.transactions).joinedload(Transaction.attempts))
        .where(Customer.id == customer_id)
    )
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    transactions = customer.transactions or []
    method_data: dict[str, dict[str, Any]] = {}

    for txn in transactions:
        for att in txn.attempts:
            m = (att.payment_method or "UNKNOWN").upper()
            if m not in method_data:
                method_data[m] = {
                    "method": m,
                    "total_attempts": 0,
                    "successful_attempts": 0,
                    "failed_attempts": 0,
                    "total_volume": Decimal("0.00"),
                    "last_used_at": None,
                }
            
            entry = method_data[m]
            entry["total_attempts"] += 1
            entry["total_volume"] += Decimal(str(txn.amount))
            if att.created_at:
                if entry["last_used_at"] is None or att.created_at > entry["last_used_at"]:
                    entry["last_used_at"] = att.created_at

            if att.failure_code:
                entry["failed_attempts"] += 1
            else:
                entry["successful_attempts"] += 1

    method_stats: list[PaymentMethodStat] = []
    for m, d in method_data.items():
        tot = d["total_attempts"]
        succ = d["successful_attempts"]
        avg_amt = (d["total_volume"] / Decimal(str(tot))).quantize(Decimal("0.01")) if tot > 0 else Decimal("0.00")
        method_stats.append(
            PaymentMethodStat(
                method=m,
                total_attempts=tot,
                successful_attempts=succ,
                failed_attempts=d["failed_attempts"],
                success_rate=round(succ / tot, 4) if tot > 0 else 0.0,
                total_volume=d["total_volume"],
                average_amount=avg_amt,
                last_used_at=d["last_used_at"],
            )
        )

    features_meta = intel.features if isinstance(intel.features, dict) else {}
    hourly = features_meta.get("hourly_distribution", {str(h): 0 for h in range(24)})

    # Channel affinity estimate
    upi_affinity = float(intel.method_success_rates.get("UPI", 0.75))
    card_affinity = float(intel.method_success_rates.get("CARD", 0.50))
    link_affinity = 0.65 if intel.behavioral_segment in ("VIP_HIGH_VALUE", "UPI_MOBILE_PREFERRED") else 0.50

    return CustomerPaymentBehaviorResponse(
        customer_id=customer.id,
        external_customer_id=customer.external_customer_id,
        merchant_id=customer.merchant_id,
        computed_at=intel.computed_at,
        preferred_payment_method=intel.preferred_payment_method,
        behavioral_segment=intel.behavioral_segment,
        risk_score=intel.risk_score,
        recent_failure_streak=intel.recent_failure_streak,
        average_transaction_value=intel.average_transaction_value,
        last_successful_method=intel.last_successful_method,
        last_failure_code=intel.last_failure_code,
        methods=method_stats,
        hourly_distribution=hourly,
        retry_tolerance_score=max(0.1, min(0.95, round(1.0 - float(intel.risk_score), 2))),
        channel_affinity={
            "SWITCH_TO_UPI": round(upi_affinity, 4),
            "PAYMENT_LINK": round(link_affinity, 4),
            "RETRY_SAME_METHOD": round(card_affinity * 0.8, 4),
            "CUSTOMER_NOTIFICATION": 0.70,
        },
    )


def get_customer_recovery_history(
    session: Session, customer_id: UUID
) -> CustomerRecoveryHistoryResponse:
    """Fetch customer recovery history timeline and conversion efficiency."""
    customer = session.scalar(
        select(Customer)
        .options(
            joinedload(Customer.transactions).joinedload(Transaction.recovery_cases).joinedload(RecoveryCase.actions),
            joinedload(Customer.transactions).joinedload(Transaction.attempts),
        )
        .where(Customer.id == customer_id)
    )
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    cases_items: list[CustomerRecoveryHistoryItem] = []
    total_recovered = Decimal("0.00")
    recovered_count = 0
    stopped_count = 0
    open_count = 0

    for txn in customer.transactions:
        for case in txn.recovery_cases:
            if case.state == RecoveryState.RECOVERED or txn.status == TransactionStatus.SUCCEEDED:
                recovered_count += 1
                total_recovered += Decimal(str(txn.amount))
            elif case.state == RecoveryState.STOPPED:
                stopped_count += 1
            elif case.state == RecoveryState.OPEN:
                open_count += 1

            # Determine primary recommended action
            selected_action = None
            for act in case.actions:
                if act.selected:
                    selected_action = act.action_type.value
                    break
            if not selected_action and case.actions:
                selected_action = case.actions[0].action_type.value

            latest_att = txn.attempts[-1] if txn.attempts else None
            failure_code = latest_att.failure_code if latest_att and latest_att.failure_code else "UNKNOWN"

            cases_items.append(
                CustomerRecoveryHistoryItem(
                    recovery_case_id=case.id,
                    transaction_id=txn.id,
                    external_transaction_id=txn.external_transaction_id,
                    amount=txn.amount,
                    currency=txn.currency,
                    state=case.state.value,
                    failure_code=failure_code,
                    actions_count=len(case.actions),
                    recommended_action=selected_action,
                    created_at=case.created_at,
                    updated_at=case.updated_at,
                )
            )

    total_cases = len(cases_items)
    conversion_rate = round(recovered_count / total_cases, 4) if total_cases > 0 else 0.0

    return CustomerRecoveryHistoryResponse(
        customer_id=customer.id,
        external_customer_id=customer.external_customer_id,
        total_recovery_cases=total_cases,
        recovered_cases=recovered_count,
        stopped_cases=stopped_count,
        open_cases=open_count,
        recovery_conversion_rate=conversion_rate,
        total_recovered_amount=total_recovered,
        cases=sorted(cases_items, key=lambda c: c.created_at, reverse=True),
    )


def extract_customer_features(
    session: Session, customer_id: UUID
) -> CustomerFeaturesSnapshot:
    """Generate normalized point-in-time ML feature snapshot for decision engine and model scoring."""
    intel = compute_customer_intelligence(session, customer_id, persist=True)
    customer = session.scalar(select(Customer).where(Customer.id == customer_id))
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    features_blob = intel.features if isinstance(intel.features, dict) else {}
    metrics = features_blob.get("metrics", {})
    vector = features_blob.get("feature_vector", [])

    return CustomerFeaturesSnapshot(
        customer_id=customer.id,
        external_customer_id=customer.external_customer_id,
        merchant_id=customer.merchant_id,
        snapshot_time=intel.computed_at,
        feature_version="v1",
        features=metrics,
        feature_vector=vector,
    )


# Customer CRUD Helpers


def list_customers(
    session: Session,
    merchant_id: str | None = None,
    risk_segment: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[CustomerSummaryItem]]:
    """List customers with optional merchant, risk tier, or search filters."""
    query = select(Customer).options(
        joinedload(Customer.intelligence),
        joinedload(Customer.transactions),
    )

    if merchant_id:
        query = query.where(Customer.merchant_id == merchant_id)
    if risk_segment:
        query = query.where(Customer.risk_segment == risk_segment.upper())
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Customer.external_customer_id.ilike(search_term),
                Customer.name.ilike(search_term),
                Customer.email.ilike(search_term),
            )
        )

    count_stmt = select(func.count(Customer.id))
    if merchant_id:
        count_stmt = count_stmt.where(Customer.merchant_id == merchant_id)
    if risk_segment:
        count_stmt = count_stmt.where(Customer.risk_segment == risk_segment.upper())
    if search:
        search_term = f"%{search}%"
        count_stmt = count_stmt.where(
            or_(
                Customer.external_customer_id.ilike(search_term),
                Customer.name.ilike(search_term),
                Customer.email.ilike(search_term),
            )
        )

    total = session.scalar(count_stmt) or 0
    customers = list(
        session.scalars(query.order_by(Customer.created_at.desc()).limit(limit).offset(offset))
        .unique()
        .all()
    )

    items: list[CustomerSummaryItem] = []
    for c in customers:
        intel = c.intelligence
        # Compute if intelligence is missing
        if intel is None:
            intel = compute_customer_intelligence(session, c.id, persist=False)

        items.append(
            CustomerSummaryItem(
                id=c.id,
                external_customer_id=c.external_customer_id,
                merchant_id=c.merchant_id,
                name=c.name,
                email=c.email,
                preferred_payment_method=intel.preferred_payment_method or c.preferred_payment_method,
                risk_segment=c.risk_segment,
                behavioral_segment=intel.behavioral_segment,
                total_transactions=intel.total_transactions,
                total_spent=intel.total_spent,
                success_rate=intel.success_rate,
                recovered_count=intel.recovered_transactions,
                recent_failure_streak=intel.recent_failure_streak,
                last_active_at=intel.last_active_at,
                created_at=c.created_at,
            )
        )

    return total, items


def get_customer_detail(session: Session, customer_id: UUID) -> CustomerDetailResponse:
    """Fetch complete customer profile with intelligence stats."""
    intel = compute_customer_intelligence(session, customer_id, persist=True)
    customer = session.scalar(
        select(Customer)
        .options(joinedload(Customer.transactions))
        .where(Customer.id == customer_id)
    )
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    intel_detail = CustomerIntelligenceDetail(
        total_transactions=intel.total_transactions,
        successful_transactions=intel.successful_transactions,
        failed_transactions=intel.failed_transactions,
        recovered_transactions=intel.recovered_transactions,
        total_spent=intel.total_spent,
        total_recovered_amount=intel.total_recovered_amount,
        success_rate=intel.success_rate,
        recovery_rate=intel.recovery_rate,
        preferred_payment_method=intel.preferred_payment_method,
        method_success_rates=intel.method_success_rates or {},
        method_usage_counts=intel.method_usage_counts or {},
        recent_failure_streak=intel.recent_failure_streak,
        average_transaction_value=intel.average_transaction_value,
        last_active_at=intel.last_active_at,
        last_successful_method=intel.last_successful_method,
        last_failure_code=intel.last_failure_code,
        risk_score=intel.risk_score,
        behavioral_segment=intel.behavioral_segment,
        computed_at=intel.computed_at,
    )

    return CustomerDetailResponse(
        id=customer.id,
        external_customer_id=customer.external_customer_id,
        merchant_id=customer.merchant_id,
        name=customer.name,
        email=customer.email,
        phone=customer.phone,
        preferred_payment_method=customer.preferred_payment_method,
        risk_segment=customer.risk_segment,
        metadata=customer.metadata_ or {},
        intelligence=intel_detail,
        recent_transactions_count=len(customer.transactions),
        created_at=customer.created_at,
        updated_at=customer.updated_at,
    )


def create_customer(session: Session, data: CustomerCreateRequest) -> Customer:
    """Register a new customer profile."""
    existing = session.scalar(
        select(Customer).where(Customer.external_customer_id == data.external_customer_id)
    )
    if existing:
        raise ValueError(f"Customer with external_id {data.external_customer_id} already exists")

    customer = Customer(
        external_customer_id=data.external_customer_id,
        merchant_id=data.merchant_id,
        name=data.name,
        email=data.email,
        phone=data.phone,
        preferred_payment_method=data.preferred_payment_method.upper() if data.preferred_payment_method else None,
        risk_segment=data.risk_segment.upper(),
        metadata_=data.metadata,
    )
    session.add(customer)
    session.flush()

    # Initialize empty intelligence
    compute_customer_intelligence(session, customer.id, persist=True)
    return customer


def update_customer(session: Session, customer_id: UUID, data: CustomerUpdateRequest) -> Customer:
    """Update customer details or payment preferences."""
    customer = session.scalar(select(Customer).where(Customer.id == customer_id))
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    if data.name is not None:
        customer.name = data.name
    if data.email is not None:
        customer.email = data.email
    if data.phone is not None:
        customer.phone = data.phone
    if data.preferred_payment_method is not None:
        customer.preferred_payment_method = data.preferred_payment_method.upper()
    if data.risk_segment is not None:
        customer.risk_segment = data.risk_segment.upper()
    if data.metadata is not None:
        customer.metadata_ = data.metadata

    session.flush()
    compute_customer_intelligence(session, customer.id, persist=True)
    return customer
