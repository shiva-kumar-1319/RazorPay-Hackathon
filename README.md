# RecoverX — AI Revenue Recovery Engine

> An explainable, safety-bounded platform for turning failed payment attempts into recovered revenue.

## Why RecoverX

Failed payments create silent revenue loss. A generic “try again” message ignores why a payment failed, what has worked for this customer before, and whether another attempt is safe or worthwhile. RecoverX is built to identify recoverable failures, choose a permitted recovery path, execute a bounded workflow, and measure recovered GMV with a complete audit trail.

**Status:** Day 7 Failure Intelligence complete. The platform features deep failure categorization into four canonical classes (`TEMPORARY`, `PAYMENT_METHOD`, `CUSTOMER_ACTION`, `HARD_FAILURE`), multi-gateway error translation (Razorpay, Stripe, NPCI UPI, ISO 8583), semantic NLP regex error parsing with confidence scoring, plain-language customer and merchant diagnostics, retry limits & backoff calculation, and real-time failure anomaly detection.

## Product story

`Failed payment → multi-gateway failure intelligence & NLP classification → customer intelligence context → outbox event → event bus → recovery orchestrator → personalized candidate action ranking → audit ledger → recovery & analytics APIs`

For example, a raw bank decline response `"Issuer rejected charge: card validity expired"` is ingested. The Failure Intelligence Engine's semantic NLP parser maps it to `EXPIRED_CARD` with 98% confidence, classifies it as a **`HARD_FAILURE`**, sets max retries to 0, selects `STOP_RECOVERY`, logs compliance advisories, and provides an empathetic plain-language explanation for the customer.

## Who it serves

- **Merchants:** reduce failed-payment revenue loss, eliminate chargeback risks on bad cards, and monitor failure anomaly spikes.
- **Operations & Finance teams:** inspect why a decision was made, review root cause diagnostics across gateways, and inspect full audit timelines.
- **Customers:** receive frictionless, personalized recovery journeys with clear explanations of why their payment was declined.

## Current foundation

- **FastAPI Application (v0.6.0):** Modular routes (`/health`, `/api/v1/failures`, `/api/v1/customers`, `/api/v1/events`, `/api/v1/simulator`, `/api/v1/transactions`, `/api/v1/recovery`)
- **Failure Intelligence & Multi-Category Classification:**
  - **4 Canonical Categories:** `TEMPORARY`, `PAYMENT_METHOD`, `CUSTOMER_ACTION`, `HARD_FAILURE`.
  - **Multi-Gateway Error Translation:** Native dictionaries for Razorpay, Stripe, NPCI UPI (`U30`, `ZM`, `ZA`, `ZH`, `U69`, `U16`, `U28`), and ISO 8583 banking switch codes (`05`, `14`, `41`, `43`, `51`, `54`, `57`, `61`, `65`, `82`, `75`, `91`, `96`).
  - **Semantic NLP Diagnostics Parser:** Extracts structured failure codes and confidence scores from unstructured bank messages.
  - **Customer & Merchant Diagnostics:** Empathetic customer explanations + technical root-cause logs + regulatory compliance notes.
  - **Failure Analytics & Anomaly Detection:** Real-time telemetry, category recovery conversion, transient outage detection, and fraud surge alerts.
- **Transaction & Customer Intelligence:**
  - **Behavioral Profiling & Segmentation:** Categorizes customers into `VIP_HIGH_VALUE`, `UPI_MOBILE_PREFERRED`, `CARD_DECLINE_PRONE_RECOVERABLE`, `HIGH_FAILURE_RISK`, `NEW_CUSTOMER`.
  - **Payment Instrument Analytics:** Success rate per payment method, attempt heatmap by hour of day, retry tolerance score, channel affinity.
  - **Point-in-Time ML Feature Store:** Standardized numerical feature vector extraction.
  - **Persona Seeding Engine:** Instantly seed VIP, UPI mobile, card decline prone, and first-time buyer personas.
- **Real-Time Event Pipeline:**
  - **In-Memory & Async Event Bus:** Topic subscriptions, wildcard support, error isolation boundaries, operational metrics.
  - **Transactional Outbox Publisher:** Chronological batch publishing from `outbox_events` with atomic publication timestamps.
  - **Recovery Orchestrator:** Idempotent consumer keyed by `processed_events`, customer-aware candidate action ranking, and downstream domain event generation.
  - **Dead-Letter Quarantine:** Isolates malformed or poison events in `quarantine_events`.
