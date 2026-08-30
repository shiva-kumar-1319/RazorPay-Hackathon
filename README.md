# RecoverX — AI Revenue Recovery Engine

> An explainable, safety-bounded platform for turning failed payment attempts into recovered revenue.

## Why RecoverX

Failed payments create silent revenue loss. A generic “try again” message ignores why a payment failed, what has worked for this customer before, and whether another attempt is safe or worthwhile. RecoverX is built to identify recoverable failures, choose a permitted recovery path, execute a bounded workflow, and measure recovered GMV with a complete audit trail.

**Status:** Day 10 Bounded Payment Recovery Agent complete. The platform features an autonomous, tool-calling AI agent that investigates payment failures using 6 strictly allow-listed tools, evaluates failure policy rules, obtains ML recovery predictions and Cost-Aware Expected Value rankings, validates pre-execution safety guards, and generates explainable audit traces with tailored customer and merchant narratives.

## Product story

`Failed payment → multi-gateway failure intelligence & NLP classification → customer intelligence context → outbox event → event bus → recovery orchestrator → bounded recovery agent (tool-calling loop: get_context → get_policy → score_candidates → create_plan → request_execution → write_explanation) → audit ledger → recovery & analytics APIs`

For example, when a card decline failure occurs on a ₹4,999 transaction:
1. The **Payment Recovery Agent** executes `get_transaction_context` with automatic PII masking (email and phone tokenized).
2. It calls `get_failure_policy` to confirm `PAYMENT_METHOD` permits `SWITCH_TO_UPI` and `PAYMENT_LINK` but strictly bans same-card retries.
3. It calls `score_candidates` to get ML-predicted success probabilities (68.5%) and net Expected Value (₹3,412.50) factoring in execution costs and customer friction.
4. It calls `create_recovery_plan` to formulate an approved draft plan with idempotency keys.
5. It calls `request_execution` to validate executor guards (verifying status is not `SUCCEEDED` and retry limits are respected).
6. It calls `write_explanation` to log structured customer guidance and technical root-cause logs in the immutable audit ledger.

## Who it serves

- **Merchants:** reduce failed-payment revenue loss, eliminate chargeback risks on bad cards, and monitor failure anomaly spikes.
- **Operations & Finance teams:** inspect why a decision was made, review root cause diagnostics across gateways, and inspect full audit timelines.
- **Customers:** receive frictionless, personalized recovery journeys with clear explanations of why their payment was declined.

## Current foundation

- **FastAPI Application (v0.9.0):** Modular routes (`/health`, `/api/v1/failures`, `/api/v1/customers`, `/api/v1/events`, `/api/v1/simulator`, `/api/v1/transactions`, `/api/v1/recovery`, `/api/v1/prediction`, `/api/v1/decision`, `/api/v1/agent`)
- **Bounded Tool-Calling Recovery Agent (Day 10):**
  - **6 Allow-Listed Tools:** `get_transaction_context`, `get_failure_policy`, `score_candidates`, `create_recovery_plan`, `request_execution`, `write_explanation`.
  - **Non-Negotiable Guardrails:** No free-form SQL/network tools, mandatory PII masking, deterministic policy gate priority, and double-billing executor guards.
  - **Autonomous Step Trace:** Step-by-step reasoning trace logging (`AgentStepTrace`) for auditability and compliance inspection.
- **Cost-Aware Decision Engine (Day 9):** Net Expected Value ($EV = P \times A \times e^{-\lambda t} - \text{cost} - \text{friction}$) ranking and cost model configuration.
- **Recovery Prediction Model (Day 8):** Calibrated Gradient-Boosted Classifier estimating $P(\text{success} \mid \text{action})$ with 26 engineered features.
- **Failure Intelligence & Multi-Category Classification (Day 7):** Canonical categories (`TEMPORARY`, `PAYMENT_METHOD`, `CUSTOMER_ACTION`, `HARD_FAILURE`), multi-gateway dictionaries (Razorpay, Stripe, NPCI UPI, ISO 8583), semantic NLP regex parser, and anomaly alerts.
- **Transaction & Customer Intelligence (Day 6):** Behavioral profiling (`VIP_HIGH_VALUE`, `UPI_MOBILE_PREFERRED`, etc.), instrument analytics, and point-in-time ML feature store.
- **Real-Time Event Pipeline (Day 5):** Async event bus, transactional outbox publisher, idempotent consumer, and dead-letter quarantine.
- **Payment Simulator Engine (Day 4):** Multi-gateway payment attempts, 17+ failure codes, 6 outage scenarios, and persona seeding.
- **Automated Test Suite:** **125 passing tests** with 100% test pass rate across unit, integration, and API layers.

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
Bounded Recovery Agent Loop:
  1. get_transaction_context (PII Redacted)
  2. get_failure_policy (Category Rules & Stop Flags)
  3. score_candidates (ML P(success) + Cost-Aware Net EV)
  4. create_recovery_plan (Policy Constraint Validation & Idempotency Key)
  5. request_execution (Pre-Execution Validation Guard: Status, Attempts, Policy)
  6. write_explanation (Multi-Stakeholder Customer & Merchant Audit Trail)
       ↓ (updates recovery_cases, recovery_actions, audit_logs, outbox_events)
Failure, Customer, Prediction, Decision & Recovery Agent APIs
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

### Agent & Recovery Quickstart Examples

```powershell
# 1. Discover registered allow-listed agent tools and safety guardrails
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/api/v1/agent/tools

# 2. Seed realistic customer personas (VIP, UPI-only, Card decline prone, New user)
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/simulator/seed-customers?merchant_id=merch_101

# 3. Simulate a card decline failure for one of the seeded customers
$sim = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/simulator/payments -ContentType application/json -Body '{"merchant_id":"merch_101","external_customer_id":"cust_vip_priya","amount":4999,"payment_method":"CARD","target_outcome":"FAIL","target_failure_code":"CARD_DECLINED"}'
$txnId = $sim.transaction_id

# 4. Run autonomous agent investigation on the failed transaction
$investigation = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/agent/investigate -ContentType application/json -Body (@{transaction_id=$txnId} | ConvertTo-Json)
$investigation | ConvertTo-Json -Depth 5

# 5. Inspect the agent decision traces and audit logs
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/agent/traces/$txnId"
```

## Running tests

```bash
pytest -v
```

All **125 tests** will run against an in-memory test database with full coverage of the bounded recovery agent, allow-listed tools, decision engine, prediction model, failure intelligence, customer intelligence, simulators, event bus, outbox publisher, and REST APIs.
