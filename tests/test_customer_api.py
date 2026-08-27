"""Integration tests for Customer Intelligence REST APIs and Persona Seeding."""

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.main import app


def test_customer_crud_apis(client: TestClient) -> None:
    """Test creating, fetching, updating, and listing customer profiles via REST API."""
    ext_id = f"cust_api_{uuid4().hex[:6]}"

    # 1. Create Customer
    payload = {
        "external_customer_id": ext_id,
        "merchant_id": "merch_api",
        "name": "Integration User",
        "email": f"{ext_id}@example.com",
        "phone": "+919876543210",
        "preferred_payment_method": "UPI",
        "risk_segment": "VIP",
        "metadata": {"tier": "gold"},
    }
    create_res = client.post("/api/v1/customers", json=payload)
    assert create_res.status_code == 201
    data = create_res.json()
    cust_id = data["id"]
    assert data["external_customer_id"] == ext_id
    assert data["name"] == "Integration User"
    assert data["intelligence"]["behavioral_segment"] == "VIP_HIGH_VALUE" or data["intelligence"]["behavioral_segment"] == "NEW_CUSTOMER"

    # 2. Get Customer Detail
    get_res = client.get(f"/api/v1/customers/{cust_id}")
    assert get_res.status_code == 200
    assert get_res.json()["email"] == f"{ext_id}@example.com"

    # 3. Patch Customer Preferences
    patch_res = client.patch(
        f"/api/v1/customers/{cust_id}",
        json={"name": "Integration User Renamed", "risk_segment": "STANDARD"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Integration User Renamed"
    assert patch_res.json()["risk_segment"] == "STANDARD"

    # 4. List Customers with Search & Filtering
    list_res = client.get(f"/api/v1/customers?merchant_id=merch_api&search={ext_id}")
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == cust_id


def test_customer_payment_behavior_api(client: TestClient) -> None:
    """Test customer payment behavior breakdown endpoint."""
    ext_id = f"cust_beh_{uuid4().hex[:6]}"
    create_res = client.post(
        "/api/v1/customers",
        json={
            "external_customer_id": ext_id,
            "merchant_id": "merch_beh",
            "name": "Behavior Test",
            "preferred_payment_method": "UPI",
        },
    )
    cust_id = create_res.json()["id"]

    # Call payment-behavior
    res = client.get(f"/api/v1/customers/{cust_id}/payment-behavior")
    assert res.status_code == 200
    data = res.json()
    assert data["customer_id"] == cust_id
    assert "retry_tolerance_score" in data
    assert "channel_affinity" in data
    assert "hourly_distribution" in data


def test_customer_features_api(client: TestClient) -> None:
    """Test customer ML feature snapshot endpoint."""
    ext_id = f"cust_feat_{uuid4().hex[:6]}"
    create_res = client.post(
        "/api/v1/customers",
        json={"external_customer_id": ext_id, "merchant_id": "merch_feat", "name": "Feature User"},
    )
    cust_id = create_res.json()["id"]

    res = client.get(f"/api/v1/customers/{cust_id}/features")
    assert res.status_code == 200
    data = res.json()
    assert data["customer_id"] == cust_id
    assert data["feature_version"] == "v1"
    assert len(data["feature_vector"]) == 9


def test_customer_recovery_history_api(client: TestClient) -> None:
    """Test customer recovery history endpoint."""
    ext_id = f"cust_rec_{uuid4().hex[:6]}"
    create_res = client.post(
        "/api/v1/customers",
        json={"external_customer_id": ext_id, "merchant_id": "merch_rec", "name": "Recovery User"},
    )
    cust_id = create_res.json()["id"]

    res = client.get(f"/api/v1/customers/{cust_id}/recovery-history")
    assert res.status_code == 200
    data = res.json()
    assert data["customer_id"] == cust_id
    assert data["total_recovery_cases"] == 0


def test_seed_customers_simulator_endpoint(client: TestClient) -> None:
    """Test POST /api/v1/simulator/seed-customers endpoint."""
    res = client.post("/api/v1/simulator/seed-customers?merchant_id=merch_seed_test")
    assert res.status_code == 201
    data = res.json()
    assert data["seeded_customers"] == 4
    assert data["seeded_transactions"] > 0
    assert len(data["customer_ids"]) == 4

    # Verify seeded customer appears in customer list
    list_res = client.get("/api/v1/customers?merchant_id=merch_seed_test")
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 4
