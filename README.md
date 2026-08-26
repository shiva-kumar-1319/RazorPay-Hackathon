# RecoverX — AI Revenue Recovery Engine

> An explainable, safety-bounded platform for turning failed payment attempts into recovered revenue.

## Why RecoverX

Failed payments create silent revenue loss. A generic “try again” message ignores why a payment failed, what has worked for this customer before, and whether another attempt is safe or worthwhile. RecoverX is built to identify recoverable failures, choose a permitted recovery path, execute a bounded workflow, and measure recovered GMV with a complete audit trail.

**Status:** Day 5 Real-Time Event Pipeline & Recovery Service complete. The platform features an in-process asynchronous EventBus, transactional Outbox Publisher, idempotent Recovery Orchestrator with `processed_events` deduplication, dead-letter `quarantine_events` handling, deterministic candidate action generation, standalone worker CLI daemon, and complete recovery query APIs.

## Product story

`Failed payment → failure diagnosis → outbox event → event bus → recovery orchestrator → policy candidate generation → audit ledger → recovery APIs`

For example, a ₹4,999 card payment that fails with `CARD_DECLINED` triggers an outbox event published through the event bus. The recovery orchestrator opens a `RecoveryCase`, evaluates policy, scores and ranks `SWITCH_TO_UPI` (85% probability) as primary and `PAYMENT_LINK` (65% probability) as fallback, logs reason codes to `audit_logs`, and prevents duplicate event delivery. Hard failures like `FRAUD_REJECTED` or `BLOCKED_CARD` immediately transition to `STOPPED` with a `STOP_RECOVERY` guard.

## Who it serves

- **Merchants:** reduce failed-payment revenue loss and track recovery funnel performance in real time.
- **Operations teams:** inspect why a decision was made, what action was selected, and inspect full audit timelines.
- **Customers:** receive frictionless, context-aware recovery journeys rather than repetitive failure loops.

## Current foundation

- **FastAPI Application (v0.4.0):** Modular routes (`/health`, `/api/v1/events`, `/api/v1/simulator`, `/api/v1/transactions`, `/api/v1/recovery`)
- **Real-Time Event Pipeline:**
  - **In-Memory & Async Event Bus:** Topic subscriptions, wildcard support, error isolation boundaries, operational metrics.
  - **Transactional Outbox Publisher:** Chronological batch publishing from `outbox_events` with atomic publication timestamps.
  - **Recovery Orchestrator:** Idempotent consumer keyed by `processed_events`, deterministic candidate action ranking, and downstream domain event generation.
  - **Dead-Letter Quarantine:** Isolates malformed or poison events in `quarantine_events` with SHA-256 hash diagnostics.
- **Payment Simulator Engine:** Multi-gateway payment attempts, 17+ Indian & global failure codes, 6 probabilistic outage scenarios, batch generation, and CLI tools.
- **Database & Migrations:** 10 transactional models in PostgreSQL with Alembic versioning (`001_initial_schema.py`, `002_add_processed_and_quarantine_events.py`).
- **Container Infrastructure:** Multi-stage Dockerfile, unprivileged `appuser`, automated startup migration entrypoint, and Docker Compose with health checks.
- **Automated Test Suite:** 35 passing tests covering database schema, simulators, event bus, outbox publisher, orchestrator idempotency, and API endpoints.

## Architecture

```text
Payment Ingestion / Simulator
       ↓ (atomic database commit)
PostgreSQL (Transactions, Attempts, OutboxEvents, AuditLogs)
       ↓
Outbox Publisher Service / Worker Daemon
       ↓
Event Bus (payment.failed.v1)
       ↓
Recovery Orchestrator (Idempotent Consumer via processed_events)
       ↓
Policy Evaluation & Candidate Action Generator
       ↓ (updates recovery_cases, recovery_actions, audit_logs)
Recovery Query & Pipeline APIs
```

## Recovery policy reference

| Failure category | Example Codes | Recovery Posture | Generated Actions |
| --- | --- | --- | --- |
| **Payment method** | `CARD_DECLINED`, `CARD_TYPE_NOT_SUPPORTED`, `MANDATE_FAILED` | Switch to alternate permitted instrument | `SWITCH_TO_UPI` (Primary), `PAYMENT_LINK` |
| **Customer action** | `OTP_TIMEOUT`, `3DS_FAILURE`, `INSUFFICIENT_FUNDS`, `INCORRECT_PIN` | Prompt customer interaction | `CUSTOMER_NOTIFICATION` (Primary), `PAYMENT_LINK` |
| **Temporary** | `TIMEOUT`, `NETWORK_ERROR`, `UPI_FAILURE`, `GATEWAY_ERROR` | Exponential backoff retry | `DELAYED_RETRY` (Primary), `RETRY_SAME_METHOD` |
| **Hard failure** | `BLOCKED_CARD`, `FRAUD_REJECTED`, `INVALID_ACCOUNT`, `EXPIRED_CARD` | Stop recovery immediately | `STOP_RECOVERY` (Expected Value = 0.00) |

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

### Run the Outbox Worker CLI

```bash
# Run a single outbox publisher pass
python -m backend.app.worker --once

# Inspect pipeline metrics and backlog
python -m backend.app.worker --status

# Run continuous background worker daemon
python -m backend.app.worker --interval 2.0 --batch-size 100
```

### Try the End-to-End Recovery Pipeline

```powershell
# 1. Simulate a card decline failure
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/simulator/payments -ContentType application/json -Body '{"amount":4999,"payment_method":"CARD","gateway":"RAZORPAY","target_outcome":"FAIL","target_failure_code":"CARD_DECLINED"}'

# 2. Process pending outbox events through the event pipeline
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/recovery/pipeline/process

# 3. View the generated recovery case and ranked candidate actions
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/api/v1/recovery/cases
```

### Running Tests

```bash
pytest -v
```

## Documentation

- [Day 5 Real-Time Event Pipeline & Recovery Service](docs/day-5-real-time-event-pipeline.md)
- [Day 4 Payment Simulator & Transaction Lifecycle](docs/day-4-payment-simulator.md)
- [Day 3 Project Foundation & Hardening](docs/day-3-project-foundation.md)
- [Day 2 System Architecture Blueprint](docs/day-2-system-architecture.md)
- [Event Flow & Delivery Semantics](docs/event-flow.md)
- [Service Architecture](docs/service-architecture.md)
- [Persistence Architecture](docs/persistence-architecture.md)
- [Bounded Agent Architecture](docs/agent-architecture.md)
- [ML Architecture](docs/ml-architecture.md)
- [Dashboard Architecture](docs/dashboard-architecture.md)
- [Integration Contracts](docs/integration-contracts.md)
- [Reliability & Security](docs/reliability-and-security.md)
- [Architecture Delivery Plan](docs/architecture-delivery-plan.md)

## Roadmap

| Phase | Planned capability | Status |
| --- | --- | --- |
| Day 1 | API gateway foundation, health probe, logging | Complete |
| Day 2 | Domain models, event ingestion slice, policy gate | Complete |
| Day 3 | Project foundation hardening, Alembic migrations, Docker security, test suite | Complete |
| Day 4 | Payment simulator, realistic transaction lifecycle, failure codes, query APIs | Complete |
| Day 5 | Real-time event pipeline (failure events → outbox → event bus → recovery orchestrator) | Complete |
| Day 6–10 | Customer context, decision engine, ML shadow scoring, bounded agent | Next |
| Day 11–14 | Recovery workflows, dashboard projections, evaluation, demo and hardening | Planned |

## License

This repository is provided for hackathon evaluation and production deployment demonstration.
