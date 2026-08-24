# RecoverX — AI Revenue Recovery Engine

> An explainable, safety-bounded platform for turning failed payment attempts into recovered revenue.

## Why RecoverX

Failed payments create silent revenue loss. A generic “try again” message ignores why a payment failed, what has worked for this customer before, and whether another attempt is safe or worthwhile. RecoverX is being built to identify recoverable failures, choose a permitted recovery path, execute a bounded workflow, and measure recovered GMV with a complete audit trail.

**Status:** Day 3 Project Foundation complete. The platform features production-hardened infrastructure: Alembic migration pipeline, multi-stage Docker container with non-root execution and health probes, named network orchestration in Docker Compose, shared pytest fixture architecture with transactional SQLite isolation, CORS middleware, structured JSON logging, and live database health monitoring.

## Product story

`Failed payment → failure diagnosis → customer context → permitted recovery options → value-based decision → bounded execution → audit trail → recovered GMV`

For example, a ₹4,999 card payment that fails with a bank decline may be routed to UPI when the customer’s UPI history indicates a higher chance of success. A blocked card is stopped immediately rather than retried.

## Who it serves

- **Merchants:** reduce failed-payment revenue loss and understand recovery performance.
- **Operations teams:** inspect why a decision was made and what action was taken.
- **Customers:** receive fewer unhelpful retries and more relevant recovery journeys.

## Current foundation

- FastAPI application with versioned API structure (`/api/v1/events/...`)
- `/health` endpoint with active database connectivity probe
- Alembic database migration management (`001_initial_schema.py`)
- Request correlation IDs, structured JSON / text logging, and unhandled exception handling
- Configurable CORS middleware for dashboard integrations
- Multi-stage Dockerfile with unprivileged `appuser` (UID 1001) and container `HEALTHCHECK`
- Docker Compose stack with PostgreSQL, Redis, health checks, and named network (`recoverx-net`)
- SQLAlchemy payment/recovery/audit/outbox models
- Idempotent `payment.failed` ingestion with audit and transactional outbox records
- Deterministic policy gate that stops hard failures before recovery actions
- Automated testing suite with in-memory SQLite fixtures and TestClient dependency injection

## Architecture

```text
Dashboard (future)
       ↓
FastAPI API Gateway (CORS enabled)
       ↓
Payment / Event / Recovery Orchestrator (planned modules)
       ↓
Failure Intelligence + Customer Context + Decision Engine + Bounded Agent
       ↓
PostgreSQL (Alembic)     Redis     ML model (future)
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
alembic upgrade head
uvicorn backend.app.main:app --reload
```

Open `http://127.0.0.1:8000/health`. Interactive OpenAPI docs are available at `http://127.0.0.1:8000/docs`.

### Try the event pipeline

With the application running, submit a normalized failed-payment event:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/events/payment-failures -ContentType application/json -Body '{"external_transaction_id":"txn-demo-001","merchant_id":"merchant-demo","amount":4999,"payment_method":"CARD","attempt_number":1,"failure_code":"CARD_DECLINED"}'
```

The API creates source-of-truth transaction/attempt/failure/audit/outbox records in one database transaction. Re-submitting the exact same event produces an idempotent duplicate-safe `200` response.

### Docker

Run the full production-hardened stack:

```bash
docker compose up --build
```

The stack automatically launches PostgreSQL with healthchecks, applies pending Alembic migrations via `entrypoint.sh`, and starts the FastAPI service under the non-root `appuser`.

### Tests

```bash
pytest
```

## Documentation

- [Day 3 Project Foundation & Hardening](docs/day-3-project-foundation.md)
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

| Phase | Planned capability | Status |
| --- | --- | --- |
| Day 1 | API gateway foundation, health probe, logging | Complete |
| Day 2 | Domain models, event ingestion slice, policy gate | Complete |
| Day 3 | Project foundation hardening, Alembic migrations, Docker security, test suite | Complete |
| Day 4–6 | Payment simulator, events, customer context, failure intelligence | Next |
| Day 7–10 | Dataset, recovery model, deterministic decision engine, bounded agent | Planned |
| Day 11–14 | Recovery workflows, dashboard, evaluation, demo and hardening | Planned |

## License

This repository is currently provided for hackathon and portfolio evaluation.
