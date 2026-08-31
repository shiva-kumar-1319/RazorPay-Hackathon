"""Core transactional models for payment failure recovery."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, JSON, Boolean, Enum as SqlEnum, ForeignKey, Index, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampedModel


class TransactionStatus(str, Enum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"
    SUCCEEDED = "SUCCEEDED"


class RecoveryState(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    RECOVERED = "RECOVERED"
    STOPPED = "STOPPED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ActionType(str, Enum):
    RETRY_SAME_METHOD = "RETRY_SAME_METHOD"
    SWITCH_TO_UPI = "SWITCH_TO_UPI"
    SWITCH_TO_CARD = "SWITCH_TO_CARD"
    SWITCH_TO_NETBANKING = "SWITCH_TO_NETBANKING"
    DELAYED_RETRY = "DELAYED_RETRY"
    CUSTOMER_NOTIFICATION = "CUSTOMER_NOTIFICATION"
    PAYMENT_LINK = "PAYMENT_LINK"
    STOP_RECOVERY = "STOP_RECOVERY"


class Customer(TimestampedModel, Base):
    __tablename__ = "customers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    external_customer_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    merchant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    preferred_payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_segment: Mapped[str] = mapped_column(String(32), default="STANDARD")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    transactions: Mapped[list[Transaction]] = relationship(back_populates="customer")
    intelligence: Mapped[CustomerIntelligence | None] = relationship(
        back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )


class CustomerIntelligence(TimestampedModel, Base):
    __tablename__ = "customer_intelligence"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), unique=True, index=True)
    total_transactions: Mapped[int] = mapped_column(Integer, default=0)
    successful_transactions: Mapped[int] = mapped_column(Integer, default=0)
    failed_transactions: Mapped[int] = mapped_column(Integer, default=0)
    recovered_transactions: Mapped[int] = mapped_column(Integer, default=0)
    total_spent: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    total_recovered_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    success_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.0000"))
    recovery_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.0000"))
    preferred_payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    method_success_rates: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    method_usage_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recent_failure_streak: Mapped[int] = mapped_column(Integer, default=0)
    average_transaction_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.1000"))
    behavioral_segment: Mapped[str] = mapped_column(String(64), default="NEW_CUSTOMER")
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    customer: Mapped[Customer] = relationship(back_populates="intelligence")


class Transaction(TimestampedModel, Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_merchant_status_created", "merchant_id", "status", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    external_transaction_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    merchant_id: Mapped[str] = mapped_column(String(128), index=True)
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[TransactionStatus] = mapped_column(SqlEnum(TransactionStatus), default=TransactionStatus.CREATED)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    customer: Mapped[Customer | None] = relationship(back_populates="transactions")
    attempts: Mapped[list[PaymentAttempt]] = relationship(back_populates="transaction")
    recovery_cases: Mapped[list[RecoveryCase]] = relationship(back_populates="transaction")


class PaymentAttempt(TimestampedModel, Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (Index("uq_attempt_transaction_number", "transaction_id", "attempt_number", unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    payment_method: Mapped[str] = mapped_column(String(32))
    gateway: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(64), index=True)
    transaction: Mapped[Transaction] = relationship(back_populates="attempts")
    failures: Mapped[list[FailureEvent]] = relationship(back_populates="attempt")


class FailureEvent(TimestampedModel, Base):
    __tablename__ = "failure_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("payment_attempts.id"), index=True)
    failure_code: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32), index=True)
    recoverable: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempt: Mapped[PaymentAttempt] = relationship(back_populates="failures")


class RecoveryCase(TimestampedModel, Base):
    __tablename__ = "recovery_cases"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    state: Mapped[RecoveryState] = mapped_column(SqlEnum(RecoveryState), default=RecoveryState.OPEN, index=True)
    policy_version: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    transaction: Mapped[Transaction] = relationship(back_populates="recovery_cases")
    actions: Mapped[list[RecoveryAction]] = relationship(back_populates="recovery_case")


class RecoveryAction(TimestampedModel, Base):
    __tablename__ = "recovery_actions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recovery_case_id: Mapped[UUID] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    action_type: Mapped[ActionType] = mapped_column(SqlEnum(ActionType))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    recovery_case: Mapped[RecoveryCase] = relationship(back_populates="actions")
    customer_sessions: Mapped[list[CustomerRecoverySession]] = relationship(
        back_populates="recovery_action", cascade="all, delete-orphan"
    )


class CustomerRecoverySession(TimestampedModel, Base):
    __tablename__ = "customer_recovery_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recovery_action_id: Mapped[UUID] = mapped_column(ForeignKey("recovery_actions.id"), index=True)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)  # ACTIVE, COMPLETED, EXPIRED
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payment_method_options: Mapped[list[str]] = mapped_column(JSON, default=list)
    customer_notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    recovery_action: Mapped[RecoveryAction] = relationship(back_populates="customer_sessions")
    transaction: Mapped[Transaction] = relationship()


class OutboxEvent(TimestampedModel, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished_created", "published_at", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(96))
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(TimestampedModel, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_transaction_created", "transaction_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(96))
    actor: Mapped[str] = mapped_column(String(64))
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class ProcessedEvent(TimestampedModel, Base):
    __tablename__ = "processed_events"
    __table_args__ = (
        Index("uq_processed_events_consumer_event", "consumer_name", "event_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    consumer_name: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(96))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class QuarantineEvent(TimestampedModel, Base):
    __tablename__ = "quarantine_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_event_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(96), nullable=True)
    consumer_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="QUARANTINED")
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

