# Database schema design

PostgreSQL is the system of record. SQLAlchemy models and migrations are scheduled for Day 2.

| Entity | Key fields | Purpose |
| --- | --- | --- |
| `customers` | external_customer_id, preferred_payment_method, totals, lifetime_value | Customer profile and aggregated context |
| `transactions` | transaction_id, customer_id, merchant_id, amount, currency, status | Payment intent / lifecycle |
| `payment_attempts` | transaction_id, method, gateway, bank, attempt_number, failure data | Every payment attempt |
| `failure_events` | transaction_id, attempt_id, code, category, severity, recoverability | Immutable failed-payment signal |
| `recovery_actions` | transaction_id, action_type, probability, expected_value, selected, outcome | Candidates and selected recovery execution |
| `audit_logs` | transaction_id, event_type, actor, decision, reason, metadata | Explainable record of every material decision |

Relationships: a customer has many transactions; a transaction has many attempts, failure events, recovery actions, and audit logs. Monetary values use fixed-precision decimal columns; timestamps are UTC; external IDs are unique and indexed. Audit metadata is stored as JSONB.
