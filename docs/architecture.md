# Architecture

RecoverX follows a modular, event-oriented architecture so financial decisions remain explainable and bounded.

```text
Client / Dashboard
  → FastAPI API Gateway
  → Payment Service → Event Interface → Recovery Orchestrator
                                      ├─ Failure Intelligence
                                      ├─ Customer Intelligence
                                      ├─ Recovery Prediction
                                      ├─ Decision Engine
                                      ├─ Bounded Recovery Agent
                                      ├─ Recovery Execution
                                      └─ Audit Service
  → PostgreSQL / Redis / model artifacts
```

## Service boundaries

| Component | Responsibility | Status |
| --- | --- | --- |
| API gateway | Contract validation, request IDs, errors, versioned routes | Day 1 foundation |
| Payment service | Payment lifecycle and simulator integration | Planned Day 3 |
| Event interface | Publish/consume idempotent payment events | Planned Day 4 |
| Customer intelligence | Historical customer and payment-method context | Planned Day 5 |
| Failure intelligence | Classify failure and permitted next stages | Planned Day 6 |
| Prediction | Estimate `P(success | action)` | Planned Day 8 |
| Decision engine | Rank permitted actions by expected recovery value | Planned Day 9 |
| Agent | Tool-only orchestration and explanation | Planned Day 10 |
| Execution | Simulated, bounded recovery actions | Planned Day 11 |
| Audit service | Immutable decision/outcome history | Designed Day 1; implemented incrementally |

The future decision formula is `expected recovery value = probability of success × transaction amount − recovery cost`. Only actions permitted by failure policy and stopping rules may be ranked.

## Safety boundaries

- No recovery action is initiated directly by an LLM.
- `BLOCKED_CARD`, `INVALID_ACCOUNT`, and `FRAUD_REJECTED` terminate recovery.
- Attempt limits, expiry, success, customer-action requirements, low expected value, and policy disallowance stop recovery.
- All classifications, candidate actions, decisions, policy results, and outcomes are auditable.
