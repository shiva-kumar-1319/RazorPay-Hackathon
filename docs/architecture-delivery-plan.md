# Architecture Delivery Plan

This plan converts the Day 2 design into small, demonstrable slices. Each slice must include test coverage, audit events, and an idempotency story before the next slice starts.

| Slice | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 1 | SQLAlchemy schema + migrations | Clean database bootstraps and constraints are tested |
| 2 | Payment simulator and attempt lifecycle | A simulated failure creates transaction, attempt, event, and audit rows |
| 3 | Transactional outbox + worker | Duplicate delivery produces one recovery case/action |
| 4 | Failure policy and customer context | Hard failures stop; permitted candidate list is explainable |
| 5 | Deterministic decision baseline | Candidate ranking includes cost, value, and reason codes |
| 6 | Bounded executor | Action limits, expiry, and provider-simulator outcomes are enforced |
| 7 | Dashboard projections | Funnel/detail views match source records and show freshness |
| 8 | ML offline pipeline and shadow scoring | Reproducible metrics beat/meet baseline before live selection |

## Definition of done for every recovery action

1. Input event and output event are versioned and validated.
2. Database write and event publication are atomic through the outbox.
3. Duplicate command/event handling has an automated test.
4. An audit record captures actor, policy version, reasons, and outcome.
5. Sensitive fields are redacted in all logs and test fixtures.
6. Metrics and an operational failure path exist before enabling the action.

## Demo scenario

1. Create a ₹4,999 simulated card payment and receive `CARD_DECLINED`.
2. Ingest `payment.failed.v1`; inspect the correlation-linked audit timeline.
3. Show policy permits UPI but rejects an unsafe same-card retry.
4. Show baseline/model score, expected value, selected action, and executor guard check.
5. Simulate UPI success; dashboard recovered GMV and funnel update through projections.

This single path demonstrates eventing, state, decisioning, bounded action, explainability, and dashboard consistency end-to-end.
