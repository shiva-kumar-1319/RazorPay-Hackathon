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
| Payment service | Payment lifecycle and simulator integration | Day 4 complete |
| Event interface | Publish/consume idempotent payment events | Day 5 complete |
| Customer intelligence | Historical customer and payment-method context | Day 6 complete |
| Failure intelligence | Classify failure and permitted next stages | Day 7 complete |
| Prediction | Estimate `P(success \| action)` | Day 8 complete |
| Decision engine | Rank permitted actions by expected recovery value | Day 9 complete |
| Agent | Tool-only orchestration and explanation | Day 10 complete |
| Execution | Simulated, bounded recovery actions | Planned Day 11 |
| Audit service | Immutable decision/outcome history | Day 1–10 complete |

The future decision formula is `expected recovery value = probability of success × transaction amount − recovery cost`. Only actions permitted by failure policy and stopping rules may be ranked.

## Safety boundaries

- No recovery action is initiated directly by an LLM.
- `BLOCKED_CARD`, `INVALID_ACCOUNT`, and `FRAUD_REJECTED` terminate recovery.
- Attempt limits, expiry, success, customer-action requirements, low expected value, and policy disallowance stop recovery.
- All classifications, candidate actions, decisions, policy results, and outcomes are auditable.
