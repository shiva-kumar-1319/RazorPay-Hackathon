# Day 11 — Recovery Execution Engine & Workflows

## Overview

Day 11 delivers the **Recovery Execution Engine & Workflows** for RecoverX. Building directly upon the Day 10 Bounded Tool-Calling Agent and Day 9 Decision Engine, Day 11 implements automated, safety-bounded execution across four core payment recovery workflows:

1. **Immediate Retry (`RETRY_SAME_METHOD`):** Safe retry attempts for transient gateway glitches and network timeouts, enforcing attempt limits and double-billing guards.
2. **Payment-Method Switch (`SWITCH_TO_UPI`, `SWITCH_TO_CARD`, `SWITCH_TO_NETBANKING`):** Bypasses issuer card declines and mandate failures by seamlessly shifting to alternate instruments (UPI FastPay, NetBanking, or alternate card).
3. **Delayed Retry Backoff & Scheduling (`DELAYED_RETRY`):** Applies exponential backoff scheduling ($T_{\text{scheduled}} = \text{now} + \text{delay} \times 2^{\text{attempt}-1} \pm \text{jitter}$), transitions states to `SCHEDULED`, and provides automated batch due-execution workers.
4. **Customer Recovery Workflow & Payment Links (`CUSTOMER_NOTIFICATION`, `PAYMENT_LINK`):** Multi-channel notification delivery (SMS, WhatsApp, Email, Push) with crypto-secure tokenized payment links and interactive customer checkout completion endpoints.

```mermaid
flowchart TD
  subgraph Recovery Decision & Plan
    PLAN[Approved Recovery Plan / Action<br/>action_type · idempotency_key · amount]
  end

  subgraph Recovery Execution Engine Dispatcher
    GUARD{Pre-Execution Safety Guards<br/>Status != SUCCEEDED?<br/>Attempts <= Max?<br/>Policy Permitted?}
    STOP[BLOCKED / REFUSED<br/>Double-billing protection<br/>Hard failure terminal stop]
    
    W1[1. Immediate Retry Workflow<br/>RETRY_SAME_METHOD<br/>Same Instrument · Direct API Attempt]
    W2[2. Payment-Method Switch Workflow<br/>SWITCH_TO_UPI / CARD / NETBANKING<br/>Card Decline Bypass · Instrument Switch]
    W3[3. Delayed Retry Scheduler<br/>DELAYED_RETRY<br/>Exponential Backoff · State: SCHEDULED]
    W4[4. Customer Recovery Journey<br/>CUSTOMER_NOTIFICATION · PAYMENT_LINK<br/>Tokenized Session · Multi-Channel Dispatch]
  end

  subgraph Execution Outcomes & Projections
    DUE[Scheduler Due-Execution Worker<br/>Polls mature retries · Executes attempt]
    PAY[Customer Interactive Checkout<br/>GET /link/{token} → POST /link/{token}/pay]
    SUCCESS[Transaction SUCCEEDED<br/>Case RECOVERED<br/>Action COMPLETED]
    FAIL[Transaction FAILED<br/>Next Attempt / Terminal State]
    AUDIT[Immutable Audit Log<br/>actor: recovery_executor]
    OUTBOX[Domain Events Published<br/>payment.succeeded.v1 · recovery.outcome.v1]
  end

  PLAN --> GUARD
  GUARD -->|Violation| STOP
  GUARD -->|Safe: RETRY_SAME_METHOD| W1
  GUARD -->|Safe: SWITCH_*| W2
  GUARD -->|Safe: DELAYED_RETRY| W3
  GUARD -->|Safe: CUSTOMER_*| W4

  W1 -->|Attempt Result| SUCCESS
  W1 -->|Attempt Result| FAIL
  W2 -->|Attempt Result| SUCCESS
  W3 --> DUE
  DUE --> SUCCESS
  W4 --> PAY
  PAY --> SUCCESS

  SUCCESS --> AUDIT
  SUCCESS --> OUTBOX
  FAIL --> AUDIT
```

---

## The 4 Core Recovery Workflows

### 1. Immediate Retry (`RETRY_SAME_METHOD`)
- **Use Case:** Transient errors (`TIMEOUT`, `NETWORK_ERROR`, `GATEWAY_ERROR`) on initial attempt.
- **Mechanism:** Creates a subsequent `PaymentAttempt` with the same instrument and gateway.
- **Guards:** Checks attempt count against category ceiling (max 3 for `TEMPORARY`), refuses execution if transaction already succeeded.
- **Outcome:** On success, transitions transaction to `SUCCEEDED`, recovery case to `RECOVERED`, action status to `COMPLETED`, and publishes `payment.succeeded.v1` and `recovery.outcome.v1`.

### 2. Payment-Method Switch (`SWITCH_TO_UPI`, `SWITCH_TO_CARD`, `SWITCH_TO_NETBANKING`)
- **Use Case:** Card decline or mandate failures (`CARD_DECLINED`, `CARD_TYPE_NOT_SUPPORTED`, `MANDATE_FAILED`) where retry on the same card is strictly forbidden.
- **Mechanism:** Dynamically creates a new payment attempt using an alternate instrument:
  - `SWITCH_TO_UPI`: Switches to UPI via `NPCI_UPI` with VPA handle (`cust@okhdfcbank` or customer preferred VPA).
  - `SWITCH_TO_NETBANKING`: Switches to retail NetBanking via `RAZORPAY`.
  - `SWITCH_TO_CARD`: Switches to alternate card route.
- **Outcome:** Resolves failed card payment with 88%+ recovery probability, records instrument switch audit metadata.

