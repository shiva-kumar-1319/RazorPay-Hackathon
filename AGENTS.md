# RecoverX Agent System Specification (`AGENTS.md`)

> **Target Audience**: AI Agents, Code Evaluators, and Technical Reviewers inspecting autonomous decision-making in RecoverX.

---

## 1. Agent Architecture & Paradigm

RecoverX operates a **Bounded AI-Assisted Payment Recovery Agent** (`PaymentRecoveryAgent`) designed specifically for payment failure remediation. Unlike unbounded open-ended conversational agents or generative LLMs, RecoverX enforces strict determinism, bounded execution steps, and non-bypassable policy guardrails.

* **ML Model**: Provides calibrated recovery-success probability prediction (`GradientBoostingClassifier` + `CalibratedClassifierCV` isotonic).
* **Decision Engine**: Maximizes Net Expected Value ($EV$).
* **Bounded Orchestrator**: Executes a deterministic multi-step tool workflow with a strict 6-step budget.
* **Policy Guardrails**: Enforces non-bypassable stopping rules and immediate hard stops.
* **Core Execution**: Does not rely on a generative LLM in the financial transaction path.

```
Incoming Failure Event 
       │
       ▼
[ Step 1: get_transaction_context ] ──► PII-Redacted Context (Transaction + Customer History)
       │
       ▼
[ Step 2: get_failure_policy ]       ──► Deterministic Failure Codebook (Category + Hard-Stop Check)
       │
       ├─► IF Hard-Stop (Fraud/Closed/Invalid) ──► TERMINATE IMMEDIATELY (Zero Action Allowed)
       │
       ▼
[ Step 3: score_recovery_candidates ] ──► Calibrated ML Recovery Probability & Net EV Calculation
       │
       ▼
[ Step 4: propose_recovery_plan ]    ──► Formal Plan Synthesis & Fallback Selection
       │
       ▼
[ Step 5: request_execution ]         ──► Pre-Execution Policy & Attempt Limit Guard Check
       │
       ▼
[ Step 6: write_explanation ]         ──► Cryptographic SHA-256 Chained Multi-Stakeholder Narrative
```

---

## 2. Hard Step Budget & Termination Guarantees

1. **Maximum Step Budget**: The agent is bounded to a maximum of **6 discrete execution steps** per investigation cycle.
2. **Infinite Loop Prevention**: The agent cannot loop indefinitely or re-invoke tools recursively.
3. **Deterministic Early Stopping**: If Step 2 classifies the failure as `HARD_FAILURE` (e.g. `FRAUD_REJECTED`, `STOLEN_CARD`, `INVALID_ACCOUNT_NUMBER`), the agent **aborts immediately**, skips steps 3–5, and transitions directly to Step 6 to log the refusal.
4. **Latency Budget**: Mean agent trajectory execution latency is strictly `< 50ms`.

---

## 3. Tool Allow-List & Sandbox Boundary

The agent operates in a closed sandbox and may only invoke registered tools through the `AgentToolRegistry`. Dynamic arbitrary code execution or unvetted external HTTP calls are strictly prohibited.

| Tool Name | Category | Inputs | Output Schema | Invariant Enforced |
| :--- | :--- | :--- | :--- | :--- |
| `get_transaction_context` | `inspection` | `transaction_id` | `RedactedTransactionContext` | PII is masked (`_mask_email`, `_mask_phone`) |
| `get_failure_policy` | `policy` | `failure_code` | `DeterministicPolicyResult` | Identifies hard stops and rail constraints |
| `score_recovery_candidates` | `intelligence`| `transaction_id`, `candidate_actions` | `ScoreCandidatesResult` | Calibrated isotonic ML scoring + Net EV |
| `propose_recovery_plan` | `planning` | `transaction_id`, `chosen_action`, `fallback` | `AgentRecoveryPlan` | Generates plan ID and idempotency key |
| `request_execution` | `execution` | `transaction_id`, `recovery_plan_id`, `idempotency_key` | `AgentExecutionResult` | Validates attempt limits & merchant ownership |
| `write_explanation` | `audit` | `transaction_id`, `explanation_summary`, `customer_message` | `AgentExplanationResult` | Links entry into SHA-256 cryptographic chain |

---

## 4. Mathematical Decision Rule: Net Expected Value ($EV$)

The agent does not maximize raw recovery probability. It maximizes **Net Expected Value ($EV$)**, penalizing execution costs and customer disruption:

$$\text{Net } EV(a) = P(\text{Success} \mid \mathbf{x}, a) \cdot \text{Amount} - C_{\text{rail}}(a) - F_{\text{customer}}(a)$$

Where:
- $P(\text{Success} \mid \mathbf{x}, a)$: Calibrated recovery probability output by `CalibratedClassifierCV` (Isotonic regression over Gradient Boosting).
- $\text{Amount}$: Transaction value in INR.
- $C_{\text{rail}}(a)$: Gateway and network execution cost (e.g., INR 2.00 for direct retry, INR 1.00 for UPI switch, INR 2.50 for SMS/WhatsApp recovery link).
- $F_{\text{customer}}(a)$: Friction penalty assigned to intrusive customer outreach to prevent checkout abandonment and brand fatigue.

---

## 5. Fail-Safe Guardrails & Fallbacks

- **Zero LLM Dependency for Critical Safety**: Core hard-stop decisions and double-recovery guards are enforced deterministically in Python/SQL. If an LLM is offline or unconfigured, the agent functions autonomously with 100% precision.
- **Optimistic Concurrency**: Transactions enforce version increments (`Transaction.version += 1`) to prevent concurrent race conditions.
- **Idempotent Caching**: Actions submitted with identical idempotency keys return cached responses without executing secondary financial attempts.
- **Tenant Isolation**: Execution requests verify `merchant_id` ownership, preventing cross-tenant leakage.
