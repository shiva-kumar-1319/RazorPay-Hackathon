# RecoverX Security, Architecture & Compliance Disclosure

This document provides a transparent, factual disclosure of the security architecture, compliance boundaries, and data protection practices of RecoverX.

---

## 1. Compliance Architecture & Boundaries

> [!IMPORTANT]
> **Prototype / Simulation Disclosure**:
> RecoverX is built for the **Razorpay AI Buildathon 2026** as an autonomous recovery agent prototype.
> - RecoverX is **designed to align with** the principles of PCI-DSS v4.0 and RBI Payment Aggregator Guidelines.
> - RecoverX is **NOT** a certified PCI-DSS Level 1 Service Provider and does **NOT** hold formal regulatory certification.
> - In production payment systems, PAN/CVV handling is delegated exclusively to certified card vaults and payment aggregators (e.g., Razorpay / Stripe). RecoverX strictly operates on tokenized references, masked BINs, and payment gateway tokens.

---

## 2. PII Protection & Data Minimization

RecoverX enforces strict PII minimization across all agent tools, logging systems, and database models:

| Data Type | Handling Policy | Implementation |
| :--- | :--- | :--- |
| **Card Numbers (PAN)** | Never stored or ingested | Masked to `BIN + ****** + Last4` (e.g., `411111******1234`) |
| **Card Security Codes (CVV)** | Strictly prohibited | Never logged, parsed, or persisted |
| **Customer Email** | Redacted in agent tools and logs | Masked to `j***e@domain.com` |
| **Phone Numbers** | Redacted in audit and agent context | Masked to `+91 ******1234` |
| **UPI Virtual Payment Addresses (VPA)** | Partially masked in public views | Retained only for intent routing |

---

## 3. Cryptographic Audit Ledger

Every automated state transition and recovery decision is recorded with a cryptographic SHA-256 hash:
- Each event computes `hash(sequence_number, previous_hash, timestamp, actor, action, before_state, after_state, policy_version, reason_codes, metadata)`.
- The ledger is append-only and linearly linked from Genesis (Sequence 1) to Sequence N.
- Tampering with any historical audit log invalidates the hash chain downstream and is caught by `verify_audit_chain()`.

---

## 4. Authentication & Multi-Tenant Isolation

- **Merchant API Authentication**: Every protected API route requires an `X-API-Key` header.
- **Tenant Isolation**: Transactions, customer profiles, and recovery cases belong to a specific `merchant_id`. Cross-tenant execution is rejected with `403 Forbidden`.
- **Idempotency**: Execution endpoints require an `idempotency_key` or generate a unique key. Concurrent duplicate requests are rejected with `409 Conflict`, and completed operations return cached results without double billing.

---

## 5. Secrets Handling & Key Management

RecoverX strictly adheres to modern 12-factor configuration principles for all sensitive credentials:
- **Environment-Based Injection**: Zero API keys, gateway tokens, or model credentials are hardcoded in source code or tracked in version control. All configuration is loaded dynamically via `pydantic-settings` from environment variables or local `.env`.
- **Fail-Fast Validation**: The application startup sequence (`backend/app/main.py`) validates the presence and structure of required credentials for active features (`USE_LIVE_GATEWAY`, `USE_LLM_EXPLANATIONS`, and production merchant auth), immediately halting startup with explicit error diagnostics if required keys are missing.
- **Git Hygiene**: The `.env` file is strictly listed in `.gitignore` and never committed. Only `.env.example` with non-functional placeholder values is tracked in the repository.
- **Automated Regression Guard**: A dedicated test in `tests/security/test_security.py` scans all Python files in the repository to permanently prevent hardcoded credentials or API key patterns from ever being committed.
- **Production Roadmap**: While environment-based secret injection protects credentials from source leaks, automated secrets rotation, KMS envelope encryption, and HashiCorp Vault / AWS Secrets Manager integrations represent ongoing production deliverables (production TODO).

---

## 6. Network & Infrastructure Security

- **Database Isolation**: In `docker-compose.yml`, internal storage services (PostgreSQL, Redis) are isolated on an internal bridge network (`recoverx-net`) without exposed host ports.
- **CORS Protection**: Cross-Origin Resource Sharing restricts allowed origins to explicit frontend domains and forbids credentials on wildcard origins.
- **Single-Use Secure Recovery Links**: Customer recovery links utilize cryptographically secure random tokens (`secrets.token_urlsafe(32)`) and enforce a strict Time-To-Live (TTL, default 24 hours).

---

## 7. Vulnerability Disclosure

If you discover a security vulnerability, please submit a report with reproduction steps to the repository maintainers.

