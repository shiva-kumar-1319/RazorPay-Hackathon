"""API integration tests for Prediction and Decision endpoints — Day 8 & 9."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestPredictionAPI:
    """Test /api/v1/prediction/* endpoints."""

    def test_predict_endpoint(self, client: TestClient):
        resp = client.post("/api/v1/prediction/predict", json={
            "failure_code": "CARD_DECLINED",
            "failure_category": "PAYMENT_METHOD",
            "action_type": "SWITCH_TO_UPI",
            "amount": 5000.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "predicted_probability" in data
        assert 0 <= data["predicted_probability"] <= 1
        assert data["failure_category"] == "PAYMENT_METHOD"
        assert data["action_type"] == "SWITCH_TO_UPI"
        assert data["confidence"] in ("HIGH", "MEDIUM", "LOW")

    def test_predict_invalid_action_type(self, client: TestClient):
        resp = client.post("/api/v1/prediction/predict", json={
            "failure_code": "TIMEOUT",
            "failure_category": "TEMPORARY",
            "action_type": "INVALID_ACTION",
            "amount": 1000.0,
        })
        assert resp.status_code == 400

    def test_compare_endpoint(self, client: TestClient):
        resp = client.post("/api/v1/prediction/compare", json={
            "failure_category": "TEMPORARY",
            "amount": 3000.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "predictions" in data
        assert len(data["predictions"]) == 8  # all ActionType values
        assert data["predictions"][0]["rank"] == 1
        assert data["best_probability"] >= data["predictions"][-1]["predicted_probability"]

    def test_model_metrics_endpoint(self, client: TestClient):
        resp = client.get("/api/v1/prediction/model/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_trained"] is True
        assert data["auc"] > 0.5
        assert data["feature_count"] == 26

    def test_feature_importances_endpoint(self, client: TestClient):
        resp = client.get("/api/v1/prediction/model/features")
        assert resp.status_code == 200
        data = resp.json()
        assert "importances" in data
        assert len(data["importances"]) == 26
        assert len(data["top_10"]) == 10

    def test_retrain_endpoint(self, client: TestClient):
        resp = client.post("/api/v1/prediction/model/retrain?n_samples=1000&seed=99")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "retrained"
        assert "auc" in data["metrics"]


class TestDecisionAPI:
    """Test /api/v1/decision/* endpoints."""

    def test_evaluate_endpoint(self, client: TestClient):
        resp = client.post("/api/v1/decision/evaluate", json={
            "failure_category": "PAYMENT_METHOD",
            "amount": 5000.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "best_action" in data
        assert "all_actions" in data
        assert "explanation" in data
        assert len(data["all_actions"]) >= 1
        assert data["best_action"]["selected"] is True
        assert data["best_action"]["rank"] == 1

    def test_evaluate_hard_failure(self, client: TestClient):
        resp = client.post("/api/v1/decision/evaluate", json={
            "failure_category": "HARD_FAILURE",
            "amount": 10000.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["best_action"]["action_type"] == "STOP_RECOVERY"
        assert data["best_action"]["expected_value"] <= 0

    def test_recommend_endpoint(self, client: TestClient):
        resp = client.post("/api/v1/decision/recommend", json={
            "failure_category": "CUSTOMER_ACTION",
            "amount": 2500.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "recommended_action" in data
        assert "predicted_probability" in data
        assert "expected_value" in data
        assert len(data["explanation"]) > 10

    def test_cost_model_endpoint(self, client: TestClient):
        resp = client.get("/api/v1/decision/cost-model")
        assert resp.status_code == 200
        data = resp.json()
        assert "cost_model" in data
        assert "SWITCH_TO_UPI" in data["cost_model"]
        assert "STOP_RECOVERY" in data["cost_model"]
        assert data["friction_penalty_rate"] > 0
        assert data["time_decay_rate"] > 0

    def test_evaluate_temporary_failure(self, client: TestClient):
        resp = client.post("/api/v1/decision/evaluate", json={
            "failure_category": "TEMPORARY",
            "amount": 7500.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        action_types = [a["action_type"] for a in data["all_actions"]]
        assert "DELAYED_RETRY" in action_types or "RETRY_SAME_METHOD" in action_types
