# Dashboard Architecture

The merchant dashboard reads optimized projections; it does not query or mutate the recovery command path directly.

## Views

| View | Audience | Data and purpose |
| --- | --- | --- |
| Recovery overview | Merchant owner | Failed GMV, recovered GMV, recovery rate, and trend |
| Funnel | Operations | Failed → eligible → actioned → recovered, segmented by method/category |
| Recovery queue | Operations | Active, delayed, stopped, and review-required cases |
| Transaction detail | Support | Attempts, decisions, policy reasons, and audit timeline |
| Model health | Internal admin | Score distribution, outcomes, drift, and version comparisons |

## Read model flow

```text
Domain events → projection worker → dashboard tables/materialized views → dashboard API → web client
```

The projection worker is idempotent and stores its consumer checkpoint. It exposes a `last_projected_at` value; the UI shows a freshness indicator when data is delayed.

## Query/API shape

- Scope every query by authenticated `merchant_id`.
- Use cursor pagination for transaction and audit timelines.
- Filter by UTC date range, payment method, failure category, recovery state, and action.
- Return amounts alongside currency; never aggregate currencies together without explicit conversion rules.
- Cache aggregate cards briefly, but use source-of-truth detail for a single transaction.

## Metric definitions

| Metric | Definition |
| --- | --- |
| Failed GMV | Sum of failed transaction amounts in selected period |
| Recovered GMV | Sum of transactions succeeding after a recovery action |
| Recovery rate | Recovered eligible transactions / eligible failed transactions |
| Incremental recovery | Recovered GMV versus matched no-action baseline |
| Average recovery time | Outcome timestamp minus original failure timestamp |
| Customer friction | Average attempts + customer-contact actions per case |

## Access model

Merchant roles can see only their tenant’s data. Support roles need explicit, time-bound access with all views logged. The dashboard never displays raw payment credentials, full PAN, OTPs, or unredacted provider payloads.