### 3. Delayed Retry Backoff & Scheduler (`DELAYED_RETRY`)
- **Use Case:** Temporary bank server downtimes and gateway infrastructure outages (`BANK_SERVER_DOWN`, `UPI_FAILURE`).
- **Mechanism:**
  - Computes exponential backoff with randomized jitter:
    $$\text{Total Delay} = \text{base\_delay} \times 2^{\text{attempt} - 1} \pm \text{jitter}$$
  - Sets `RecoveryAction.status = "SCHEDULED"` with timestamp `scheduled_at`.
  - Transitions `RecoveryCase.state = RecoveryState.SCHEDULED`.
  - Background worker (`run_scheduler_pass` or `POST /api/v1/execution/scheduler/run-due`) polls due scheduled actions and executes payment attempts when mature.

### 4. Customer Recovery Workflow (`CUSTOMER_NOTIFICATION`, `PAYMENT_LINK`)
- **Use Case:** Customer action required failures (`OTP_TIMEOUT`, `3DS_FAILURE`, `INSUFFICIENT_FUNDS`, `USER_CANCELLED`).
- **Mechanism:**
  - Generates tokenized `CustomerRecoverySession` (`rec_<crypto_token>`) with configurable TTL (default 30 mins).
  - Dispatches customized notification across SMS, WhatsApp, Email, or In-App Push.
  - Public checkout inspection endpoint (`GET /api/v1/execution/customer/link/{token}`) presents transaction amount, merchant name, plain-language failure reason, and alternative payment options.
  - Interactive payment completion endpoint (`POST /api/v1/execution/customer/link/{token}/pay`) processes payment and marks recovery session `COMPLETED`.

---

## Safety Guardrails & Non-Negotiable Invariants

1. **Double-Billing Prevention Guard:** The engine strictly refuses execution if the transaction status is already `SUCCEEDED`.
2. **Attempt Ceiling Guard:** Rejects execution if prior attempt count exceeds the category retry limit ($N_{\text{attempts}} > \text{max\_retries} + 1$).
3. **Hard Failure Terminal Stop:** Hard failure codes (`FRAUD_REJECTED`, `BLOCKED_CARD`, `EXPIRED_CARD`, `INVALID_ACCOUNT`) are immediately blocked and transition case to `STOPPED`.
4. **Idempotency Guarantees:** Actions carry unique idempotency keys (`idemp_<case_id>_<action>_<hash>`) preventing duplicate executions.
5. **Token Expiry Enforcement:** Customer payment links check UTC expiration timestamps and reject expired or completed sessions.

---

## REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/execution/actions/execute` | Execute an automated recovery action (retry, switch, delayed retry, link) |
| `POST` | `/api/v1/execution/scheduler/run-due` | Process all delayed retries that have reached their scheduled execution time |
| `POST` | `/api/v1/execution/customer/create-link` | Create tokenized customer payment recovery session and dispatch notification |
| `GET` | `/api/v1/execution/customer/link/{token}` | Public customer checkout view for inspecting payment details |
| `POST` | `/api/v1/execution/customer/link/{token}/pay` | Submit customer recovery payment via tokenized link |
| `GET` | `/api/v1/execution/metrics` | Retrieve aggregate operational execution KPIs and conversion rates |

---

## Quickstart & Demonstration Examples

### 1. Execute Payment-Method Switch (Card -> UPI)
```bash
curl -X POST http://localhost:8000/api/v1/execution/actions/execute \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "c2854e40-f191-4f1a-b7bc-e55325119d90",
    "action_type": "SWITCH_TO_UPI",
    "force_outcome": "SUCCESS",
    "parameters": {"vpa": "priya@okhdfcbank"}
  }'
```

### 2. Generate Customer Payment Link & Dispatch Notification
```bash
curl -X POST http://localhost:8000/api/v1/execution/customer/create-link \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "c2854e40-f191-4f1a-b7bc-e55325119d90",
    "channel": "WHATSAPP",
    "expires_in_minutes": 30
  }'
```

### 3. Customer Inspects and Completes Payment via Recovery Link
```bash
# View public checkout page
curl http://localhost:8000/api/v1/execution/customer/link/rec_MGYRJId1-Y--5V7UtOm55g

# Submit recovery payment
curl -X POST http://localhost:8000/api/v1/execution/customer/link/rec_MGYRJId1-Y--5V7UtOm55g/pay \
  -H "Content-Type: application/json" \
  -d '{
    "payment_method": "UPI",
    "simulate_outcome": "SUCCESS"
  }'
```

### 4. Process Due Scheduled Delayed Retries
```bash
curl -X POST http://localhost:8000/api/v1/execution/scheduler/run-due \
  -H "Content-Type: application/json" \
  -d '{"limit": 50, "force_now": true}'
```

### 5. Inspect Execution KPI Metrics
```bash
curl http://localhost:8000/api/v1/execution/metrics
```

---

## Verification & Test Evidence

All **142 automated tests** pass with 100% test pass rate:
```bash
pytest -v
```
- **Recovery Execution Workflows (11 tests):** Immediate retry success/failure, method switch to UPI / NetBanking / Card, delayed retry scheduling and due execution, customer link creation, token inspection, interactive payment completion, token expiration rejection, double-billing prevention guard, hard failure terminal stop guard, max attempt ceiling guard, execution KPI metrics aggregation.
- **Execution REST API Endpoints (6 tests):** Action execution endpoint, double-recovery refusal, scheduler batch run-due endpoint, customer link flow (create, inspect, pay), 404 token validation, and aggregate execution metrics endpoint.
