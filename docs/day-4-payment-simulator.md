# Day 4 — Payment Simulator & Transaction Lifecycle

## Overview

Day 4 delivers the **RecoverX Payment Simulator Engine**, establishing realistic synthetic payment traffic, complete attempt lifecycles, rich failure code taxonomies, deterministic test fixtures, and scenario-based probabilistic generation.

This simulator acts as the upstream payment provider interface, generating transactional entities (`transactions`, `payment_attempts`, `failure_events`, `audit_logs`, `outbox_events`) that feed the RecoverX recovery pipeline while maintaining strict transactional atomicity and the outbox publishing pattern.

---

## Key Deliverables

### 1. Payment Methods & Gateways
The simulator supports all standard Indian and global payment methods with realistic masked instrument metadata:
- **UPI:** Google Pay, PhonePe, Paytm, BHIM, CRED, Amazon Pay (with realistic VPA handles and remitter bank tags).
- **Cards:** Visa, Mastercard, RuPay across Credit & Debit tiers with PCI-compliant tokenized BIN references (`411111******1234`).
- **NetBanking:** Retail channels across major Indian banks (HDFC, SBI, ICICI, Axis, Kotak, PNB).
- **Wallets:** Paytm Wallet, Amazon Pay, Mobikwik.
- **BNPL:** LazyPay, Simpl, ZestMoney.
- **Aggregator Gateways:** Razorpay, PayU, Cashfree, BillDesk, Stripe, HDFC SmartHub.

---

### 2. Failure Code Taxonomy & Policy Gate

Payment failures are classified into four deterministic categories according to recovery eligibility:

| Category | Failure Code | Description | Recoverability | Default Policy Action |
| --- | --- | --- | --- | --- |
| **HARD_FAILURE** | `BLOCKED_CARD` | Card reported lost/stolen or frozen | Unrecoverable | `STOP_RECOVERY` |
| **HARD_FAILURE** | `INVALID_ACCOUNT` | Terminated or non-existent bank account/VPA | Unrecoverable | `STOP_RECOVERY` |
| **HARD_FAILURE** | `FRAUD_REJECTED` | Declined by security anomaly/risk engine | Unrecoverable | `STOP_RECOVERY` |
| **HARD_FAILURE** | `EXPIRED_CARD` | Card validity date expired | Unrecoverable | `STOP_RECOVERY` |
| **HARD_FAILURE** | `LIMIT_EXCEEDED_HARD` | Account limit exceeded for cycle | Unrecoverable | `STOP_RECOVERY` |
| **CUSTOMER_ACTION** | `OTP_TIMEOUT` | SMS/App OTP timed out or not submitted | Recoverable | `CUSTOMER_NOTIFICATION`, `PAYMENT_LINK` |
| **CUSTOMER_ACTION** | `3DS_FAILURE` | Biometric or 3DS verification failed | Recoverable | `CUSTOMER_NOTIFICATION`, `PAYMENT_LINK` |
| **CUSTOMER_ACTION** | `INSUFFICIENT_FUNDS` | Inadequate balance or credit line | Recoverable | `CUSTOMER_NOTIFICATION`, `PAYMENT_LINK` |
| **CUSTOMER_ACTION** | `INCORRECT_PIN` | Incorrect UPI PIN or ATM PIN entered | Recoverable | `CUSTOMER_NOTIFICATION`, `PAYMENT_LINK` |
| **CUSTOMER_ACTION** | `USER_CANCELLED` | Customer explicitly dismissed checkout | Recoverable | `CUSTOMER_NOTIFICATION`, `PAYMENT_LINK` |
| **TEMPORARY** | `TIMEOUT` | Gateway socket or upstream timeout | Recoverable | `DELAYED_RETRY`, `RETRY_SAME_METHOD` |
| **TEMPORARY** | `NETWORK_ERROR` | Network transmission or connection reset | Recoverable | `DELAYED_RETRY`, `RETRY_SAME_METHOD` |
| **TEMPORARY** | `UPI_FAILURE` | NPCI switch or PSP degradation | Recoverable | `DELAYED_RETRY`, `RETRY_SAME_METHOD` |
| **TEMPORARY** | `GATEWAY_ERROR` | Aggregator 5xx internal server error | Recoverable | `DELAYED_RETRY`, `RETRY_SAME_METHOD` |
| **TEMPORARY** | `BANK_SERVER_DOWN` | Core banking system maintenance | Recoverable | `DELAYED_RETRY`, `RETRY_SAME_METHOD` |
| **PAYMENT_METHOD** | `CARD_DECLINED` | Issuer decline (e-commerce disabled, etc.) | Recoverable | `SWITCH_TO_UPI`, `PAYMENT_LINK` |
| **PAYMENT_METHOD** | `CARD_TYPE_NOT_SUPPORTED` | Commercial/prepaid card tier not allowed | Recoverable | `SWITCH_TO_UPI`, `PAYMENT_LINK` |
| **PAYMENT_METHOD** | `MANDATE_FAILED` | Subscription auto-debit rejected | Recoverable | `SWITCH_TO_UPI`, `PAYMENT_LINK` |

