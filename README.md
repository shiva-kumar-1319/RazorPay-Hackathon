# RecoverX — AI Revenue Recovery Engine

> An explainable, safety-bounded platform for turning failed payment attempts into recovered revenue.

## Why RecoverX

Failed payments create silent revenue loss. A generic “try again” message ignores why a payment failed, what has worked for this customer before, and whether another attempt is safe or worthwhile. RecoverX is built to identify recoverable failures, choose a permitted recovery path, execute a bounded workflow, and measure recovered GMV with a complete audit trail.

**Status:** **Day 12 Real-Time Recovery & Revenue Analytics Dashboard complete (v0.12.0).** The platform features a live interactive operations dashboard delivering real-time failed payments streaming, autonomous AI agent decision logs, recovery execution workflow tracking, multi-stage recovery conversion funnels, ML model calibration metrics, and recovered GMV analytics.

## Product story

`Failed payment → multi-gateway failure intelligence & NLP classification → customer intelligence context → outbox event → event bus → recovery orchestrator → bounded recovery agent (get_context → get_policy → score_candidates → create_plan → request_execution → write_explanation) → recovery execution engine (retry / switch / delayed scheduler / customer recovery link) → audit ledger → real-time projection worker → interactive merchant & operations dashboard`

For example, when a card decline failure occurs on a ₹4,999 transaction:
1. The **Payment Recovery Agent** executes `get_transaction_context` with automatic PII masking (email and phone tokenized).
2. It calls `get_failure_policy` to confirm `PAYMENT_METHOD` permits `SWITCH_TO_UPI` and `PAYMENT_LINK` but strictly bans same-card retries.
3. It calls `score_candidates` to get ML-predicted success probabilities (68.5%) and net Expected Value (₹3,412.50) factoring in execution costs and customer friction.
4. It calls `create_recovery_plan` to formulate an approved draft plan with idempotency keys.
5. It calls `request_execution` to validate executor guards (verifying status is not `SUCCEEDED` and retry limits are respected).
6. The **Recovery Execution Engine** executes `SWITCH_TO_UPI`, creating a new attempt routed via UPI intent, recovering the ₹4,999 payment and updating state to `RECOVERED`.
7. It logs structured customer guidance and technical root-cause logs in the immutable audit ledger.
8. The **Dashboard Projection Service** instantly updates real-time KPIs: **+₹4,999.00 Recovered GMV**, increments the recovery rate, advances the conversion funnel, and streams the event to the live operations feed.

## Who it serves

- **Merchants:** reduce failed-payment revenue loss, eliminate chargeback risks on bad cards, and monitor recovery KPIs & GMV live.
- **Operations & Finance teams:** inspect why an AI decision was made, track the multi-stage conversion funnel, and inspect full audit timelines.
- **Customers:** receive frictionless, personalized recovery journeys with clear explanations of why their payment was declined.

## Current foundation

- **Interactive Merchant Dashboard (Day 12):**
  - **Live Web Client:** Glassmorphism UI served at `http://127.0.0.1:8000/dashboard` and `http://127.0.0.1:8000/`.
  - **Executive KPI Cards:** Failed Payments GMV, Recovered Revenue, Net Recovery Rate %, Incremental Revenue Gain, Average Recovery Turnaround, and Customer Friction Index.
  - **Multi-Stage Conversion Funnel:** 4-stage funnel ($1. \text{Total Failed} \to 2. \text{Policy Eligible} \to 3. \text{Action Dispatched} \to 4. \text{Revenue Recovered}$) with category breakdowns and instrument switch routing matrix.
  - **Live Feeds:** Real-time stream of failed payments with PII masking, agent decisions ledger, and workflow execution logs.
  - **ML Model Health:** Calibrated ROC-AUC (94.2%+), accuracy (89.5%+), Brier score, feature weights, and score distribution.
  - **Interactive Simulator:** One-click simulations for card declines, network timeouts, OTP drops, bank outages, and multi-scenario batches.
- **Recovery Execution Engine (Day 11):**
  - **4 Workflows:** Immediate Retry (`RETRY_SAME_METHOD`), Payment-Method Switch (`SWITCH_TO_UPI`, `SWITCH_TO_CARD`, `SWITCH_TO_NETBANKING`), Delayed Retry with Exponential Backoff (`DELAYED_RETRY`), and Customer Recovery Links (`CUSTOMER_NOTIFICATION`, `PAYMENT_LINK`).
  - **Pre-Execution Guards:** Double-billing prevention (blocks already-`SUCCEEDED` payments), attempt ceiling limits, and hard failure terminal stops.
  - **Scheduled Retries Processor:** Background worker and API trigger for executing due delayed retries.
  - **Customer Interactive Checkout:** Public tokenized checkout page (`GET /link/{token}`) and payment submission (`POST /link/{token}/pay`).
