"""Gemini Explanation Layer for RecoverX.

Generates human-readable, multi-stakeholder narratives (merchant summary,
customer notification, merchant diagnostic notes) for recovery decisions.

CRITICAL ARCHITECTURAL GUARANTEE:
Zero Generative LLM in Core Financial Path.
This module is STRICTLY an explanation/narration layer called downstream of all
deterministic decisions. No LLM output influences action selection, policy checks,
EV calculation, or execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "5.0"))


@dataclass
class ExplanationContext:
    transaction_id: str
    amount: float
    currency: str
    failure_code: str
    failure_category: str
    chosen_action: str
    predicted_probability: float
    net_expected_value: float
    merchant_log: str
    customer_default_message: str
    execution_disposition: str = "QUEUED"
    feature_importances: dict[str, float] | None = None


@dataclass
class ExplanationResult:
    narrative_summary: str
    customer_message: str
    merchant_notes: str
    explanation_source: str  # "llm" | "template"


def _build_deterministic_template(ctx: ExplanationContext) -> ExplanationResult:
    """Standard deterministic template explanation (default fallback)."""
    narrative_summary = (
        f"Agent selected {ctx.chosen_action} as the optimal recovery path for {ctx.failure_code} "
        f"({ctx.failure_category}). ML model predicted {ctx.predicted_probability:.1%} success rate, "
        f"yielding net Expected Value ₹{ctx.net_expected_value:.2f}. "
        f"Execution disposition: {ctx.execution_disposition}."
    )
    merchant_notes = (
        f"Root cause: {ctx.merchant_log}. Recommended {ctx.chosen_action}. "
        f"Calculated Net EV: ₹{ctx.net_expected_value:.2f} (P={ctx.predicted_probability:.1%})."
    )
    return ExplanationResult(
        narrative_summary=narrative_summary,
        customer_message=ctx.customer_default_message,
        merchant_notes=merchant_notes,
        explanation_source="template",
    )


def generate_recovery_explanation(
    ctx: ExplanationContext,
    client: httpx.Client | None = None,
) -> ExplanationResult:
    """Synthesize human-readable explanation using Gemini (if enabled) with deterministic fallback.

    Zero LLM in the core financial path: input is strictly downstream of ML scoring,
    EV ranking, and policy enforcement.
    """
    # 1. Check feature flag and API key (environment variables override settings)
    try:
        from backend.app.config import get_settings
        settings = get_settings()
        default_flag = settings.use_llm_explanations
        default_key = settings.gemini_api_key
    except Exception:
        default_flag = False
        default_key = None

    env_flag = os.getenv("USE_LLM_EXPLANATIONS")
    use_llm = (env_flag.lower() in ("true", "1", "yes")) if env_flag is not None else default_flag

    env_key = os.getenv("GEMINI_API_KEY")
    api_key = env_key if env_key is not None else default_key

    if not use_llm or not api_key:
        return _build_deterministic_template(ctx)

    # 2. Construct narrative synthesis prompt (downstream of all decisions)
    system_prompt = (
        "You are an AI financial narrator for the RecoverX payment recovery platform. "
        "The recovery decision has already been calculated deterministically by a calibrated ML model "
        "and Net Expected Value optimizer. Your sole task is narrative synthesis — translating structured "
        "decision context into clear, concise, professional text for stakeholders.\n\n"
        "Return ONLY a valid JSON object matching this exact schema:\n"
        "{\n"
        '  "narrative_summary": "1-2 sentence executive summary for merchant dashboard.",\n'
        '  "customer_message": "Clear, friendly message for customer SMS/WhatsApp without technical jargon.",\n'
        '  "merchant_notes": "Technical root-cause and rail routing rationale for operations."\n'
        "}"
    )

    decision_data = {
        "transaction_id": ctx.transaction_id,
        "amount": ctx.amount,
        "currency": ctx.currency,
        "failure_code": ctx.failure_code,
        "failure_category": ctx.failure_category,
        "chosen_action": ctx.chosen_action,
        "predicted_success_rate": f"{ctx.predicted_probability:.1%}",
        "net_expected_value": f"{ctx.currency} {ctx.net_expected_value:.2f}",
        "execution_disposition": ctx.execution_disposition,
        "technical_diagnosis": ctx.merchant_log,
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": system_prompt},
                    {"text": f"DECISION CONTEXT:\n{json.dumps(decision_data, indent=2)}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 300,
            "responseMimeType": "application/json",
        },
    }

    # 3. Call Gemini with tight 3.0s timeout and fail-open to template
    try:
        url = f"{GEMINI_API_URL}?key={api_key}"
        if client is not None:
            resp = client.post(url, json=payload, timeout=GEMINI_TIMEOUT_SECONDS)
        else:
            with httpx.Client(timeout=GEMINI_TIMEOUT_SECONDS) as http_client:
                resp = http_client.post(url, json=payload)

        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                parsed = json.loads(raw_text)
                return ExplanationResult(
                    narrative_summary=parsed.get("narrative_summary") or _build_deterministic_template(ctx).narrative_summary,
                    customer_message=parsed.get("customer_message") or ctx.customer_default_message,
                    merchant_notes=parsed.get("merchant_notes") or _build_deterministic_template(ctx).merchant_notes,
                    explanation_source="llm",
                )
        logger.warning("Gemini explanation call returned status %d; falling back to template.", resp.status_code)
    except Exception as exc:
        logger.warning("Gemini explanation failed (%s); falling back to deterministic template.", type(exc).__name__)

    return _build_deterministic_template(ctx)
