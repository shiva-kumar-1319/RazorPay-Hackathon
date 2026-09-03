# RecoverX Evaluation Methodology (`EVALUATION.md`)

This guide explains the verification framework, ground-truth mechanics, and baseline criteria used to evaluate RecoverX.

---

## 1. Evaluation Methodology

Payment recovery evaluation is notoriously difficult due to **counterfactual selection bias**: in real payment logs, we only observe what happened on the rail that was attempted, not what *would* have happened had a different action been taken.

To solve this rigorously without fabricating live data, RecoverX introduces `PaymentEnvironmentSimulator` (`benchmark/simulator.py`):
1. Each scenario pairs an **Observable Failure Event** with a **Hidden Ground Truth**.
2. Recovery strategies (No Action, Blind Retry, Heuristic, RecoverX) receive *only* the Observable Event.
3. The Simulator reveals whether the chosen action actually succeeds based on latent environment physics:
   - For an immediate retry to succeed, the failure must be transient AND the bank rail must not be currently down.
   - For a method switch to UPI to succeed, the customer must have sufficient latent balance AND latent willingness to pay.
   - For any action on a fraudulent attempt, the simulator incurs heavy penalty fees and marks a policy violation.

---

## 2. Invariant Verification

RecoverX includes 3 dedicated test suites verifying system invariants:

1. `tests/security/test_security.py`:
   - Tenant isolation (Merchant A cannot access or trigger recovery for Merchant B's transactions).
   - Non-test prevention of `force_outcome` (Returns 403 Forbidden).
   - Complete PII masking across agent context and audit trails.

2. `tests/invariants/test_invariants.py`:
   - Sequential SHA-256 hash chaining and tamper detection.
   - Double-recovery prevention invariant (`Transaction.status == SUCCEEDED`).
   - Terminal hard-stop invariant (`is_hard_stop` strictly prevents retries).
   - Idempotency key cached response return.

3. `tests/evaluation/test_benchmark_invariants.py`:
   - Seed determinism (Identical seeds produce bit-for-bit identical outputs).
   - Zero hard-stop violations invariant for RecoverX.
   - Substantial net financial revenue lift over Blind Immediate Retry.
