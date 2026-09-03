"""Unit tests for Gemini Explanation Layer and Architectural Invariants."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.app.services.gemini_explainer import (
    ExplanationContext,
    generate_recovery_explanation,
)


@pytest.fixture
def sample_context() -> ExplanationContext:
    return ExplanationContext(
        transaction_id="txn_test_12345",
        amount=2499.00,
        currency="INR",
        failure_code="CARD_DECLINED",
        failure_category="PAYMENT_METHOD",
        chosen_action="SWITCH_TO_UPI",
        predicted_probability=0.885,
        net_expected_value=2210.60,
        merchant_log="Do Not Honor (ISO 05)",
        customer_default_message="Your card was declined. Please try paying via UPI for instant processing.",
        execution_disposition="QUEUED",
    )


def test_gemini_disabled_by_default_returns_template(sample_context):
    """When USE_LLM_EXPLANATIONS is false, returns deterministic template without making HTTP calls."""
    with patch.dict(os.environ, {"USE_LLM_EXPLANATIONS": "false", "GEMINI_API_KEY": "dummy_key"}):
        res = generate_recovery_explanation(sample_context)
        assert res.explanation_source == "template"
        assert "Agent selected SWITCH_TO_UPI" in res.narrative_summary
        assert "Your card was declined" in res.customer_message


def test_gemini_missing_api_key_returns_template(sample_context):
    """When GEMINI_API_KEY is unset, falls back immediately to template without error."""
    with patch.dict(os.environ, {"USE_LLM_EXPLANATIONS": "true", "GEMINI_API_KEY": ""}):
        res = generate_recovery_explanation(sample_context)
        assert res.explanation_source == "template"
        assert "Agent selected SWITCH_TO_UPI" in res.narrative_summary


def test_gemini_successful_llm_response(sample_context):
    """When Gemini returns a valid JSON narrative, format and tag as explanation_source='llm'."""
    mock_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "narrative_summary": "Autonomous agent routed customer to UPI following bank decline.",
                                "customer_message": "Tap here to finish your order via UPI.",
                                "merchant_notes": "Card decline resolved via UPI intent switch.",
                            })
                        }
                    ]
                }
            }
        ]
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_resp

    with patch.dict(os.environ, {"USE_LLM_EXPLANATIONS": "true", "GEMINI_API_KEY": "test_gemini_key_mock"}):
        res = generate_recovery_explanation(sample_context, client=mock_client)
        assert res.explanation_source == "llm"
        assert res.narrative_summary == "Autonomous agent routed customer to UPI following bank decline."
        assert res.customer_message == "Tap here to finish your order via UPI."
        assert res.merchant_notes == "Card decline resolved via UPI intent switch."


def test_gemini_timeout_falls_back_to_template(sample_context):
    """On Gemini network timeout, gracefully falls back to deterministic template."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.side_effect = httpx.TimeoutException("Read timed out after 3.0s")

    with patch.dict(os.environ, {"USE_LLM_EXPLANATIONS": "true", "GEMINI_API_KEY": "test_gemini_key_mock"}):
        res = generate_recovery_explanation(sample_context, client=mock_client)
        assert res.explanation_source == "template"
        assert "Agent selected SWITCH_TO_UPI" in res.narrative_summary
        assert "Your card was declined" in res.customer_message


def test_gemini_http_error_falls_back_to_template(sample_context):
    """On HTTP 500 / 429 error, gracefully falls back to deterministic template."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 500

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_resp

    with patch.dict(os.environ, {"USE_LLM_EXPLANATIONS": "true", "GEMINI_API_KEY": "test_gemini_key_mock"}):
        res = generate_recovery_explanation(sample_context, client=mock_client)
        assert res.explanation_source == "template"
        assert "Agent selected SWITCH_TO_UPI" in res.narrative_summary


def test_gemini_corrupted_response_falls_back_to_template(sample_context):
    """When LLM returns non-JSON or invalid schema, falls back to deterministic template."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "Sorry, I cannot answer this request."}]}}]
    }

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_resp

    with patch.dict(os.environ, {"USE_LLM_EXPLANATIONS": "true", "GEMINI_API_KEY": "test_gemini_key_mock"}):
        res = generate_recovery_explanation(sample_context, client=mock_client)
        assert res.explanation_source == "template"
        assert "Agent selected SWITCH_TO_UPI" in res.narrative_summary


def test_zero_generative_llm_in_core_financial_path():
    """Strict Architectural Invariant: assert no core decision modules import or call Gemini/LLM."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent

    critical_files = [
        repo_root / "backend" / "app" / "services" / "decision_engine.py",
        repo_root / "backend" / "app" / "services" / "recovery_policy.py",
        repo_root / "backend" / "app" / "services" / "prediction_model.py",
        repo_root / "backend" / "app" / "services" / "failure_intelligence.py",
    ]

    for fpath in critical_files:
        content = fpath.read_text(encoding="utf-8")
        assert "gemini_explainer" not in content, f"Violation: {fpath.name} must not import gemini_explainer"
        assert "google" not in content, f"Violation: {fpath.name} must not import google"
        assert "generate_recovery_explanation" not in content, f"Violation: {fpath.name} must not call explainer"


def test_gemini_live_call_when_key_configured(sample_context):
    """If a real GEMINI_API_KEY is configured in settings or environment, test live API generation."""
    from backend.app.config import get_settings
    key = get_settings().gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        pytest.skip("No live GEMINI_API_KEY configured.")

    with patch.dict(os.environ, {"USE_LLM_EXPLANATIONS": "true", "GEMINI_API_KEY": key}):
        res = generate_recovery_explanation(sample_context)
        assert res.explanation_source in ("llm", "template")
        assert len(res.narrative_summary) > 10
        assert len(res.customer_message) > 5
        assert len(res.merchant_notes) > 5

