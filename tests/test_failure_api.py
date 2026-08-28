"""API tests for Failure Intelligence endpoints."""

import pytest
from fastapi.testclient import TestClient


def test_classify_failure_api_exact_code(client: TestClient):
    """Test POST /api/v1/failures/classify with exact failure code."""
    response = client.post(
        "/api/v1/failures/classify",
        json={"failure_code": "OTP_TIMEOUT"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["normalized_code"] == "OTP_TIMEOUT"
    assert data["category"] == "CUSTOMER_ACTION"
    assert data["recoverable"] is True
    assert data["confidence"] == "1.0000" or float(data["confidence"]) == 1.0
    assert data["match_source"] == "EXACT_CODE"
    assert "CUSTOMER_NOTIFICATION" in data["permitted_actions"]
    assert len(data["customer_explanation"]) > 0
    assert len(data["merchant_explanation"]) > 0


def test_classify_failure_api_gateway_code(client: TestClient):
    """Test POST /api/v1/failures/classify with gateway-specific error code."""
    response = client.post(
        "/api/v1/failures/classify",
        json={
            "gateway": "RAZORPAY",
            "gateway_code": "BAD_REQUEST_PAYMENT_DECLINED_BY_BANK",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["normalized_code"] == "CARD_DECLINED"
    assert data["category"] == "PAYMENT_METHOD"
    assert data["recoverable"] is True
    assert "SWITCH_TO_UPI" in data["permitted_actions"]


def test_classify_failure_api_raw_message_nlp(client: TestClient):
    """Test POST /api/v1/failures/classify with natural language error message."""
    response = client.post(
        "/api/v1/failures/classify",
        json={
            "raw_message": "Issuer rejected charge: stolen card reported by cardholder.",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["normalized_code"] == "BLOCKED_CARD"
    assert data["category"] == "HARD_FAILURE"
    assert data["recoverable"] is False
    assert data["suggested_action"] == "STOP_RECOVERY"


def test_batch_classify_failures_api(client: TestClient):
    """Test POST /api/v1/failures/batch-classify."""
    response = client.post(
        "/api/v1/failures/batch-classify",
        json={
            "items": [
                {"failure_code": "TIMEOUT"},
                {"gateway": "STRIPE", "gateway_code": "insufficient_funds"},
                {"failure_code": "FRAUD_REJECTED"},
                {"raw_message": "online e-commerce disabled on card"},
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_processed"] == 4
    results = data["results"]
    assert results[0]["category"] == "TEMPORARY"
    assert results[1]["category"] == "CUSTOMER_ACTION"
    assert results[2]["category"] == "HARD_FAILURE"
    assert results[3]["category"] == "PAYMENT_METHOD"


def test_get_failure_taxonomy_api(client: TestClient):
    """Test GET /api/v1/failures/taxonomy."""
    response = client.get("/api/v1/failures/taxonomy")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "taxonomy.v1"
    assert data["codes_count"] >= 15
    assert len(data["categories"]) == 4
    assert "RAZORPAY" in data["gateway_mappings"]
    assert "STRIPE" in data["gateway_mappings"]
    assert "NPCI" in data["gateway_mappings"]


def test_explain_failure_code_api(client: TestClient):
    """Test GET /api/v1/failures/{failure_code}/explain."""
    response = client.get("/api/v1/failures/CARD_DECLINED/explain")
    assert response.status_code == 200
    data = response.json()
    assert data["normalized_code"] == "CARD_DECLINED"
    assert data["category"] == "PAYMENT_METHOD"
    assert data["recoverable"] is True
    assert "UPI" in data["alternative_payment_methods"]
    assert data["max_retries_permitted"] == 1


def test_get_failure_analytics_api(client: TestClient):
    """Test GET /api/v1/failures/analytics."""
    response = client.get("/api/v1/failures/analytics")
    assert response.status_code == 200
    data = response.json()
    assert "total_failures_recorded" in data
    assert "category_breakdown" in data
    assert len(data["category_breakdown"]) == 4
    assert "top_failure_codes" in data
    assert "gateway_failure_rates" in data
    assert "method_failure_rates" in data
    assert "anomalies_detected" in data
