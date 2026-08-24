def test_health_endpoint_returns_service_metadata(client) -> None:
    response = client.get("/health", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert data["service"] == "RecoverX"
    assert "timestamp" in data
    assert "database" in data
    assert response.headers["X-Request-ID"] == "test-request"
