# Service Architecture

RecoverX begins as a modular monolith with independently deployable worker processes. Modules communicate through contracts and events, so high-volume paths can later be extracted without changing the product model.

| Module | Owns | Sync interface | Async interface |
| --- | --- | --- | --- |
| Ingestion API | webhook validation, idempotency admission | REST/webhook | `payment.*` |
| Payment service | transactions and attempts | payment commands | `payment.created`, `payment.attempted`, `payment.failed` |
| Recovery orchestrator | recovery lifecycle state | recovery query | consumes failed payments; emits orchestration state |
| Failure intelligence | category, severity, recoverability | classification function | `failure.classified` |
| Customer context | profile and permitted instruments | context query | profile refresh events |
| Decision engine | candidate ranking and selection | decision function | `recovery.decided` |
| Executor | retry/link/notification commands | approved action command | `recovery.executed`, `recovery.outcome` |
| Audit service | immutable business explanation | audit query | consumes all material events |
| Projection worker | dashboard read models | dashboard query | consumes all material events |

## Process layout

```text
api process       FastAPI: ingestion, queries, dashboard APIs
worker process    outbox publisher, orchestration, projections, notifications
scheduler         expiry scans, delayed retries, feature refresh, model evaluation
```

## Boundary rules

- Only the payment service creates payment attempts.
- Only the executor requests an external provider operation or sends a customer notification.
- The decision engine returns a recommendation, evidence, and policy result—not an imperative side effect.
- The audit service consumes facts; it does not decide or mutate payment state.
- Dashboard queries use projections and never block a recovery decision path.

## Scaling path

1. Run modules in one codebase with separate API and worker deployments.
2. Split the outbox publisher and projection worker first if throughput requires it.
3. Extract the executor behind its command contract only when provider integration warrants isolated credentials and release cadence.
4. Adopt a dedicated event broker when Redis Streams no longer satisfies retention, ordering, or consumer-scale requirements.
