# Integration Contracts

## External webhook admission

`POST /api/v1/events/payment-provider`

The endpoint verifies provider signature, validates a versioned payload, records an idempotency key derived from provider event ID, commits the normalized event/outbox record, and returns `202 Accepted`. It does not wait for recovery processing.

Responses:

| Status | Meaning |
| --- | --- |
| `202` | New event accepted for processing |
| `200` | Duplicate event already accepted; safe acknowledgement |
| `400` | Invalid schema or unsupported event version |
| `401` | Invalid signature |
| `429` | Rate limit reached |

## Command contracts

Commands to the executor use a schema like:

```json
{
  "command_id": "uuid",
  "idempotency_key": "recovery-case/action/version",
  "transaction_id": "uuid",
  "recovery_case_id": "uuid",
  "action_type": "DELAYED_RETRY",
  "policy_version": "2026-08-23",
  "expires_at": "2026-08-23T11:00:00Z",
  "correlation_id": "uuid"
}
```

The executor rejects a command when its case version is stale, it has expired, the action is no longer permitted, an idempotency key has already succeeded, or an attempt limit is reached.

## Query contracts

- `GET /api/v1/transactions/{transaction_id}` returns current payment and recovery state, with no sensitive provider payload.
- `GET /api/v1/recoveries/{transaction_id}` returns selected action, reason codes, policy/model versions, and ordered audit facts.
- `GET /api/v1/metrics` is tenant-scoped, date-filtered, and reports definition/version metadata with aggregates.

## Versioning rules

Use `/api/v1` for HTTP contracts and `name.v1` for events. Add optional fields compatibly; publish a new version for semantic changes or breaking removal. Consumers ignore unknown fields and validate the explicit version they support. Deprecated versions retain a published sunset date and replay plan.