- **Bounded Tool-Calling Recovery Agent (Day 10):** 6 allow-listed tools (`get_transaction_context`, `get_failure_policy`, `score_candidates`, `create_recovery_plan`, `request_execution`, `write_explanation`), PII masking, and step-by-step reasoning traces.
- **Cost-Aware Decision Engine (Day 9):** Net Expected Value ($EV = P \times A \times e^{-\lambda t} - \text{cost} - \text{friction}$) ranking and cost model configuration.
- **Recovery Prediction Model (Day 8):** Calibrated Gradient-Boosted Classifier estimating $P(\text{success} \mid \text{action})$ with 26 engineered features.
- **Failure Intelligence & Multi-Category Classification (Day 7):** Canonical categories (`TEMPORARY`, `PAYMENT_METHOD`, `CUSTOMER_ACTION`, `HARD_FAILURE`), multi-gateway dictionaries (Razorpay, Stripe, NPCI UPI, ISO 8583), and semantic NLP regex parser.
- **Transaction & Customer Intelligence (Day 6):** Behavioral profiling (`VIP_HIGH_VALUE`, `UPI_MOBILE_PREFERRED`, etc.), instrument analytics, and point-in-time ML feature store.
- **Real-Time Event Pipeline (Day 5):** Async event bus, transactional outbox publisher, idempotent consumer, and dead-letter quarantine.
- **Payment Simulator Engine (Day 4):** Multi-gateway payment attempts, 17+ failure codes, 6 outage scenarios, and persona seeding.
- **Automated Test Suite:** **157 passing tests** with 100% test pass rate across unit, projection, integration, and API layers.

## Architecture

```text
Payment Ingestion / Simulator / Webhook
       ↓ (Failure Intelligence Classification & Normalization)
PostgreSQL (Customers, CustomerIntelligence, Transactions, Attempts, RecoveryCases, RecoveryActions, CustomerRecoverySessions, OutboxEvents, AuditLogs)
       ↓
Outbox Publisher Service / Worker Daemon
       ↓
Event Bus (payment.failed.v1, recovery.outcome.v1)
       ↓
Recovery Orchestrator (Idempotent Consumer + Customer Intelligence Context)
       ↓
Bounded Recovery Agent Loop (Tool-Calling Investigation & EV Scoring)
       ↓
Recovery Execution Engine:
   ├─ Immediate Retry (Same Method / Direct API)
   ├─ Payment-Method Switch (UPI / NetBanking / Card)
   ├─ Delayed Retry (Exponential Backoff + Scheduled Worker)
   └─ Customer Recovery (SMS / WhatsApp + Tokenized Payment Link)
       ↓ (State Updates, Audit Logs & Outbox Events)
Dashboard Projection Engine (backend/app/services/dashboard_service.py)
       ↓ (Overview KPIs, Funnels, Feeds, Model Health, Batch Simulations)
REST APIs (/api/v1/dashboard/*) → Interactive Web UI (http://127.0.0.1:8000/dashboard)
```

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

Open `http://127.0.0.1:8000/dashboard` to launch the **Real-Time Recovery Dashboard**.
Interactive OpenAPI docs are available at `http://127.0.0.1:8000/docs`.

### Dashboard & Analytics Quickstart Examples

```powershell
# 1. Fetch live overview KPI metrics (Failed GMV, Recovered GMV, Recovery Rate %)
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/dashboard/overview?merchant_id=merch_101"

# 2. Inspect 4-stage recovery conversion funnel & method switch routing
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/dashboard/funnel?merchant_id=merch_101"

# 3. Stream live failed payments feed with PII masking
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/dashboard/live-failed-payments?merchant_id=merch_101&limit=10"

# 4. Stream autonomous AI agent decisions ledger & reasoning traces
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/dashboard/agent-decisions?merchant_id=merch_101&limit=10"

# 5. Track recovery execution workflow attempts & switch routing
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/dashboard/recovery-attempts?merchant_id=merch_101&limit=10"

# 6. Check ML prediction model health, ROC-AUC, and feature importances
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/dashboard/model-health?merchant_id=merch_101"

# 7. Run an automated live simulation batch (6 scenarios with end-to-end recovery)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/dashboard/simulate-live-batch" -ContentType application/json -Body '{"merchant_id":"merch_101","count":6,"auto_investigate":true,"auto_execute":true}'
```

## Running tests

```bash
python -u run_tests.py
```

All **157 tests** run against an in-memory test database with full coverage of the real-time recovery dashboard, projection engine, execution workflows, bounded recovery agent, allow-listed tools, decision engine, prediction model, failure intelligence, customer intelligence, simulators, event bus, outbox publisher, and REST APIs.
