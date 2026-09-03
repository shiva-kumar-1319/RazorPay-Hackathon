"""Tests for PaymentGatewayAdapter implementations and adapter factory."""

import os
from unittest.mock import patch

import pytest

from backend.app.services.gateway_adapter import (
    PaymentGatewayAdapter,
    RazorpayTestModeAdapter,
    SimulatedGatewayAdapter,
    get_gateway_adapter,
)


def test_simulated_gateway_adapter_create_order():
    """Verify simulated gateway adapter generates deterministic mock order."""
    adapter = SimulatedGatewayAdapter()
    order = adapter.create_order(amount=2499.00, currency="INR", notes={"source": "test"})

    assert order.order_id.startswith("order_sim_")
    assert order.amount == 2499.00
    assert order.currency == "INR"
    assert order.status == "created"
    assert order.raw_response["simulated"] is True


def test_simulated_gateway_adapter_retry_payment():
    """Verify simulated gateway adapter supports forced outcomes."""
    adapter = SimulatedGatewayAdapter()

    success_res = adapter.retry_payment(
        transaction_id="txn_123",
        payment_method="UPI",
        amount=1500.00,
        force_outcome="SUCCESS",
    )
    assert success_res.is_success is True
    assert success_res.status == "captured"
    assert success_res.amount == 1500.00

    fail_res = adapter.retry_payment(
        transaction_id="txn_123",
        payment_method="UPI",
        amount=1500.00,
        force_outcome="FAILED",
    )
    assert fail_res.is_success is False
    assert fail_res.status == "failed"


def test_simulated_gateway_adapter_create_payment_link():
    """Verify simulated payment link generation."""
    adapter = SimulatedGatewayAdapter()
    link = adapter.create_payment_link(
        amount=999.00,
        customer_name="Aarav Sharma",
        reference_id="token_abc_123",
    )
    assert link.link_id.startswith("plink_sim_")
    assert "token_abc_123" in link.short_url
    assert link.amount == 999.00


def test_gateway_adapter_factory_defaults_to_simulated():
    """Verify get_gateway_adapter defaults to SimulatedGatewayAdapter when flag is off."""
    with patch.dict(os.environ, {"USE_LIVE_GATEWAY": "false"}):
        adapter = get_gateway_adapter()
        assert isinstance(adapter, SimulatedGatewayAdapter)
        assert adapter.name == "simulated"


def test_gateway_adapter_factory_uses_razorpay_when_configured():
    """Verify get_gateway_adapter instantiates RazorpayTestModeAdapter when flag is on."""
    env_patch = {
        "USE_LIVE_GATEWAY": "true",
        "RAZORPAY_KEY_ID": "mock_key_id_123",
        "RAZORPAY_KEY_SECRET": "dummysecret456",
    }
    with patch.dict(os.environ, env_patch):
        adapter = get_gateway_adapter()
        assert isinstance(adapter, RazorpayTestModeAdapter)
        assert adapter.name == "razorpay_test_mode"
        assert adapter.key_id == "mock_key_id_123"


@pytest.mark.skipif(
    not os.getenv("RAZORPAY_TEST_KEY"),
    reason="Requires live Razorpay test credentials in RAZORPAY_TEST_KEY environment variable",
)
def test_razorpay_live_test_mode_round_trip():
    """Integration test: executes one round-trip against real Razorpay sandbox API."""
    key_id = os.getenv("RAZORPAY_TEST_KEY")
    key_secret = os.getenv("RAZORPAY_TEST_SECRET", "dummy_secret")
    adapter = RazorpayTestModeAdapter(key_id=key_id, key_secret=key_secret)

    order = adapter.create_order(amount=500.00, currency="INR", receipt="rcpt_itest_1")
    assert order.order_id.startswith("order_")
    assert order.status == "created"
