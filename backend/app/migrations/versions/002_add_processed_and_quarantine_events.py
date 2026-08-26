"""Add processed_events and quarantine_events tables.

Revision ID: 002
Revises: 001
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- processed_events ---
    op.create_table(
        "processed_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("consumer_name", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_processed_events_consumer_event",
        "processed_events",
        ["consumer_name", "event_id"],
        unique=True,
    )
    op.create_index("ix_processed_events_consumer_name", "processed_events", ["consumer_name"])
    op.create_index("ix_processed_events_event_id", "processed_events", ["event_id"])

    # --- quarantine_events ---
    op.create_table(
        "quarantine_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_event_id", sa.String(128), nullable=True),
        sa.Column("event_type", sa.String(96), nullable=True),
        sa.Column("consumer_name", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUARANTINED"),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quarantine_events_source_event_id", "quarantine_events", ["source_event_id"])


def downgrade() -> None:
    op.drop_table("quarantine_events")
    op.drop_table("processed_events")
