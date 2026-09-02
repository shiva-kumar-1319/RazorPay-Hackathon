# 🚀 RecoverX — Hackathon Judge Demo & Walkthrough Guide

This guide provides a comprehensive, step-by-step walkthrough for hackathon judges and evaluators to test and experience every capability of the **RecoverX AI Revenue Recovery Platform**.

---

## ⚡ Option 1: One-Click Interactive CLI Demonstration (Fastest)

To run the complete end-to-end evaluation flow covering all 5 core payment recovery scenarios, the 4-way empirical benchmark, and SHA-256 cryptographic audit verification:

```bash
# Ensure virtual environment is activated
python scripts/demo_flow.py
```

### What You Will See in the Demo Output:
1. **Scenario 1 (Network Timeout)**: Ingests a failed UPI payment (`TIMEOUT`), classifies as `TEMPORARY`, and the agent executes a successful immediate retry recovering ₹2,499.00.
2. **Scenario 2 (Card Declined)**: Ingests a failed card attempt (`CARD_DECLINED`), classifies as `PAYMENT_METHOD`, evaluates candidates, and switches method to high-conversion UPI Intent recovering ₹4,999.00.
3. **Scenario 3 (3DS Drop)**: Ingests an interrupted OTP checkout (`OTP_TIMEOUT`), generates a secure tokenized checkout link (`TTL = 15m`), and simulates instant customer checkout completion recovering ₹8,450.00.
4. **Scenario 4 (Bank Outage)**: Ingests a core banking system downtime failure (`BANK_SERVER_DOWN`), and calculates a 17s jittered exponential backoff scheduled retry.
5. **Scenario 5 (Fraud / Stolen Card)**: Ingests a stolen card transaction (`FRAUD_REJECTED`), and the policy pre-guard enforces a **100% immediate terminal stop** with 0 retries dispatched.
6. **Scenario 6 (4-Way Comparative Benchmark)**: Runs a 100-transaction simulation comparing `NO_ACTION`, `BLIND_RETRY`, `RULE_BASED_HEURISTIC`, and `RECOVERX_AI` (showing **84.5% recovery rate** and **$1,513.2\times$ ROI**).
7. **Scenario 7 (Cryptographic Audit Trail)**: Reconstructs a 9-stage chronological audit timeline for the transaction, verifying SHA-256 checksums at every step.

---

## 🖥 Option 2: Interactive Merchant Dashboard UI Walkthrough

### 1. Launch the Server
```bash
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. Navigate to Dashboard
Open your browser to: **[http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)**

### 3. Explore the 4 Dashboard Tabs:

#### Tab 1: 📊 Executive Overview
* **Top Metric Cards**: Live GMV Recovered, Net Recovery Rate (84.5%), Net ROI Multiplier (24.7x), Cost-to-Recover Ratio (3.8%), and Stopping Rules Compliance (100%).
* **Live Ingestion Feed**: Real-time stream of incoming payment failures, failure categories, and automated recovery dispositions.

#### Tab 2: 🤖 AI Recovery Agent Studio
* **Transaction Inspector**: Select any failed transaction to view its PII-redacted context.
* **Step-by-Step ReAct Trace**: Inspect the agent's internal monologue (`Thought ──► Tool Call ──► Observation ──► Plan`).
* **Multi-Stakeholder Explanations**: Review the generated customer empathetic copy, merchant business justification notes, and compliance circular citations.

#### Tab 3: ⚡ Execution Workflows & Links
* **Tokenized Link Generator**: Create hosted recovery payment links with custom expiration TTLs.
* **Interactive Customer Checkout Simulator**: Open the generated payment link in a new tab to experience the responsive customer payment sheet.

#### Tab 4: ⚖️ Business Proof & Benchmark
* **Live Batch Simulator**: Configure sample sizes (50 to 500 txns) and trigger live 4-way comparative benchmarks.
* **Strategy Comparison Matrix**: Side-by-side breakdown of recovery rate, GMV saved, execution costs, and net ROI across all 4 strategies.
* **Safety Stopping Rules Auditor**: Live verification matrix proving 0 violations across all 6 safety rules.
* **Cryptographic SHA-256 Inspector**: Inspect event-by-event hash chains for immutable non-repudiation.

---

## 🔍 Option 3: REST API Testing via Swagger UI & cURL

Open Swagger UI at **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)** to test the REST endpoints directly:

### 1. Classify a Payment Failure
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/failures/classify" \
     -H "Content-Type: application/json" \
     -d '{"failure_code": "CARD_DECLINED", "raw_message": "Card declined by issuing bank (ISO 05)"}'
```

### 2. Trigger Autonomous Agent Investigation
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/agent/investigate" \
     -H "Content-Type: application/json" \
     -d '{"transaction_id": "<TRANSACTION_UUID>", "execute_bounded_action": true}'
```

### 3. Run Comparative Evaluation Benchmark
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/evaluation/benchmark" \
     -H "Content-Type: application/json" \
     -d '{"merchant_id": "merch_101", "num_transactions": 100, "seed": 42}'
```

### 4. Fetch Cryptographic Audit Trail
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/evaluation/audit-trail/<TRANSACTION_UUID>"
```

---

## 🧪 Option 4: Full Automated Test Suite Verification

Run the master test runner to verify all 169 automated test cases:

```bash
python run_tests.py
```

**Expected Output**: `169 passed in ~4.5s (100% pass rate)`
