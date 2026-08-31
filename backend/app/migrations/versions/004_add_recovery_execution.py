"""Add recovery execution fields and customer recovery sessions table.

Revision ID: 004
Revises: 003
Create Date: 2026-08-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enrich recovery_actions table ---
    with op.batch_alter_table("recovery_actions") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"))
        batch_op.add_column(sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("execution_channel", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.create_index("ix_recovery_actions_status", ["status"])
        batch_op.create_index("ix_recovery_actions_scheduled_at", ["scheduled_at"])

    # --- customer_recovery_sessions table ---
    op.create_table(
        "customer_recovery_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("recovery_action_id", sa.Uuid(), sa.ForeignKey("recovery_actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_method_options", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("customer_notes", sa.String(255), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_customer_recovery_sessions_token", "customer_recovery_sessions", ["token"], unique=True)
    op.create_index("ix_customer_recovery_sessions_status", "customer_recovery_sessions", ["status"])
    op.create_index("ix_customer_recovery_sessions_expires_at", "customer_recovery_sessions", ["expires_at"])
    op.create_index("ix_customer_recovery_sessions_recovery_action_id", "customer_recovery_sessions", ["recovery_action_id"])
    op.create_index("ix_customer_recovery_sessions_transaction_id", "customer_recovery_sessions", ["transaction_id"])


def downgrade() -> None:
    op.drop_table("customer_recovery_sessions")
    with op.batch_alter_table("recovery_actions") as batch_op:
        batch_op.drop_index("ix_recovery_actions_scheduled_at")
        batch_op.drop_index("ix_recovery_actions_status")
        batch_op.drop_column("metadata")
        batch_op.drop_column("execution_channel")
        batch_op.drop_column("executed_at")
        batch_op.drop_column("scheduled_at")
        batch_op.drop_column("status")
