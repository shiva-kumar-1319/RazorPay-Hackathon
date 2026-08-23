# RecoverX — AI Revenue Recovery Engine

> An explainable, safety-bounded platform for turning failed payment attempts into recovered revenue.

## Why RecoverX

Failed payments create silent revenue loss. A generic “try again” message ignores why a payment failed, what has worked for this customer before, and whether another attempt is safe or worthwhile. RecoverX is being built to identify recoverable failures, choose a permitted recovery path, execute a bounded workflow, and measure recovered GMV with a complete audit trail.

**Status:** Day 2 system architecture complete. The project now includes the first executable vertical slice: SQLAlchemy recovery models, deterministic policy gating, idempotent failed-payment ingestion, transactional outbox records, and automated coverage for policy and duplicate events.

## Product story

`Failed payment → failure diagnosis → customer context → permitted recovery options → value-based decision → bounded execution → audit trail → recovered GMV`

For example, a ₹4,999 card payment that fails with a bank decline may be routed to UPI when the customer’s UPI history indicates a higher chance of success. A blocked card is stopped immediately rather than retried.

## Who it serves

- **Merchants:** reduce failed-payment revenue loss and understand recovery performance.
- **Operations teams:** inspect why a decision was made and what action was taken.
- **Customers:** receive fewer unhelpful retries and more relevant recovery journeys.

## Current foundation

- FastAPI application with versioned API structure
- `/health` endpoint, request IDs, structured logging, and basic error handling
- Environment-driven configuration
- Docker Compose foundation for API + PostgreSQL + Redis
- Day 2-ready module boundaries, database schema design, and API contracts
- Automated health endpoint test
- SQLAlchemy payment/recovery/audit/outbox models
- Idempotent `payment.failed` ingestion with audit and transactional outbox records
- Deterministic policy gate that stops hard failures before recovery actions

## Architecture

```text
Dashboard (future)
       ↓
FastAPI API Gateway
       ↓
Payment / Event / Recovery Orchestrator (planned modules)
       ↓
Failure Intelligence + Customer Context + Decision Engine + Bounded Agent
       ↓
PostgreSQL     Redis     ML model (future)
```

See [architecture documentation](docs/architecture.md) for ownership and extension points.

## Recovery policy reference

| Failure category | Example | Recovery posture |
| --- | --- | --- |
| Temporary | `TIMEOUT`, `NETWORK_ERROR` | Safe retry or delayed retry may be considered |
| Payment method | `CARD_DECLINED`, `UPI_FAILURE` | Consider an alternate permitted method |
| Customer action | `OTP_TIMEOUT`, `3DS_FAILURE` | Request customer action; do not blindly retry |
| Hard failure | `BLOCKED_CARD`, `FRAUD_REJECTED` | Stop recovery immediately |

Candidate actions are `RETRY_SAME_METHOD`, `SWITCH_TO_UPI`, `SWITCH_TO_CARD`, `SWITCH_TO_NETBANKING`, `DELAYED_RETRY`, `CUSTOMER_NOTIFICATION`, `PAYMENT_LINK`, and `STOP_RECOVERY`.

## Success metrics

The primary metric is **recovered GMV**. Later iterations will also measure recovery rate, incremental recovery rate versus a generic retry baseline, revenue at risk, recovery cost, average recovery time, attempts per transaction, retry reduction, customer friction, and recovery action performance.

## Quick start

Prerequisites: Python 3.11+ (or Docker).

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn backend.app.main:app --reload
```

Open `http://127.0.0.1:8000/health`. Interactive OpenAPI docs are available at `http://127.0.0.1:8000/docs`.

### Try the event pipeline

With the Docker stack running, submit a normalized failed-payment event:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/events/payment-failures -ContentType application/json -Body '{"external_transaction_id":"txn-demo-001","merchant_id":"merchant-demo","amount":4999,"payment_method":"CARD","attempt_number":1,"failure_code":"CARD_DECLINED"}'
```

The API creates source-of-truth transaction/attempt/failure/audit/outbox records in one database transaction. Include an `event_id` in the request and re-submit it to receive a duplicate-safe `200` response.

### Docker

```bash
docker compose up --build
```

The compose file provides PostgreSQL and Redis now as foundation services; application persistence and caching are deliberately introduced in Day 2 and Day 5.

### Tests

```bash
pytest
```

## Documentation

- [Day 2 system architecture blueprint](docs/day-2-system-architecture.md)
- [Event flow](docs/event-flow.md)
- [Service architecture](docs/service-architecture.md)
- [Persistence architecture](docs/persistence-architecture.md)
- [Bounded agent architecture](docs/agent-architecture.md)
- [ML architecture](docs/ml-architecture.md)
- [Dashboard architecture](docs/dashboard-architecture.md)
- [Integration contracts](docs/integration-contracts.md)
- [Reliability and security](docs/reliability-and-security.md)
- [Architecture delivery plan](docs/architecture-delivery-plan.md)
- [Foundation architecture](docs/architecture.md)
- [API boundaries](docs/api.md)
- [Database schema](docs/database.md)
- [Day 1 scope](docs/day-1-foundation.md)
- [Development guide](docs/development.md)

## Roadmap

| Phase | Planned capability |
| --- | --- |
| Day 2 | SQLAlchemy models, database initialization, migrations |
| Day 3–6 | Payment simulator, events, customer context, failure intelligence |
| Day 7–10 | Dataset, recovery model, deterministic decision engine, bounded agent |
| Day 11–14 | Recovery workflows, dashboard, evaluation, demo and hardening |

## License

This repository is currently provided for hackathon and portfolio evaluation.
