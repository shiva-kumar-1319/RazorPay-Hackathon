<div align="center">

# RecoverX

### AI-Powered Payment Recovery Agent

**Razorpay AI Buildathon 2026 — Track 03: AI Revenue Recovery**

![Python](https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql)
![Tests](https://img.shields.io/badge/Tests-183%20passed-success?style=flat-square)
![Audit](https://img.shields.io/badge/Evaluator%20Audit-20%2F20-success?style=flat-square)

</div>

---

## What is RecoverX?

RecoverX is a **Bounded AI-Assisted Payment Recovery Agent** that detects failed payments, predicts per-action recovery probabilities using calibrated machine learning, selects the optimal intervention via Net Expected Value optimization, enforces deterministic safety policy guardrails, executes bounded recovery workflows, and measures actual revenue recovered.

> **Zero Generative LLM in Core Financial Path**: Recovery decisions are driven by calibrated ML (`GradientBoosting` + isotonic regression) and Net Expected Value math, bound by strict deterministic policy gates. This prevents hallucinations, unbounded loops, or compliance violations on live financial transactions.

---

## Results

Benchmark evaluated on 1,000 transactions with a fixed seed — 100% reproducible and order-invariant.

| Strategy | Recovery Rate | Net Revenue Recovered | Policy Violations |
|---|---|---|---|
| No Action | 0.0% | ₹0 | 0 |
| Blind Immediate Retry | 12.2% | ₹5,93,785 | **50** |
| Rule-Based Heuristic | 59.0% | ₹37,30,049 | 0 |
| **RecoverX (Cost-Aware EV Agent)** | **58.3%** | **₹37,77,203** | **0** |

- **+₹31,83,418** net revenue vs blind retry (+536%)
- **+₹47,153** net revenue vs rule heuristic (cost-awareness advantage)
- **Zero** hard-stop policy violations — fraud and terminal failures are never retried

```bash
python -m benchmark.run_benchmark --seed 42 --transactions 1000
```

---

## Architecture

### Full System Pipeline

> Every box is a real module. Every arrow is a real data contract. The **Policy Gate** and **EV Optimizer** are what separate RecoverX from a simple retry engine.

```mermaid
flowchart TD
    FAI(["💳 Payment Failure Event\nfailure_code · amount · merchant_id · customer_id"])

    FAI -->|raw failure event| FI

    subgraph STAGE1["① CLASSIFY — failure_intelligence.py + customer_intelligence.py"]
        FI["Failure Intelligence\n─────────────────────\n50+ failure codes → category\nTEMPORARY · PAYMENT_METHOD\nCUSTOMER_ACTION · HARD_FAILURE"]
        CI[("Customer Intelligence\n─────────────────────\nsuccess_rate · recovery_rate\nrisk_score · failure_streak\nbehavioral_segment · history")]
        FI -->|failure_category| CI
    end

    CI -->|"failure_category\ncustomer_context\npermitted_actions"| PG

    subgraph STAGE2["② POLICY GATE — recovery_policy.py   ★ Critical Differentiator"]
        PG{"Is it a\nHard Failure?"}
    end

    PG -->|"FRAUD_REJECTED\nSTOLEN_CARD\nBLOCKED_CARD\nINVALID_ACCOUNT"| STOP
    STOP["🛑 HARD STOP\n────────────────────────\nZero recovery action\nAudit log only\nNo retry — ever"]

    PG -->|Recoverable| ML

    subgraph STAGE3["③ ML PREDICTION + EV RANKING — prediction_model.py + decision_engine.py"]
        ML["GradientBoostingClassifier\n+ CalibratedClassifierCV isotonic\n─────────────────────────────\n26-feature vector per candidate action\n→ P(success) for each action"]
        ML -->|"P(success) per action"| EV
        EV["Net Expected Value Engine\n──────────────────────────────────────\nEV = P × amount × time_decay\n    − execution_cost − friction_penalty\n──────────────────────────────────────\nRanks: SWITCH_TO_UPI vs PAYMENT_LINK\nvs DELAYED_RETRY vs RETRY_SAME"]
    end

    EV -->|"highest EV action\n+ idempotency_key"| AG

    subgraph STAGE4["④ BOUNDED AGENT — recovery_agent.py   Max 6 steps"]
        AG["PaymentRecoveryAgent\n──────────────────────────────────────────────────────"]
        T1["① get_transaction_context     PII-redacted context"]
        T2["② get_failure_policy          hard-stop classification"]
        T3["③ score_recovery_candidates   ML scoring + EV ranking"]
        T4["④ propose_recovery_plan       plan_id + idempotency_key"]
        T5["⑤ request_execution           ownership + attempt-limit check"]
        T6["⑥ write_explanation           append to audit chain"]
        AG --> T1 --> T2 --> T3 --> T4 --> T5 --> T6
    end

    T5 -->|"validated action\nidempotency_key"| EX

    subgraph STAGE5["⑤ IDEMPOTENT EXECUTION — recovery_execution.py"]
        EX["IdempotencyRecord check\nSHA-256 request hash\n100 duplicate requests → 1 execution"]
        EX --> E1["Retry Same Method"]
        EX --> E2["Switch → UPI / Card / NetBanking"]
        EX --> E3["Delayed Retry + Backoff Scheduler"]
        EX --> E4["Customer Payment Link\nSMS · WhatsApp · Email"]
    end

    E1 & E2 & E3 & E4 -->|"recovery outcome\nrecovered_amount"| DB

    subgraph STAGE6["⑥ PERSIST + PROVE — audit_chain.py + outbox_publisher.py"]
        DB[("PostgreSQL\n──────────────────────\nTransaction\nRecoveryCase · RecoveryAction\nIdempotencyRecord · AuditLog")]
        DB -->|"new audit entry"| CHAIN
        DB -->|"domain event"| OB
        CHAIN["SHA-256 Audit Chain\n──────────────────────────────────────────\nevent_hash = SHA256\n  seq | ts | actor | action |\n  before | after | prev_hash\n──────────────────────────────────────────\nverify_audit_chain detects any tampering"]
        OB["Transactional Outbox\n──────────────────────────────────────────\nat-least-once event delivery\nexponential backoff · quarantine on max retries"]
    end

    OB -->|"published events"| DASH
    DASH["📊 Dashboard / API\n──────────────────────────────\nLive GMV recovered · Recovery rate\nAudit trail · Benchmark metrics"]
```

---

### Why RecoverX Beats a Retry Engine

```mermaid
flowchart LR
    subgraph OTHER["❌ Blind Retry Engine"]
        O1["Payment Fails"] --> O2["Retry Everything"]
        O2 --> O3["50 Hard-Stop Violations\nper 1,000 transactions"]
        O2 --> O4["12.2% Recovery Rate"]
        O2 --> O5["Net Revenue: ₹5.9 L"]
    end

    subgraph RX["✅ RecoverX (AI-Assisted)"]
        R1["Payment Fails"] --> R2["Classify Failure"]
        R2 --> R3{"Hard Failure?"}
        R3 -->|Yes| R4["STOP — zero cost, zero risk"]
        R3 -->|No| R5["ML + EV selects\nbest action per transaction"]
        R5 --> R6["Idempotent Execute"]
        R6 --> R7["0 Violations\n58.3% Recovery Rate\nNet Revenue: ₹37.8 L"]
    end
```

---

### Agent Internals — 6-Step Bounded Execution

```mermaid
flowchart TD
    START(["investigate_transaction called"])
    START --> S1

    S1["Step 1: get_transaction_context\n→ PII-masked email · phone\n→ customer history · intelligence"]
    S1 --> S2

    S2["Step 2: get_failure_policy\n→ failure category\n→ permitted action list\n→ is_hard_stop flag"]

    S2 --> HCHECK{"is_hard_stop?"}
    HCHECK -->|YES| ABORT["Abort immediately\nSkip steps 3-5\nJump to Step 6"]
    HCHECK -->|NO| S3

    S3["Step 3: score_recovery_candidates\n→ GBM predicts P per action\n→ EV engine ranks candidates\n→ returns ordered action list"]
    S3 --> S4

    S4["Step 4: propose_recovery_plan\n→ selected action + fallback\n→ plan_id generated\n→ idempotency_key created"]
    S4 --> S5

    S5["Step 5: request_execution\n→ verify merchant ownership\n→ check attempt limits\n→ idempotency guard\n→ execute action"]
    S5 --> S6

    ABORT --> S6
    S6["Step 6: write_explanation\n→ plain-language summary\n→ appended to SHA-256 audit chain\n→ linked to previous hash"]
    S6 --> END(["AgentInvestigationResponse returned"])
```

---

### Decision Engine — Net Expected Value

RecoverX does not pick the highest-probability action. It picks the highest **Net Expected Value** action:

```
Net EV(action) = P(success) × amount × time_decay − execution_cost − friction_penalty

  time_decay    = e^(−0.01 × hours_to_recovery)
  friction_cost = 0.02 × amount × friction_score
```

**Live example — ₹4,999 card decline, FREQUENT_BUYER customer:**

```mermaid
flowchart LR
    INPUT(["CARD_DECLINED · ₹4,999 · FREQUENT_BUYER"])
    INPUT --> A & B & C

    A["SWITCH_TO_UPI\nP = 84%  Cost = ₹1.00  Friction = low\nNet EV = ₹4,183"]
    B["SWITCH_TO_NETBANKING\nP = 70%  Cost = ₹1.50  Friction = medium\nNet EV = ₹3,461"]
    C["PAYMENT_LINK\nP = 61%  Cost = ₹5.00  Friction = high\nNet EV = ₹2,994"]

    A --> WIN["✅ SELECTED\nSWITCH_TO_UPI\nHighest Net EV"]
    B --> SKIP1[" "]
    C --> SKIP2[" "]
```

---

## Benchmark Integrity & Fairness

The benchmark framework enforces strict mathematical fairness and causal integrity:

1. **Separation of Hidden Ground Truth & Observable Facts**: The agent and baseline strategies only receive `ObservableFailureEvent` (failure code, category, amount, customer history). They have zero access to `HiddenGroundTruth` (customer willingness, liquid balance, terminal fraud flags).
2. **Strategy-Fair Deterministic Outcomes**: For any `(seed, scenario_id, action)`, stochastic outcomes are deterministically derived using SHA-256 seed hashing.
3. **Execution-Order Invariance**: Strategy execution order cannot affect benchmark results. Running RecoverX before or after Blind Retry yields bit-for-bit identical results.
4. **Reproducibility**: No non-deterministic `uuid4()` calls or unseeded RNGs exist in the benchmark pipeline. Running `--seed 42` produces identical numbers every time.

---

## Project Structure

```
├── backend/app/
│   ├── api/                  # FastAPI REST endpoints
│   ├── models/               # SQLAlchemy ORM (Transaction, AuditLog, IdempotencyRecord, ...)
│   ├── schemas/              # Pydantic request/response models
│   └── services/
│       ├── failure_intelligence.py   # Failure taxonomy + classification
│       ├── customer_intelligence.py  # Customer history + risk scoring
│       ├── recovery_policy.py        # Deterministic policy gate
│       ├── prediction_model.py       # GBM + isotonic ML model
│       ├── decision_engine.py        # Net EV calculator + action ranker
│       ├── recovery_agent.py         # Bounded 6-step orchestrator
│       ├── recovery_execution.py     # Idempotent execution engine
│       ├── audit_chain.py            # SHA-256 tamper-evident ledger
│       └── outbox_publisher.py       # At-least-once event delivery
├── benchmark/
│   ├── scenarios.py          # Causal separation: HiddenGroundTruth vs ObservableFailureEvent
│   ├── simulator.py          # Payment environment (physics-based outcome resolution)
│   ├── baselines.py          # No Action, Blind Retry, Rule Heuristic, RecoverX
│   ├── metrics.py            # StrategyMetrics: recovery rate, GMV, cost, violations
│   └── run_benchmark.py      # 4-way comparative benchmark CLI
├── tests/
│   ├── evaluation/           # Benchmark invariants: seed determinism, zero hard-stop violations
│   ├── invariants/           # Double-recovery guard, audit chain integrity
│   └── security/             # PII masking, tenant isolation, auth
├── scripts/
│   ├── evaluator_check.py    # 20-point automated compliance audit
│   └── demo_end_to_end.py    # 5-scenario interactive walkthrough
├── docs/                     # Architecture docs, security disclosure
├── Dockerfile
├── docker-compose.yml
└── .github/workflows/ci.yml
```

---

## Getting Started

### Prerequisites

- Python 3.12+
- Docker Desktop (for full stack)

### Run without Docker (benchmark + tests only)

```bash
git clone https://github.com/shiva-kumar-1319/RazorPay-Hackathon
cd RazorPay-Hackathon
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

# Run automated compliance audit
python scripts/evaluator_check.py

# Run benchmark
python -m benchmark.run_benchmark --seed 42 --transactions 1000

# Run test suite
pytest tests/ -q
```

### Run full stack with Docker

```bash
docker-compose up --build
```

| Endpoint | URL |
|---|---|
| Dashboard | http://localhost:8000/dashboard |
| API Docs (Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

### Interactive Demo (5 scenarios)

```bash
python scripts/demo_end_to_end.py
```

Runs five payment failure scenarios end-to-end — classification, ML scoring, EV decision, execution, and audit chain verification:

| # | Failure | Recovery Action |
|---|---|---|
| 1 | CARD_DECLINED (₹4,999) | SWITCH_TO_UPI → recovered |
| 2 | FRAUD_REJECTED (₹28,500) | HARD STOP → zero action, audit logged |
| 3 | TIMEOUT (₹1,250) | DELAYED_RETRY → scheduled |
| 4 | INSUFFICIENT_FUNDS (₹8,000) | PAYMENT_LINK → customer pays via link |
| 5 | UPI_FAILURE (₹3,100) | DELAYED_RETRY → recovered |

---

## Verification

```bash
# Compliance audit — must exit 0
python scripts/evaluator_check.py

# Expected output:
# AUDIT SUMMARY: CRITICAL: 0 | HIGH: 0 | WARNINGS: 0
# ALL EVALUATION CHECKS PASSED SUCCESSFULLY.
```

```bash
# Test suite
pytest tests/ -q

# Expected output:
# 180 passed, 3 warnings in 19.10s
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Database | PostgreSQL + SQLAlchemy (async) |
| Cache / Events | Redis |
| ML | scikit-learn (GradientBoosting + isotonic calibration) |
| Migrations | Alembic |
| Testing | pytest + pytest-asyncio |
| Containerization | Docker + Docker Compose |
| CI | GitHub Actions |

---

## Scope and Design Decisions

- **Simulated execution**: Recovery actions execute against `PaymentEnvironmentSimulator`. No real payment gateway is connected.
- **Synthetic ML training data**: The model is trained on domain-knowledge-derived synthetic labels. It has not been validated on live payment data.
- **Demo authentication**: API keys are hardcoded for evaluation. Production deployment requires a proper secrets manager and key rotation.
- **Prototype grade**: Not PCI-DSS certified or RBI-compliant. This demonstrates the architecture, decision logic, and measurement methodology.

---

*Razorpay AI Buildathon 2026 · Track 03: AI Revenue Recovery*
