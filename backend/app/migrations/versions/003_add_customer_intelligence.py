"""Add customer intelligence table and enrich customers table.

Revision ID: 003
Revises: 002
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enrich customers table ---
    with op.batch_alter_table("customers") as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("phone", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("risk_segment", sa.String(32), nullable=False, server_default="STANDARD"))
        batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.create_index("ix_customers_email", ["email"])

    # --- customer_intelligence table ---
    op.create_table(
        "customer_intelligence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_transactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_transactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_transactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovered_transactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_spent", sa.Numeric(18, 2), nullable=False, server_default="0.00"),
        sa.Column("total_recovered_amount", sa.Numeric(18, 2), nullable=False, server_default="0.00"),
        sa.Column("success_rate", sa.Numeric(5, 4), nullable=False, server_default="0.0000"),
        sa.Column("recovery_rate", sa.Numeric(5, 4), nullable=False, server_default="0.0000"),
        sa.Column("preferred_payment_method", sa.String(32), nullable=True),
        sa.Column("method_success_rates", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("method_usage_counts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("recent_failure_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("average_transaction_value", sa.Numeric(18, 2), nullable=False, server_default="0.00"),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_method", sa.String(32), nullable=True),
        sa.Column("last_failure_code", sa.String(64), nullable=True),
        sa.Column("risk_score", sa.Numeric(5, 4), nullable=False, server_default="0.1000"),
        sa.Column("behavioral_segment", sa.String(64), nullable=False, server_default="NEW_CUSTOMER"),
        sa.Column("features", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_customer_intelligence_customer_id", "customer_intelligence", ["customer_id"], unique=True)


def downgrade() -> None:
    op.drop_table("customer_intelligence")
    with op.batch_alter_table("customers") as batch_op:
        batch_op.drop_index("ix_customers_email")
        batch_op.drop_column("metadata")
        batch_op.drop_column("risk_segment")
        batch_op.drop_column("phone")
        batch_op.drop_column("email")
        batch_op.drop_column("name")
