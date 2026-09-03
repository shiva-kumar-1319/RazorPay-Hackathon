# RecoverX 4-Way Comparative Benchmark Framework

The **RecoverX Benchmark Framework** provides an objective, adversarial, and reproducible evaluation environment for automated payment recovery systems. It evaluates 4 competing strategies on identical, grounded failure event sequences without synthetic bias or fabricated numbers.

---

## 1. Ground Truth Separation Architecture

A primary flaw in naive evaluators is "ground truth leakage," where the agent has direct access to the hidden reasons behind a payment failure. RecoverX strictly enforces two isolated layers:

```
+-------------------------------------------------------------------------+
|                  HIDDEN GROUND TRUTH (Environment Only)                 |
| - customer_willingness_to_retry: [0.0, 1.0]                             |
| - has_sufficient_balance: bool                                          |
| - has_active_alternate_instrument: bool                                 |
| - system_transient_degradation: [0.0, 1.0]                              |
| - is_terminal_fraud_or_hotlisted: bool                                  |
+-------------------------------------------------------------------------+
                                    |
                                    v (Filtered & Redacted)
+-------------------------------------------------------------------------+
|                 OBSERVABLE FAILURE EVENT (Agent / Decision)             |
| - transaction_id, external_transaction_id, amount, payment_method       |
| - failure_code, failure_category, gateway, hour_of_day                  |
| - customer_history (success_rate, risk_score, failure_streak, segment)  |
+-------------------------------------------------------------------------+
```

During evaluation:
1. The strategy receives **only** the `ObservableFailureEvent`.
2. The strategy selects an `action_type`.
3. The `PaymentEnvironmentSimulator` evaluates the chosen action against the `HiddenGroundTruth` using realistic payment rail dynamics.

---

## 2. The 4 Evaluated Strategies

| Strategy | Architecture | Policy Gate | Optimization Objective |
| :--- | :--- | :--- | :--- |
| **1. No Action** | Baseline passive drop | None | Baseline (0% recovery, 0 cost) |
| **2. Blind Immediate Retry** | Naive retry loop | None | Retries same method regardless of failure type |
| **3. Rule Heuristic** | Fixed rules | Deterministic | Static mapping (Timeout -> Retry, Decline -> UPI) |
| **4. RecoverX** | Calibrated ML + Policy Gate | Bounded ReAct | Cost-Aware Net Expected Value (EV) Maximization |

---

## 3. Evaluated Metrics

1. **Recovery Rate (%)**: Proportion of failed payment volume successfully settled.
2. **Net Revenue Recovered (INR)**: `Gross Recovered Volume - Gateway Execution Fees - Customer Friction Costs`.
3. **Hard-Stop Violation Count**: Number of actions attempted on hotlisted/fraudulent transactions. **RecoverX guarantees exactly 0**.
4. **Cost Per Recovery (INR)**: Total execution fees divided by successful recoveries.
5. **P95 Latency (ms)**: 95th percentile execution latency.

---

## 4. Reproducing the Benchmark

To execute the benchmark with a deterministic seed across 1,000 transactions:

```bash
# Standard 1,000 transaction run
python -m benchmark.run_benchmark --seed 42 --transactions 1000 --output benchmark/results/latest.json
```

### Typical Benchmark Output (Seed 42, 1,000 Transactions)

```
========================================================================================
Strategy                       | Recov %  | Recov (INR)     | Net Rev (INR)   | Violations
----------------------------------------------------------------------------------------
No Action (Zero Recovery)      |    0.00% | INR        0.00 | INR        0.00 |          0
Blind Immediate Retry          |   11.30% | INR  682,812.00 | INR  569,052.53 |         50
Rule-Based Heuristic           |   59.30% | INR 3,747,116.19 | INR 3,716,546.42 |          0
RecoverX (Cost-Aware EV Agent) |   59.30% | INR 3,779,082.18 | INR 3,757,329.78 |          0
----------------------------------------------------------------------------------------

[SUMMARY LIFT]
* RecoverX Net Revenue vs Blind Retry:     +INR 3,188,277.25
* RecoverX Net Revenue vs Rule Heuristic:  +INR 40,783.36
* RecoverX Hard-Stop Violations:           0 (Invariant: ZERO)
* Blind Retry Hard-Stop Violations:        50 (Policy Failures)
========================================================================================
```
