# API boundary design

The first live endpoint is intentionally small. Future endpoints retain the `/api/v1` namespace.

| Endpoint | Purpose | Planned phase |
| --- | --- | --- |
| `GET /health` | Process-level application health | Day 1 |
| `POST /api/v1/payments` | Create a simulated payment | Day 3 |
| `POST /api/v1/payments/{id}/simulate` | Simulate a payment outcome | Day 3 |
| `GET /api/v1/transactions/{id}` | Retrieve transaction and attempts | Day 3 |
| `GET /api/v1/customers/{id}/context` | Customer recovery context | Day 5 |
| `GET /api/v1/recoveries/{transaction_id}` | Explain a recovery decision and audit trail | Day 9+ |
| `GET /api/v1/metrics` | Recovery performance metrics | Day 12 |

All future write endpoints will accept an idempotency key where repeat submission could create a financial side effect. Events and API responses will carry transaction, event, correlation, and request IDs as appropriate.
