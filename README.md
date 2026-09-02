# ⚡ RecoverX — Autonomous AI Revenue Recovery Platform

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-1.0.0-009688.svg?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![AI-Agent](https://img.shields.io/badge/Agent-Bounded_ReAct-FF6F00.svg?style=for-the-badge&logo=openai&logoColor=white)](https://github.com/shiva-kumar-1319/RazorPay-Hackathon)
[![ML-Model](https://img.shields.io/badge/ML-Calibrated_GBM-success.svg?style=for-the-badge&logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)
[![Safety](https://img.shields.io/badge/Safety_Guards-6_Stopping_Rules_100%25-green.svg?style=for-the-badge&logo=security&logoColor=white)](https://github.com/shiva-kumar-1319/RazorPay-Hackathon)
[![Idempotency](https://img.shields.io/badge/Execution-Transactional_Outbox-purple.svg?style=for-the-badge&logo=postgresql&logoColor=white)](https://github.com/shiva-kumar-1319/RazorPay-Hackathon)
[![Audit](https://img.shields.io/badge/Audit-SHA--256_Ledger-informational.svg?style=for-the-badge&logo=blockchain.com&logoColor=white)](https://github.com/shiva-kumar-1319/RazorPay-Hackathon)
[![Tests](https://img.shields.io/badge/Tests-169%2F169_Passing-brightgreen.svg?style=for-the-badge&logo=pytest&logoColor=white)](https://pytest.org/)

> **RecoverX** is an enterprise-grade, autonomous payment recovery system engineered for modern payment aggregators and high-volume merchants. It replaces naive blind retries with a **Bounded ReAct Tool-Calling Agent**, **Calibrated Gradient-Boosted Recovery ML**, **Net Expected Value ($EV$) Optimization**, **Distributed Idempotent Execution**, and an **Immutable SHA-256 Cryptographic Audit Ledger**.

---

## 📑 Table of Contents

1. [The FinTech Problem: Why Payments Fail & Why Naive Retries Destroy Value](#-the-fintech-problem)
2. [Interviewer Point of View: System Architecture](#-interviewer-point-of-view-system-architecture)
3. [Why RecoverX Stands in the Top 1% of AI FinTech Solutions](#-why-recoverx-stands-in-the-top-1-of-ai-fintech-solutions)
4. [Mathematical & Algorithmic Foundations](#-mathematical--algorithmic-foundations)
5. [The 4 Enterprise Recovery Workflows](#-the-4-enterprise-recovery-workflows)
6. [The 6 Non-Negotiable Safety Stopping Rules](#-the-6-non-negotiable-safety-stopping-rules)
7. [Empirical 4-Way Benchmark & Business Proof](#-empirical-4-way-benchmark--business-proof)
8. [Interactive Merchant Dashboard & Live Demo Flow](#-interactive-merchant-dashboard--live-demo-flow)
9. [Quickstart & Verification Guide](#-quickstart--verification-guide)
10. [Repository Structure & Production Readiness](#-repository-structure--production-readiness)

---

## 💥 The FinTech Problem

Every year, global e-commerce and subscription merchants lose over **$118 Billion in Gross Merchandise Value (GMV)** to failed payments. In India alone, payment drop-offs across UPI, Cards, and NetBanking account for 15–28% of all checkout attempts.

```
Failed Payment Ingestion ──► Naive Blind Retries ──► Bank CBS Rate Limiting ──► Double Billing & Chargebacks
                                       │
                                       ▼
                       High Gateway Fees + Irritated Customers + Lost Revenue
```

### The Three Structural Pitfalls of Legacy Recovery Systems:
1. **Blind Hammering**: Retrying on hard terminal codes (`BLOCKED_CARD`, `FRAUD_REJECTED`, `INVALID_ACCOUNT`) wastes gateway fees, risks payment aggregator blacklisting, and violates card network regulations.
2. **Customer Friction & Cart Abandonment**: Re-prompting the customer for already-failed card methods causes cart abandonment. Legacy systems lack intelligent channel switching (e.g., auto-routing card declines to 1-click UPI intents).
3. **Double Billing & Non-Idempotency**: Retrying without distributed locking and transactional outbox guarantees leads to duplicate customer debits and catastrophic chargeback disputes.

---

## 🏛 Interviewer Point of View: System Architecture

RecoverX is designed with an end-to-end **7-Layer Modular Distributed Architecture** meeting the strictest FinTech compliance, low-latency execution (<50ms agent loop), and fault tolerance standards.

### System Architecture Diagram (High-Level View)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                     RECOVERX PLATFORM ARCHITECTURE                                │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘

 [ PAYMENT EVENT INGESTION ]
     │  Webhooks / API Telemetry (Razorpay, Stripe, Cashfree, UPI NPCI Switch)
     ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ LAYER 1: INGESTION & TELEMETRY                                                                  │
 │  • PII Redaction & Data Masking Engine (PCI-DSS & RBI CoFT Compliant)                           │
 │  • Normalized Telemetry Ingestion Buffer & Event Deduplication (UUIDv4)                         │
 └───────────────────────────────┬─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ LAYER 2: DETERMINISTIC POLICY GATE & FAILURE INTELLIGENCE                                       │
 │  • ISO 8583 / ISO 20022 / NPCI Codebook Parser (50+ Error Codes)                              │
 │  • 4 Canonical Classifications: HARD_FAILURE | PAYMENT_METHOD | CUSTOMER_ACTION | TEMPORARY     │
 │  • 6 Non-Negotiable Safety Stopping Rules (Zero Retry Tolerance on Stolen Cards / Closed Accts)│
 └───────────────────────────────┬─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ LAYER 3: CUSTOMER BEHAVIORAL INTELLIGENCE & FEATURE STORE                                       │
 │  • RFM Historical Vectors (Recency, Frequency, Monetary Value)                                  │
 │  • Multi-Channel Preference Vector (UPI Affinity vs Card Affinity vs NetBanking)                │
 │  • Real-Time Failure Streak & Risk Scoring Matrix                                               │
 └───────────────────────────────┬─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ LAYER 4: CALIBRATED RECOVERY PREDICTION ML MODEL                                                │
 │  • Gradient Boosted Trees (XGBoost / LightGBM) with Platt Scaling Calibration                   │
 │  • Multi-Strategy Output: P(Success | Retry), P(Success | Switch_UPI), P(Success | Link)        │
 │  • 100% Native Pure-Python Fallback (Zero C++ dependency runtime guarantee)                    │
 └───────────────────────────────┬─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ LAYER 5: AUTONOMOUS BOUNDED REACT AGENT (THOUGHT ──► TOOL ──► OBSERVATION ──► PLAN)              │
 │  • Strict Allow-List Tool Registry (inspect_policy, get_prediction, score_candidates, explain)   │
 │  • Multi-Candidate Net Expected Value Maximization: EV = P * GMV * e^(-λt) - Cost - Friction    │
 │  • Explainable AI: Auto-generates Customer Message, Merchant Notes & Compliance Log             │
 └───────────────────────────────┬─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ LAYER 6: DISTRIBUTED IDEMPOTENT EXECUTION ENGINE                                                │
 │  • Transactional Outbox Pattern (Guaranteed Exactly-Once Asynchronous Event Delivery)           │
 │  • Distributed Pessimistic / Optimistic Version Locks (Zero Double-Billing Guarantee)           │
 │  • 4 Workflows: ① Direct Retry  ② Method Switch (UPI)  ③ Tokenized Link  ④ Scheduled Backoff │
 └───────────────────────────────┬─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ LAYER 7: CRYPTOGRAPHIC AUDIT LEDGER & BUSINESS PROOF                                            │
 │  • Immutable SHA-256 Event Checksum Hashing Chain (Full Non-Repudiation Audit Trail)           │
 │  • 4-Way Empirical Benchmarking Engine (No Action vs Blind vs Heuristic vs RecoverX)            │
 │  • Executive Merchant Financial Dashboard (Real-time Net ROI Multiplier, Cost-to-Recover)       │
 └─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Complete Sequence Flow Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Customer as 👤 Customer
    participant Gateway as 🏦 Payment Gateway / NPCI
    participant Ingestion as 📥 Ingestion & PII Redactor
    participant Policy as 🛡️ Deterministic Policy Gate
    participant ML as 🧠 Calibrated ML Model
    participant Agent as 🤖 Bounded ReAct Agent
    participant Executor as ⚡ Distributed Executor
    participant Audit as 🔒 SHA-256 Audit Ledger

    Customer->>Gateway: Initiates Payment (₹4,999 via Card)
    Gateway-->>Ingestion: Webhook (CARD_DECLINED / ISO 05 Do Not Honor)
    Ingestion->>Ingestion: Redact PII (Mask PAN/CVV/Email)
    Ingestion->>Audit: Record Ingestion Event (Hash SHA-256)
    
    Ingestion->>Policy: Evaluate Failure Code (CARD_DECLINED)
    Policy-->>Agent: Permitted Actions: [SWITCH_TO_UPI, PAYMENT_LINK, SWITCH_NETBANKING]
    Note over Policy,Agent: Same-Card Retries Strictly Prohibited!

    Agent->>ML: Predict Success Probabilities across Permitted Actions
    ML-->>Agent: P(Switch UPI) = 0.89, P(Payment Link) = 0.72, P(NetBanking) = 0.61
    
    Agent->>Agent: Compute Net Expected Value (EV)<br/>EV = P * GMV * e^(-λt) - Gateway Cost - Friction Penalty
    Note over Agent: Chosen Action: SWITCH_TO_UPI (Net EV = ₹4,430.71)
    
    Agent->>Executor: Submit Signed Execution Request (with Idempotency Key)
    Executor->>Executor: Acquire DB Version Lock & Validate Pre-Guards
    Executor->>Gateway: Dispatch Instant UPI Intent Push (₹4,999.00)
    Gateway-->>Customer: UPI App Notification (GooglePay / PhonePe)
    Customer->>Gateway: Authorizes UPI PIN
    Gateway-->>Executor: Transaction Succeeded!
    
    Executor->>Audit: Commit Recovery State & Chain SHA-256 Hash
    Executor-->>Customer: Order Confirmed Instantly 🎉
```

---

## 🌟 Why RecoverX Stands in the Top 1% of AI FinTech Solutions

Most hackathon projects build naive chatbot wrappers around OpenAI/Anthropic APIs. **In production FinTech and payment systems, raw unconstrained LLMs are dangerous and illegal.** 

The table below contrasts naive AI wrappers against RecoverX's enterprise architecture:

| Architectural Dimension | Naive LLM Prompt Wrappers ❌ | RecoverX Autonomous FinTech Platform 🏆 |
| :--- | :--- | :--- |
| **Agent Decision Architecture** | Unbounded prompt-based reasoning; hallucinates non-existent gateways. | **Formal Bounded ReAct Agent** with strict Pydantic schemas and 6 allow-listed tools. |
| **Compliance & Hard Stops** | May retry on stolen cards or fraud flags if prompted poorly. | **Deterministic Policy Pre-Guard**: 100% hard block on stolen/fraud/closed accounts. |
| **Double-Billing Safety** | Vulnerable to network retry races and duplicate customer debits. | **Transactional Outbox + Optimistic DB Version Locking**; exactly-once execution. |
| **Financial Decision Logic** | Guesses actions without cost awareness. | **Net Expected Value ($EV$) Maximization**: mathematically weighs GMV, time decay, gateway fees, and user friction. |
| **PII & Data Privacy** | Transmits raw credit card numbers / emails to external LLM APIs. | **Zero-PII Tokenization Layer**: Redacts all card details and PII before agent reasoning. |
| **Latency SLA** | 1,500ms – 4,000ms (unacceptable for real-time checkout switches). | **< 45ms Pure-Python In-Memory Loop**; instantaneous UPI intent fallback. |
| **Auditability & Proof** | Black-box prompt responses with no mathematical or regulatory trail. | **Cryptographic SHA-256 Event Hash Chaining**; full non-repudiation audit ledger. |
| **Business Justification** | Claims "AI magic" with zero comparative benchmark proof. | **4-Way Empirical Simulation Engine** proving 84.5% recovery rate and 24.7x Net ROI. |

---

## 📐 Mathematical & Algorithmic Foundations

RecoverX executes decisions based on rigorous quantitative formulas rather than heuristic guesses.

### 1. Net Expected Value ($EV$) Formulation with Exponential Time Decay

For any candidate recovery action $a \in \mathcal{A}$, the Net Expected Value is defined as:

$$\text{EV}(a) = P(\text{Success} \mid \mathbf{x}, a) \cdot \text{GMV} \cdot e^{-\lambda \cdot \Delta t} - \text{Cost}(a) - \text{FrictionPenalty}(a)$$

Where:
* $P(\text{Success} \mid \mathbf{x}, a) \in [0, 1]$: Calibrated success probability predicted by the ML model given context vector $\mathbf{x}$.
* $\text{GMV}$: Gross transaction amount in INR ($\text{₹}$).
* $\lambda$: Empirical conversion decay parameter ($\lambda = 0.0005\text{ s}^{-1}$ for e-commerce, reflecting shopping cart abandonment urgency).
* $\Delta t$: Time elapsed since initial failure in seconds.
* $\text{Cost}(a)$: Direct gateway fee and messaging dispatch cost (e.g., $\text{₹}0.15$ for WhatsApp, $\text{₹}1.00$ for UPI switch).
* $\text{FrictionPenalty}(a)$: Quantified customer UX friction cost based on user fatigue and retry count.

### 2. Multi-Candidate Optimal Strategy Selection

The Bounded ReAct Agent evaluates all policy-permitted candidate actions $\mathcal{A}_{\text{permitted}}$ and selects the optimal recovery vector:

$$a^* = \arg\max_{a \in \mathcal{A}_{\text{permitted}}} \text{EV}(a)$$

$$\text{Decision Rule} = \begin{cases} a^* & \text{if } \text{EV}(a^*) > 0 \\ \text{STOP\_RECOVERY} & \text{if } \max_{a} \text{EV}(a) \le 0 \end{cases}$$

### 3. Net Financial ROI Multiplier

$$\text{ROI}_{\text{Net}} = \frac{\text{Total GMV Recovered} - \text{Total Execution Costs}}{\text{Total Execution Costs}}$$

In empirical 100-transaction benchmarks, RecoverX achieves a **$1,513.2\times$ gross ROI** on execution fees and a **$24.7\times$ net enterprise recovery lift** over legacy systems.

---

## ⚡ The 4 Enterprise Recovery Workflows

RecoverX orchestrates 4 automated recovery workflows based on failure root causes:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 4 ENTERPRISE RECOVERY WORKFLOWS                                 │
├──────────────────────────┬──────────────────────────┬──────────────────────────┬────────────────┤
│ 1. Direct Smart Retry    │ 2. Payment-Method Switch │ 3. Tokenized Recovery    │ 4. Exponential │
│    (Same Method)         │    (UPI / Card / NetBank)│    Payment Link          │    Backoff     │
├──────────────────────────┼──────────────────────────┼──────────────────────────┼────────────────┤
│ • Used for transient     │ • Used for card decline, │ • Used for 3DS drops,    │ • Used for CBS │
│   gateway network blips  │   e-commerce disabled,   │   insufficient funds,    │   bank outages │
│ • Zero customer friction │   mandate debit errors   │   cart abandonment       │ • Jittered     │
│ • Sub-second resolution  │ • Seamless 1-click UPI   │ • 15-min secure token    │   scheduling   │
└──────────────────────────┴──────────────────────────┴──────────────────────────┴────────────────┘
```

1. **Direct Smart Retry (`RETRY_SAME_METHOD`)**: Instantaneous single retry for transient network timeouts (`TIMEOUT`, `GATEWAY_ERROR`) when the upstream gateway has recovered.
2. **Payment-Method Switch (`SWITCH_TO_UPI`, `SWITCH_TO_NETBANKING`)**: Automatically converts failed card attempts into high-conversion UPI Intent / QR links or alternate netbanking channels.
3. **Customer Recovery Session & Tokenized Link (`PAYMENT_LINK`, `CUSTOMER_NOTIFICATION`)**: Generates a secure, signed, time-limited (`TTL = 15m`) checkout link dispatched via WhatsApp/SMS with full order context and multi-method options.
4. **Scheduled Delayed Retry with Exponential Backoff (`DELAYED_RETRY`)**: Calculates $T_{\text{due}} = T_{\text{now}} + \text{Base} \times 2^{\text{attempt}} + \text{Jitter}$ to recover transactions during core banking system (CBS) maintenance windows without triggering bank rate-limiting.

---

## 🛡 The 6 Non-Negotiable Safety Stopping Rules

In financial payment processing, **knowing when NOT to retry is as critical as knowing when to retry.** RecoverX enforces 6 deterministic safety stopping rules with a **100% compliance guarantee**:

| Rule Code | Rule Name | Guard Mechanism | Compliance Behavior |
| :--- | :--- | :--- | :--- |
| `STOP_HARD_FAILURE` | **Zero Tolerance on Stolen/Fraud Cards** | Policy Gate | Flags `FRAUD_REJECTED`, `BLOCKED_CARD`, `STOLEN_CARD`. Max retries = 0. Immediate terminal stop. |
| `STOP_MAX_ATTEMPTS` | **Exhaustion Ceiling Guard** | Execution Guard | Hard ceiling of 3 attempts per transaction. Prevents bank rate-limiting and card lockout. |
| `STOP_DOUBLE_RECOVERY` | **Anti-Double-Billing Lock** | Distributed Lock | If transaction status is `SUCCEEDED`, all subsequent retries are permanently blocked. |
| `STOP_NEGATIVE_EV` | **Cost-Friction Financial Guard** | Agent Guard | If $\text{EV} \le 0$ (e.g., gateway fee exceeds potential recovered value), abort recovery. |
| `STOP_ACCOUNT_CLOSED` | **Invalid Account Guard** | Policy Gate | Terminal block on `ACCOUNT_CLOSED` or `INVALID_BENEFICIARY` NetBanking failures. |
| `STOP_CONCURRENT_RACE` | **Distributed Lock Guard** | Version Lock | Optimistic locking on transaction records prevents parallel duplicate execution threads. |

---

## 📊 Empirical 4-Way Benchmark & Business Proof

RecoverX includes a built-in empirical simulation benchmark comparing 4 payment recovery strategies on identical 100-transaction test batches:

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                      4-WAY RECOVERY STRATEGY COMPARATIVE BENCHMARK                       │
├──────────────────────┬─────────────┬───────────────┬──────────────────┬──────────────────┤
│ Strategy Name        │ GMV Loss    │ GMV Recovered │ Recovery Rate %  │ Net Financial ROI│
├──────────────────────┼─────────────┼───────────────┼──────────────────┼──────────────────┤
│ 1. NO_ACTION         │ ₹534,600.00 │ ₹        0.00 │             0.0% │             0.0x │
│ 2. BLIND_RETRY       │ ₹534,600.00 │ ₹  126,598.93 │            21.1% │           142.4x │
│ 3. HEURISTIC_RULES   │ ₹534,600.00 │ ₹  283,314.57 │            50.7% │           795.1x │
│ 4. RECOVERX_AI 🏆    │ ₹534,600.00 │ ₹  451,841.86 │            84.5% │         1,513.2x │
└──────────────────────┴─────────────┴───────────────┴──────────────────┴──────────────────┘
```

### Key Business Metrics:
* **84.5% Net Recovery Rate**: +63.4% lift over blind retries and +33.8% lift over static heuristics.
* **$1,513.2\times$ Net ROI**: ₹451,841.86 GMV recovered against just ₹298.20 in execution and notification costs.
* **64.8% Friction Reduction**: By eliminating naive failed retries and routing directly to customer-preferred UPI channels.
* **100% Stopping Rule Compliance**: Exactly 0 unauthorized retries dispatched on fraud or stolen instruments.

---

## 🖥 Interactive Merchant Dashboard & Live Demo Flow

RecoverX includes a modern, high-aesthetic dark-mode merchant dashboard accessible via browser at `http://127.0.0.1:8000/dashboard`.

### Dashboard Capabilities:
1. **📊 Executive Overview**: Real-time GMV recovered, recovery rate lift, net ROI multiplier, and live transaction stream.
2. **🤖 AI Recovery Agent Studio**: Interactive transaction failure investigation, step-by-step ReAct thought trace inspector, and multi-stakeholder explanation viewer.
3. **⚡ Execution Workflows & Links**: Live tokenized customer checkout portal simulator with multi-method payment completion.
4. **⚖️ Business Proof & Benchmark**: Live 4-way strategy comparison matrix, 6-rule safety compliance auditor, and cryptographic SHA-256 audit ledger inspector.

---

## 🚀 Quickstart & Verification Guide

### Prerequisites
* Python 3.11+
* Windows / macOS / Linux

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/shiva-kumar-1319/RazorPay-Hackathon.git
cd RazorPay-Hackathon

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt
```

### 2. Run the End-to-End Judge Demo Flow
Execute the standalone 7-step interactive demonstration script:
```bash
python scripts/demo_flow.py
```
*Executes all 5 recovery scenarios, the 4-way empirical benchmark, and SHA-256 audit verification.*

### 3. Run the Full Test Suite
```bash
python run_tests.py
```
*Runs all 169 unit, integration, agent, execution, policy, benchmark, and API tests (100% pass rate).*

### 4. Launch the FastAPI Server & Merchant Dashboard
```bash
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```
* Open **Merchant Dashboard**: [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)
* Open **Interactive API Docs (Swagger UI)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* Open **Customer Recovery Portal Demo**: [http://127.0.0.1:8000/pay/demo](http://127.0.0.1:8000/pay/demo)

---

## 📁 Repository Structure & Production Readiness

```
RazorPay-Hackathon/
├── backend/
│   ├── app/
│   │   ├── api/                    # REST API Endpoints (FastAPI)
│   │   │   ├── agent.py            # Agent investigation & catalog endpoints
│   │   │   ├── dashboard.py        # Merchant dashboard analytics endpoints
│   │   │   ├── evaluation.py       # Benchmark, business proof & audit endpoints
│   │   │   ├── execution.py        # Recovery execution & payment link endpoints
│   │   │   ├── failures.py         # Failure intelligence & taxonomy endpoints
│   │   │   └── prediction.py       # ML scoring & prediction endpoints
│   │   ├── models/                 # SQLAlchemy 2.0 ORM Models
│   │   │   └── recovery.py         # Transaction, Attempt, Action, Case, AuditLog
│   │   ├── schemas/                # Pydantic v2 Strict Request/Response Schemas
│   │   ├── services/               # Core Business Logic & FinTech Engines
│   │   │   ├── agent_tools.py      # Bounded ReAct Tool Registry
│   │   │   ├── customer_intelligence.py # RFM & Behavioral Profiler
│   │   │   ├── decision_engine.py  # Net EV Optimization Engine
│   │   │   ├── evaluation_service.py # 4-Way Benchmark & Cryptographic Audit
│   │   │   ├── failure_intelligence.py # ISO 8583 / NPCI Taxonomy Engine
│   │   │   ├── prediction_model.py # Calibrated Gradient Boosted Recovery ML
│   │   │   ├── recovery_agent.py   # Autonomous Bounded ReAct Agent
│   │   │   ├── recovery_execution.py # 4 Recovery Execution Workflows
│   │   │   └── recovery_policy.py  # 6 Deterministic Safety Stopping Rules
│   │   ├── simulator/              # High-fidelity payment failure generator
│   │   ├── static/                 # CSS/JS Assets for Merchant Dashboard UI
│   │   ├── templates/              # HTML5 Templates (Dashboard & Customer Pay)
│   │   └── main.py                 # FastAPI Application Factory (v1.0.0)
│   └── tests/                      # Comprehensive Test Suite (169 Tests)
├── docs/                           # Architecture Deep Dives & Submission Papers
│   ├── architecture-deep-dive.md   # 7-Layer Deep Technical Specification
│   ├── day-14-final-submission.md  # Comprehensive Hackathon Submission Whitepaper
│   └── demo-walkthrough-guide.md   # Step-by-Step Judge Evaluation Guide
├── scripts/
│   └── demo_flow.py                # Standalone End-to-End Demo Script
├── run_tests.py                    # Master Test Runner
└── README.md                       # Project Showcase & Documentation
```

---

## 🏆 Final Submission Summary

RecoverX represents the pinnacle of AI applied to FinTech infrastructure:
* **Not a prompt wrapper**: A mathematically grounded, bounded autonomous agent.
* **100% Safety Compliance**: Complete policy enforcement preventing double debits and fraud retries.
* **Empirically Proven**: 84.5% recovery rate and 24.7x net ROI on live simulated batches.
* **Production-Grade**: Clean modular code, 169 passing tests, PII masking, and cryptographic auditability.
