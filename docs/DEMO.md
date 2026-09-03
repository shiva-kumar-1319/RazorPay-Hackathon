# RecoverX Interactive Demo Guide (`DEMO.md`)

This guide walks evaluators through running the live end-to-end interactive demo script.

---

## 1. Running the Live Demo

Execute the standalone demo script directly in the terminal:
```bash
python scripts/demo_end_to_end.py
```

---

## 2. Walkthrough of the 5 Production Scenarios

### Scenario 1: Customer 3DS OTP Drop-Off -> WhatsApp Recovery Link -> UPI Settlement
- **Trigger**: Payment attempt fails with `OTP_TIMEOUT` on a credit card.
- **Agent Action**: Recognizes user-interactive drop-off; generates a secure tokenized payment link for WhatsApp outreach.
- **Customer Action**: Customer taps link and completes payment via UPI.
- **Verification**: Transaction transitions to `SUCCEEDED`. Audit chain verified.

### Scenario 2: Transient Network Timeout -> Direct Rail Immediate Retry
- **Trigger**: Payment fails with `TIMEOUT` during a momentary gateway blip.
- **Agent Action**: Recognizes transient error; triggers seamless immediate direct retry.
- **Verification**: Recovered on attempt #2 with zero customer disruption.

### Scenario 3: Bank CBS Outage -> Exponential Backoff Delay Scheduler
- **Trigger**: Payment fails with `BANK_SERVER_DOWN`.
- **Agent Action**: Recognizes core banking downtime; schedules delayed retry with exponential backoff.
- **Verification**: Processed and recovered after bank systems restore.

### Scenario 4: Card Issuer Decline -> Autonomous Agent Investigation -> UPI Switch
- **Trigger**: Card payment declined with ISO 05 Do Not Honor (`CARD_DECLINED`).
- **Agent Action**: Bounded 6-step ReAct agent analyzes customer profile, predicts 89.9% probability for UPI switch, and executes switch.
- **Verification**: Recovered via UPI.

### Scenario 5: Fraud Risk Reject -> Strict Terminal Stop (Zero Leakage)
- **Trigger**: Payment flagged as `FRAUD_REJECTED`.
- **Agent Action**: Policy gate detects hard terminal failure; blocks execution immediately.
- **Invariant**: Strictly ZERO actions executed; zero chargeback risk incurred.
