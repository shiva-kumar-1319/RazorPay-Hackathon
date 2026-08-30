"""REST API integration tests for Payment Recovery Agent endpoints."""

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.recovery import Customer, PaymentAttempt, Transaction, TransactionStatus


def test_list_agent_tools_api(client: TestClient) -> None:
    """Test GET /api/v1/agent/tools returns registered allow-listed tools and guardrails."""
    resp = client.get("/api/v1/agent/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert "guardrails" in data
    assert len(data["tools"]) == 6
    tool_names = [t["name"] for t in data["tools"]]
    assert "get_transaction_context" in tool_names
    assert "get_failure_policy" in tool_names
    assert "score_candidates" in tool_names
    assert "create_recovery_plan" in tool_names
    assert "request_execution" in tool_names
    assert "write_explanation" in tool_names


def test_execute_tool_api_success(client: TestClient) -> None:
    """Test POST /api/v1/agent/tools/execute for valid allow-listed tool."""
    resp = client.post(
        "/api/v1/agent/tools/execute",
        json={"tool_name": "get_failure_policy", "arguments": {"failure_code": "CARD_DECLINED"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["category"] == "PAYMENT_METHOD"
    assert "SWITCH_TO_UPI" in data["data"]["permitted_actions"]


def test_execute_tool_api_disallowed_tool(client: TestClient) -> None:
    """Test POST /api/v1/agent/tools/execute rejects disallowed tools."""
    resp = client.post(
        "/api/v1/agent/tools/execute",
        json={"tool_name": "arbitrary_eval_code", "arguments": {"code": "import os; os.system('ls')"}},
    )
    assert resp.status_code == 400
    assert "Disallowed tool" in resp.json()["detail"]


def test_investigate_api_endpoint(client: TestClient, db_session: Session) -> None:
    """Test POST /api/v1/agent/investigate runs end-to-end investigation on a failed transaction."""
    customer = Customer(
        external_customer_id=f"cust_api_{uuid4().hex[:6]}",
        merchant_id="merch_101",
        name="Rohan Gupta",
        email="rohan.gupta@example.com",
        phone="+919811223344",
        preferred_payment_method="UPI",
    )
    db_session.add(customer)
    db_session.flush()

    txn = Transaction(
        external_transaction_id=f"txn_api_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        customer_id=customer.id,
        amount=Decimal("4999.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()

    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            failure_code="CARD_DECLINED",
        )
    )
    db_session.commit()

    resp = client.post(
        "/api/v1/agent/investigate",
        json={"transaction_id": str(txn.id)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["transaction_id"] == str(txn.id)
    assert data["failure_category"] == "PAYMENT_METHOD"
    assert data["chosen_action"] in ("SWITCH_TO_UPI", "PAYMENT_LINK", "SWITCH_TO_NETBANKING")
    assert data["expected_value"] > 0
    assert len(data["steps"]) >= 5
    assert data["customer_explanation"] is not None


def test_investigate_api_404_not_found(client: TestClient) -> None:
    """Test POST /api/v1/agent/investigate returns 404 for unknown transaction UUID."""
    resp = client.post(
        "/api/v1/agent/investigate",
        json={"transaction_id": str(uuid4())},
    )
    assert resp.status_code == 404


def test_investigate_api_invalid_uuid(client: TestClient) -> None:
    """Test POST /api/v1/agent/investigate returns 422 for malformed UUID."""
    resp = client.post(
        "/api/v1/agent/investigate",
        json={"transaction_id": "not-a-valid-uuid"},
    )
    assert resp.status_code == 422


def test_create_plan_api_endpoint(client: TestClient, db_session: Session) -> None:
    """Test POST /api/v1/agent/plan creates a validated recovery plan."""
    txn = Transaction(
        external_transaction_id=f"txn_plan_api_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        amount=Decimal("1500.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            failure_code="CARD_DECLINED",
        )
    )
    db_session.commit()

    resp = client.post(
        "/api/v1/agent/plan",
        json={
            "transaction_id": str(txn.id),
            "chosen_action": "SWITCH_TO_UPI",
            "confidence_score": 0.90,
            "reason_codes": ["RECOMMENDED_SAFE_UPI"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["chosen_action"] == "SWITCH_TO_UPI"
    assert data["status"] in ("APPROVED", "DRAFT")
    assert "idempotency_key" in data


def test_create_plan_api_policy_violation(client: TestClient, db_session: Session) -> None:
    """Test POST /api/v1/agent/plan returns 400 for illegal action violating policy."""
    txn = Transaction(
        external_transaction_id=f"txn_viol_api_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        amount=Decimal("1500.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            failure_code="CARD_DECLINED",
        )
    )
    db_session.commit()

    resp = client.post(
        "/api/v1/agent/plan",
        json={
            "transaction_id": str(txn.id),
            "chosen_action": "RETRY_SAME_METHOD",  # Not permitted for CARD_DECLINED
        },
    )
    assert resp.status_code == 400
    assert "Policy violation" in resp.json()["detail"]


def test_get_agent_traces_api_endpoint(client: TestClient, db_session: Session) -> None:
    """Test GET /api/v1/agent/traces/{transaction_id} returns historical investigation logs."""
    txn = Transaction(
        external_transaction_id=f"txn_traces_{uuid4().hex[:8]}",
        merchant_id="merch_101",
        amount=Decimal("2000.00"),
        status=TransactionStatus.FAILED,
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add(
        PaymentAttempt(
            transaction_id=txn.id,
            attempt_number=1,
            payment_method="CARD",
            failure_code="CARD_DECLINED",
        )
    )
    db_session.commit()

    # Trigger investigation
    client.post(
        "/api/v1/agent/investigate",
        json={"transaction_id": str(txn.id)},
    )

    # Fetch traces
    resp = client.get(f"/api/v1/agent/traces/{txn.id}")
    assert resp.status_code == 200
    traces = resp.json()
    assert len(traces) >= 1
    assert traces[0]["actor"] == "payment_recovery_agent"
    assert "explanation_summary" in traces[0]["metadata"]
