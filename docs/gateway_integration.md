# Payment Gateway Integration Architecture (`docs/gateway_integration.md`)

> **Disclosure**: RecoverX supports sandboxed test-mode gateway integration. This document delineates what is real (live API calls against sandbox endpoints) versus what is simulated (stochastic outcome generation).

---

## 1. Overview & Architecture

RecoverX decouples the recovery workflow engine from specific payment rails via the `PaymentGatewayAdapter` interface (`backend/app/services/gateway_adapter.py`). This design allows instant switching between offline simulation and real sandbox payment gateways without altering decision or recovery logic.

```
                  ┌───────────────────────────────┐
                  │   recovery_execution.py       │
                  │   (Workflow Orchestration)    │
                  └───────────────┬───────────────┘
                                  │
                                  ▼
                  ┌───────────────────────────────┐
                  │    PaymentGatewayAdapter      │
                  │         (Interface)           │
                  └───────┬───────────────┬───────┘
                          │               │
            USE_LIVE_GATEWAY=false  USE_LIVE_GATEWAY=true
                          │               │
                          ▼               ▼
        ┌───────────────────┐   ┌──────────────────────────┐
        │ SimulatedGateway  │   │ RazorpayTestModeAdapter  │
        │      Adapter      │   │ (Official Sandbox API)   │
        └───────────────────┘   └──────────────────────────┘
```

---

## 2. What Is Real vs. What Is Simulated

| Component / Layer | Status | Description |
|---|---|---|
| **Razorpay API Calls** | **REAL (Sandbox)** | When `USE_LIVE_GATEWAY=true`, HTTP requests are dispatched to official endpoints: `https://api.razorpay.com/v1/orders` and `https://api.razorpay.com/v1/payment_links` using standard HTTP Basic authentication. |
| **Order & Link Generation** | **REAL (Sandbox)** | Generated IDs (`order_...`, `plink_...`) and URLs (`https://rzp.io/i/...`) are genuine Razorpay sandbox artifacts. |
| **Outcome Probabilities** | **SIMULATED** | Success/failure transitions in test mode are determined probabilistically by the recovery environment physics, because sandbox environments do not emulate downstream issuing bank network timeouts or customer behavioral conversions. |
| **Terminal Hard-Stop Checks**| **DETERMINISTIC** | Enforced at 100% precision in code before any rail call is ever dispatched. |

---

## 3. Configuration & Feature Flags

Gateway behavior is controlled via environment variables:

```ini
# Toggle between SimulatedGatewayAdapter (false) and RazorpayTestModeAdapter (true)
USE_LIVE_GATEWAY=false

# Razorpay Test Mode Credentials (obtained from dashboard.razorpay.com in Test Mode)
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
```

### Safety & Guardrails
- **Default Inactive**: `USE_LIVE_GATEWAY` is disabled (`false`) by default, ensuring offline benchmarks and CI tests run with zero external network dependencies.
- **Fail-Safe Fallback**: If `USE_LIVE_GATEWAY=true` is specified but credentials are unset, the system safely falls back to `SimulatedGatewayAdapter`.
- **Zero Production Claims**: This integration is explicitly scoped to Razorpay Test Mode / Sandbox and does not claim production PCI-DSS compliance.
