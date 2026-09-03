# RecoverX Architecture Specification (`ARCHITECTURE.md`)

RecoverX is structured as a resilient, modular, and audit-compliant payment recovery system.

```
                                    RECOVERX ARCHITECTURE
                                    
 [Payment Ingestion] ──► [Failure Classification] ──► [Bounded ReAct Agent]
        │                         │                           │
        ▼                         ▼                           ▼
 [Telemetry Buffer]      [Policy Rules Engine]       [Calibrated ML Model]
                                                              │
                                                              ▼
 [Transactional Outbox] ◄── [Execution Engine] ◄── [Net EV Optimization]
        │                         │
        ▼                         ▼
 [Event Bus / Redis]     [Idempotency & Locks] ──► [SHA-256 Audit Chain]
```

---

## 1. Core Subsystems

### Subsystem 1: Telemetry Ingestion & PII Redaction
- Normalizes incoming failure webhooks into canonical telemetry events.
- Redacts customer PII (`_mask_email`, `_mask_phone`, `mask_card_pan`) before passing data to agents or logs.

### Subsystem 2: Deterministic Failure Policy
- Evaluates raw gateway failure codes into 4 high-level categories:
  - `HARD_FAILURE`: Permanent terminal decline (Fraud, Lost Card, Account Closed). Zero action allowed.
  - `PAYMENT_METHOD`: Rail/instrument error (Card decline, OTP timeout). Recoverable by switching payment method.
  - `TEMPORARY`: Transient network glitch or CBS maintenance. Recoverable via retry.
  - `CUSTOMER_ACTION`: User drop-off or insufficient funds. Recoverable via payment link outreach.

### Subsystem 3: Bounded ReAct Autonomous Agent
- Runs a 6-step bounded ReAct reasoning loop.
- Uses `CalibratedClassifierCV` (Isotonic regression) to predict probability of success.
- Evaluates Net Expected Value ($EV$) for candidate actions.
- Emits formal plan and execution request.

### Subsystem 4: Execution Engine & Idempotency
- Atomic state reservation via `IdempotencyRecord`.
- Double-recovery prevention guards (`txn.status == SUCCEEDED`).
- Dispatches to 4 specialized workflow handlers:
  1. Direct rail retry (`RETRY_SAME_METHOD`)
  2. Payment method switch (`SWITCH_TO_UPI`, `SWITCH_TO_CARD`, `SWITCH_TO_NETBANKING`)
  3. Exponential backoff delay scheduler (`DELAYED_RETRY`)
  4. Tokenized customer payment link (`PAYMENT_LINK`, `CUSTOMER_NOTIFICATION`)

### Subsystem 5: Cryptographic Audit Ledger
- Immutable SHA-256 chained audit logs.
- Each event includes the hash of the preceding event, ensuring sequential tamper detection.
