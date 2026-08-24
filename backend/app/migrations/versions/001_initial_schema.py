"""Initial schema — all Day 1-2 recovery domain tables.

Revision ID: 001
Revises: None
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- customers ---
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("external_customer_id", sa.String(128), unique=True, nullable=False),
        sa.Column("merchant_id", sa.String(128), nullable=False),
        sa.Column("preferred_payment_method", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_customers_external_customer_id", "customers", ["external_customer_id"], unique=True)
    op.create_index("ix_customers_merchant_id", "customers", ["merchant_id"])

    # --- transactions ---
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("external_transaction_id", sa.String(128), unique=True, nullable=False),
        sa.Column("merchant_id", sa.String(128), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("status", sa.Enum("CREATED", "PROCESSING", "FAILED", "SUCCEEDED", name="transactionstatus"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_transactions_external_transaction_id", "transactions", ["external_transaction_id"], unique=True)
    op.create_index("ix_transactions_merchant_id", "transactions", ["merchant_id"])
    op.create_index("ix_transactions_customer_id", "transactions", ["customer_id"])
    op.create_index("ix_transactions_merchant_status_created", "transactions", ["merchant_id", "status", "created_at"])

    # --- payment_attempts ---
    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("payment_method", sa.String(32), nullable=False),
        sa.Column("gateway", sa.String(64), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payment_attempts_transaction_id", "payment_attempts", ["transaction_id"])
    op.create_index("ix_payment_attempts_failure_code", "payment_attempts", ["failure_code"])
    op.create_index("uq_attempt_transaction_number", "payment_attempts", ["transaction_id", "attempt_number"], unique=True)

    # --- failure_events ---
    op.create_table(
        "failure_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_event_id", sa.String(128), unique=True, nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("payment_attempts.id"), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("recoverable", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_failure_events_source_event_id", "failure_events", ["source_event_id"], unique=True)
    op.create_index("ix_failure_events_transaction_id", "failure_events", ["transaction_id"])
    op.create_index("ix_failure_events_attempt_id", "failure_events", ["attempt_id"])
    op.create_index("ix_failure_events_category", "failure_events", ["category"])

    # --- recovery_cases ---
    op.create_table(
        "recovery_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("state", sa.Enum("OPEN", "SCHEDULED", "RECOVERED", "STOPPED", "NEEDS_REVIEW", name="recoverystate"), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_recovery_cases_transaction_id", "recovery_cases", ["transaction_id"])
    op.create_index("ix_recovery_cases_state", "recovery_cases", ["state"])

    # --- recovery_actions ---
    op.create_table(
        "recovery_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("recovery_case_id", sa.Uuid(), sa.ForeignKey("recovery_cases.id"), nullable=False),
        sa.Column("action_type", sa.Enum(
            "RETRY_SAME_METHOD", "SWITCH_TO_UPI", "SWITCH_TO_CARD", "SWITCH_TO_NETBANKING",
            "DELAYED_RETRY", "CUSTOMER_NOTIFICATION", "PAYMENT_LINK", "STOP_RECOVERY",
            name="actiontype",
        ), nullable=False),
        sa.Column("idempotency_key", sa.String(160), unique=True, nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("probability", sa.Numeric(5, 4), nullable=True),
        sa.Column("expected_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_recovery_actions_recovery_case_id", "recovery_actions", ["recovery_case_id"])

    # --- outbox_events ---
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_unpublished_created", "outbox_events", ["published_at", "created_at"])

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_transaction_id", "audit_logs", ["transaction_id"])
    op.create_index("ix_audit_transaction_created", "audit_logs", ["transaction_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("outbox_events")
    op.drop_table("recovery_actions")
    op.drop_table("recovery_cases")
    op.drop_table("failure_events")
    op.drop_table("payment_attempts")
    op.drop_table("transactions")
    op.drop_table("customers")
    op.execute("DROP TYPE IF EXISTS transactionstatus")
    op.execute("DROP TYPE IF EXISTS recoverystate")
    op.execute("DROP TYPE IF EXISTS actiontype")