- **Payment Simulator Engine:** Multi-gateway payment attempts, 17+ failure codes, 6 probabilistic outage scenarios, batch generation, customer persona seeding, and CLI tools.
- **Database & Migrations:** 11 transactional models in PostgreSQL with Alembic versioning (`001_initial_schema.py`, `002_add_processed_and_quarantine_events.py`, `003_add_customer_intelligence.py`).
- **Automated Test Suite:** 60 passing tests covering failure intelligence, gateway mapping, NLP parsing, database schema, simulators, event bus, outbox publisher, orchestrator idempotency, customer intelligence, and API endpoints.

## Architecture

```text
Payment Ingestion / Simulator / Webhook
       ↓ (Failure Intelligence Classification & Normalization)
PostgreSQL (Customers, CustomerIntelligence, Transactions, Attempts, OutboxEvents, AuditLogs)
       ↓
Outbox Publisher Service / Worker Daemon
       ↓
Event Bus (payment.failed.v1)
       ↓
Recovery Orchestrator (Idempotent Consumer + Customer Intelligence Context)
       ↓
Policy Evaluation & Personalized Candidate Action Generator
       ↓ (updates recovery_cases, recovery_actions, customer_intelligence, audit_logs)
Failure, Customer & Recovery Query APIs
```

## Failure Intelligence & Recovery Policy Reference

| Failure Category | Example Codes / Gateways | Posture & Permitted Actions | Max Retries | Backoff / Delay |
| --- | --- | --- | --- | --- |
| **`TEMPORARY`** | `TIMEOUT`, `NETWORK_ERROR`, `UPI_FAILURE`, `GATEWAY_ERROR`, `BANK_SERVER_DOWN` | Safe automated delayed retry with backoff | 3 | 45s – 120s (Exponential) |
| **`PAYMENT_METHOD`** | `CARD_DECLINED`, `CARD_TYPE_NOT_SUPPORTED`, `MANDATE_FAILED`, `ECOMMERCE_DISABLED` | Switch to alternate instrument (UPI / NetBanking) | 1 | 0s (Instant switch) |
| **`CUSTOMER_ACTION`** | `OTP_TIMEOUT`, `3DS_FAILURE`, `INSUFFICIENT_FUNDS`, `INCORRECT_PIN`, `USER_CANCELLED` | Prompt customer interaction / Send payment link | 2 | 15s – 60s (Push / SMS) |
| **`HARD_FAILURE`** | `BLOCKED_CARD`, `FRAUD_REJECTED`, `INVALID_ACCOUNT`, `EXPIRED_CARD`, `LIMIT_EXCEEDED_HARD` | Strict terminal stop (Prevents chargebacks/fraud) | 0 | 0s (Terminal) |

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

### Failure Intelligence Quickstart Examples

```powershell
# 1. Classify a raw gateway error code (e.g. Razorpay)
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/failures/classify -ContentType application/json -Body '{"gateway":"RAZORPAY","gateway_code":"BAD_REQUEST_PAYMENT_DECLINED_BY_BANK"}'

# 2. Parse an unstructured bank error with Semantic NLP
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/failures/classify -ContentType application/json -Body '{"raw_message":"Card issuer reported online usage off for this debit card"}'

# 3. Bulk classify multiple failures
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/failures/batch-classify -ContentType application/json -Body '{"items":[{"failure_code":"TIMEOUT"},{"gateway":"STRIPE","gateway_code":"insufficient_funds"},{"failure_code":"FRAUD_REJECTED"},{"raw_message":"online e-commerce disabled on card"}]}'

# 4. View full Failure Taxonomy and gateway mappings
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/api/v1/failures/taxonomy

# 5. View live Failure Analytics & Anomaly Alerts
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/api/v1/failures/analytics
```

### Seed Customer Personas & Try Customer Recovery

```powershell
# 1. Seed realistic customer personas (VIP, UPI-only, Card decline prone, New user)
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/simulator/seed-customers?merchant_id=merch_101

# 2. View customer directory with computed intelligence & lifetime spend
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/api/v1/customers?merchant_id=merch_101

# 3. Simulate a card decline failure for one of the seeded customers
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/simulator/payments -ContentType application/json -Body '{"merchant_id":"merch_101","external_customer_id":"cust_vip_priya","amount":15000,"payment_method":"CARD","target_outcome":"FAIL","target_failure_code":"CARD_DECLINED"}'

# 4. Process pending outbox events through the event pipeline
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/recovery/pipeline/process

# 5. Inspect personalized recovery case and audit logs
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/api/v1/recovery/cases
```

## Running tests

```bash
pytest -v
```

All 60 tests will run against an in-memory test database with full coverage of the failure intelligence engine, customer intelligence, simulators, event bus, outbox publisher, and recovery APIs.