---

### 3. Simulation Scenario Presets

1. **`NORMAL_BALANCED`**: Standard baseline (~82% success rate, balanced error distribution).
2. **`UPI_OUTAGE`**: Emulates high NPCI switch drop-offs (~45% success rate, heavy `UPI_FAILURE` and `TIMEOUT`).
3. **`CARD_AUTH_DEGRADATION`**: Emulates issuer 3DS ACS downtime (~50% success rate, heavy `3DS_FAILURE` and `OTP_TIMEOUT`).
4. **`HIGH_RISK_FRAUD_SURGE`**: Emulates fraud attack traffic (~55% success rate, heavy `FRAUD_REJECTED` and `BLOCKED_CARD`).
5. **`OTP_DROPOFF_PEAK`**: Emulates carrier SMS delivery delays (~60% success rate, heavy `OTP_TIMEOUT`).
6. **`GATEWAY_TIMEOUT_BURST`**: Emulates aggregator gateway latency bursts (~40% success rate, heavy `TIMEOUT` and `GATEWAY_ERROR`).

---

### 4. API Endpoints

#### `POST /api/v1/simulator/payments`
Creates a transaction and initial attempt with deterministic or probabilistic outcome:
```bash
curl -X POST http://localhost:8000/api/v1/simulator/payments \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 4999.00,
    "payment_method": "CARD",
    "gateway": "RAZORPAY",
    "target_outcome": "FAIL",
    "target_failure_code": "CARD_DECLINED"
  }'
```

#### `POST /api/v1/simulator/payments/{transaction_id}/attempts`
Simulates a retry or payment-method switch on an existing failed transaction:
```bash
curl -X POST http://localhost:8000/api/v1/simulator/payments/{transaction_id}/attempts \
  -H "Content-Type: application/json" \
  -d '{
    "payment_method": "UPI",
    "target_outcome": "SUCCESS"
  }'
```

#### `POST /api/v1/simulator/batch`
Generates batch simulated traffic:
```bash
curl -X POST http://localhost:8000/api/v1/simulator/batch \
  -H "Content-Type: application/json" \
  -d '{
    "count": 25,
    "scenario": "NORMAL_BALANCED"
  }'
```

#### `GET /api/v1/simulator/scenarios`
Lists all available scenarios, failure codes, payment methods, and gateways.

#### `GET /api/v1/transactions`
Paginated transaction listing with filtering by `merchant_id`, `status`, `payment_method`.

#### `GET /api/v1/transactions/{transaction_id}`
Detailed transaction view including full payment attempt timeline, failure payloads, and recovery status.

---

### 5. CLI Simulation Tool

```bash
# Simulate a single deterministic failure
python -m backend.app.simulator.cli single --amount 4999 --method CARD --failure-code CARD_DECLINED

# Simulate a batch under a specific scenario
python -m backend.app.simulator.cli batch --count 50 --scenario UPI_OUTAGE
```

---

## Verification & Test Evidence

All 18 unit and integration tests passing:
```bash
pytest -v
```
- Schema registration and entity relationships
- Deterministic success & failure flows
- Multi-attempt attempt progression (Attempt 1 Fail -> Attempt 2 Success)
- Succeeded transaction guard checks
- Batch aggregation metrics
- Transaction filtering & pagination
- Health & metadata checks
