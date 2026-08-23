# Reliability, Security, and Observability

## Reliability controls

| Risk | Control |
| --- | --- |
| Duplicate provider webhook | Signed payload verification + durable idempotency record |
| Duplicate event delivery | Consumer inbox keyed by consumer/event ID |
| Executor retry storm | Per-transaction action lock, attempt caps, exponential backoff |
| Provider outage | Circuit breaker, delayed retry schedule, deterministic stop threshold |
| Partial write/publication failure | Transactional outbox with publisher retry |
| Poison event | Quarantine table, alert, reviewed replay |
| Stale recovery action | Optimistic version check and final executor policy check |

## Security boundaries

- Authenticate provider webhooks with rotation-ready signatures and replay-window validation.
- Authorize all merchant and support queries with tenant isolation at the application layer; add database row-level security if multi-tenant deployment requires defence in depth.
- Encrypt data in transit and at rest; store credentials in a secret manager, not environment files committed to Git.
- Tokenize payment instruments and redact PII before logs, events, prompts, analytics, and model training.
- Restrict provider credentials to the executor process; no dashboard, agent, or training process receives them.

## Observability

Each request, event, recovery case, and action propagates `request_id`, `correlation_id`, and `transaction_id`. Track:

- API latency/error rate, webhook signature failures, outbox backlog, consumer lag, duplicate rate, and quarantine count.
- Recovery decisions by policy result, action, model version, expected value, and outcome.
- Business metrics: eligible GMV, recovered GMV, recovery rate, action cost, friction, and time-to-recovery.

Alerts trigger on rising failure rates, outbox/consumer lag, a failure-category spike, executor refusal spikes, model-score distribution drift, or a freshness breach in dashboard projections. Audit events are retained separately from application logs.

## Recovery objectives

Initial targets are RPO near zero for committed payment/recovery records and RTO under 60 minutes for the API/worker stack. Event reprocessing and read-model rebuilds are runbook operations and must be tested before production use.
