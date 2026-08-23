from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_endpoint_returns_service_metadata() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "RecoverX"
    assert response.headers["X-Request-ID"] == "test-request"
