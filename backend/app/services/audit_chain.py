"""Tamper-evident SHA-256 cryptographic audit chain for payment transactions."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.recovery import AuditLog


def _canonical_json(data: Any) -> str:
    """Serialize data into canonical JSON for deterministic cryptographic hashing."""
    if data is None:
        return ""
    if isinstance(data, (dict, list)):
        return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return str(data)


def compute_audit_hash(
    sequence_number: int,
    timestamp_iso: str,
    actor: str,
    action: str,
    before_state: str | None,
    after_state: str | None,
    details: dict[str, Any] | None,
    previous_hash: str,
    policy_version: str | None = None,
) -> str:
    """Compute deterministic SHA-256 hash over all tamper-evident fields."""
    canonical_details = _canonical_json(details or {})
    payload = "|".join([
        str(sequence_number),
        timestamp_iso,
        actor or "",
        action or "",
        before_state or "NONE",
        after_state or "NONE",
        canonical_details,
        policy_version or "v1.0",
        previous_hash or ("0" * 64),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_audit_event(
    session: Session,
    transaction_id: UUID,
    actor: str,
    action: str,
    before_state: str | None = None,
    after_state: str | None = None,
    details: dict[str, Any] | None = None,
    reason_codes: list[str] | None = None,
    policy_version: str | None = "v1.0",
    event_type: str = "recovery.audit.v1",
) -> AuditLog:
    """Record an audit log entry linked to the transaction's SHA-256 hash chain."""
    # Find the most recent audit log entry for this transaction
    stmt = (
        select(AuditLog)
        .where(AuditLog.transaction_id == transaction_id)
        .order_by(AuditLog.sequence_number.desc(), AuditLog.created_at.desc())
        .limit(1)
    )
    last_record = session.execute(stmt).scalars().first()

    if last_record:
        sequence_number = (last_record.sequence_number or 0) + 1
        previous_hash = last_record.event_hash or ("0" * 64)
    else:
        sequence_number = 1
        previous_hash = "0" * 64

    now_utc = datetime.now(timezone.utc)
    timestamp_iso = now_utc.isoformat()

    event_hash = compute_audit_hash(
        sequence_number=sequence_number,
        timestamp_iso=timestamp_iso,
        actor=actor,
        action=action,
        before_state=before_state,
        after_state=after_state,
        details=details,
        previous_hash=previous_hash,
        policy_version=policy_version,
    )

    audit_entry = AuditLog(
        transaction_id=transaction_id,
        event_type=event_type,
        actor=actor,
        action=action,
        before_state=before_state,
        after_state=after_state,
        policy_version=policy_version,
        sequence_number=sequence_number,
        previous_hash=previous_hash,
        event_hash=event_hash,
        reason_codes=reason_codes or [],
        metadata_={
            "timestamp_iso": timestamp_iso,
            **(details or {}),
        },
    )
    session.add(audit_entry)
    session.flush()
    return audit_entry


def verify_audit_chain(session: Session, transaction_id: UUID) -> tuple[bool, str | None]:
    """Verify that the cryptographic hash chain for a transaction is unbroken and untampered.

    Returns:
        (True, None) if the chain is valid.
        (False, error_message) if any link or hash is corrupt.
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.transaction_id == transaction_id)
        .order_by(AuditLog.sequence_number.asc())
    )
    records = list(session.execute(stmt).scalars().all())

    if not records:
        return True, None

    expected_prev = "0" * 64
    for idx, rec in enumerate(records, start=1):
        if rec.sequence_number != idx:
            return False, f"Sequence gap at index {idx}: expected {idx}, got {rec.sequence_number}"

        if rec.previous_hash != expected_prev:
            return False, f"Broken link at sequence {idx}: expected prev {expected_prev}, got {rec.previous_hash}"

        # Recompute hash
        timestamp_iso = rec.metadata_.get("timestamp_iso")
        if not timestamp_iso and rec.created_at:
            timestamp_iso = rec.created_at.isoformat()
        elif not timestamp_iso:
            timestamp_iso = ""

        # Extract details excluding the timestamp_iso helper key
        details = {k: v for k, v in (rec.metadata_ or {}).items() if k != "timestamp_iso"}

        recomputed = compute_audit_hash(
            sequence_number=rec.sequence_number,
            timestamp_iso=timestamp_iso,
            actor=rec.actor,
            action=rec.action,
            before_state=rec.before_state,
            after_state=rec.after_state,
            details=details,
            previous_hash=rec.previous_hash,
            policy_version=rec.policy_version,
        )

        if rec.event_hash and rec.event_hash != recomputed:
            return False, f"Hash mismatch at sequence {idx}: recorded {rec.event_hash}, recomputed {recomputed}"

        expected_prev = rec.event_hash

    return True, None
