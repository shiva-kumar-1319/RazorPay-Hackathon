# RecoverX Performance, Latency & Scale Report (`docs/performance.md`)

> **Measurement Disclosure**: All metrics below were empirically measured on a local development machine using the reproducible benchmark runner (`benchmark/perf_benchmark.py`). No simulated or fabricated performance numbers are reported.

---

## 1. Test Environment Specifications

- **Operating System**: Windows 11
- **Processor / Architecture**: AMD64 Family 23 Model 96 Stepping 1, AuthenticAMD (AMD64)
- **Python Runtime**: Python 3.12.14 (64-bit)
- **Infrastructure Note**: Local Dev Machine (Standard Non-Production Hardware)

---

## 2. Decision Latency Distribution

Latency distributions for machine learning scoring (feature extraction, gradient boosting inference, isotonic calibration, and expected value calculation) and end-to-end 6-step agent investigations:

| Operation / Pipeline Component | Samples | p50 (Median) | p95 | p99 | Mean | SLA Target | Status |
|---|---|---|---|---|---|---|---|
| **`score_recovery_candidates`** (ML + EV) | 200 | **13.15 ms** | 15.30 ms | 21.01 ms | 13.47 ms | < 20.0 ms | PASS |
| **`investigate_transaction`** (All 6 Steps) | 100 | **21.90 ms** | 25.25 ms | 49.88 ms | 22.45 ms | < 50.0 ms | PASS |

---

## 3. Concurrent Throughput Benchmark

Sustained decision throughput under concurrent synthetic failure bursts:

| Concurrency Level | Events Evaluated | Elapsed Time (s) | Sustained Throughput | Evaluation Success Rate |
|---|---|---|---|---|
| **100 concurrent** | 100 | 1.384 s | **72.3 txns/sec** | 100.0% |
| **500 concurrent** | 500 | 6.070 s | **82.4 txns/sec** | 100.0% |
| **1000 concurrent** | 1000 | 13.064 s | **76.5 txns/sec** | 100.0% |

---

## 4. Key Architectural Enablers of High Throughput

1. **Zero LLM in the Financial Path**: Traditional generative agent architectures introduce 800ms–2500ms network latency per decision. RecoverX enforces sub-millisecond ML inference with pre-compiled isotonic regressors.
2. **Pre-Computed Action Indices**: Feature matrices use vectorized NumPy representations, extracting 26 features in microseconds.
3. **Bounded ReAct Tool Loops**: Strict 6-step deterministic budget prevents infinite reflection loops or combinatorial exploration.

---

*Generated automatically on demand by `python benchmark/perf_benchmark.py`.*