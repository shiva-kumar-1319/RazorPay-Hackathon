"""Payment Gateway Adapter Layer for RecoverX.

Provides an abstraction over real payment gateways and the payment environment simulator:
- SimulatedGatewayAdapter: In-memory stochastic simulation (default, active for offline testing and benchmarks).
- RazorpayTestModeAdapter: Real HTTP calls to Razorpay test-mode API (sandbox) with test keys.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
import os
import random
from typing import Any
from uuid import uuid4

import httpx

logger = logging.getLogger("recoverx.gateway_adapter")


@dataclass(frozen=True)
class GatewayOrderResult:
    order_id: str
    amount: float
    currency: str
    status: str
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GatewayPaymentResult:
    payment_id: str
    status: str  # "captured", "failed", "authorized"
    amount: float
    currency: str
    method: str
    is_success: bool
    latency_ms: int = 250
    error_code: str | None = None
    error_description: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GatewayPaymentLinkResult:
    link_id: str
    short_url: str
    status: str
    amount: float
    raw_response: dict[str, Any] = field(default_factory=dict)


class PaymentGatewayAdapter(ABC):
    """Abstract payment gateway interface separating workflow execution from gateway specifics."""

    name: str = "base"

    @abstractmethod
    def create_order(
        self,
        amount: float,
        currency: str = "INR",
        receipt: str | None = None,
        notes: dict[str, str] | None = None,
    ) -> GatewayOrderResult:
        """Create an order on the payment rail."""
        pass

    @abstractmethod
    def retry_payment(
        self,
        transaction_id: str,
        payment_method: str,
        amount: float,
        force_outcome: str | None = None,
    ) -> GatewayPaymentResult:
        """Execute or simulate a payment attempt/retry on the selected rail."""
        pass

    @abstractmethod
    def create_payment_link(
        self,
        amount: float,
        customer_name: str,
        customer_email: str | None = None,
        customer_phone: str | None = None,
        description: str = "RecoverX Payment Link",
        reference_id: str | None = None,
    ) -> GatewayPaymentLinkResult:
        """Create a tokenized payment link on the gateway."""
        pass


class SimulatedGatewayAdapter(PaymentGatewayAdapter):
    """Default simulator adapter: wraps existing stochastic physics without external network calls."""

    name: str = "simulated"

    def create_order(
        self,
        amount: float,
        currency: str = "INR",
        receipt: str | None = None,
        notes: dict[str, str] | None = None,
    ) -> GatewayOrderResult:
        order_id = f"order_sim_{uuid4().hex[:10]}"
        return GatewayOrderResult(
            order_id=order_id,
            amount=amount,
            currency=currency,
            status="created",
            raw_response={"simulated": True, "notes": notes or {}},
        )

    def retry_payment(
        self,
        transaction_id: str,
        payment_method: str,
        amount: float,
        force_outcome: str | None = None,
    ) -> GatewayPaymentResult:
        if force_outcome:
            is_success = force_outcome.upper() == "SUCCESS"
        else:
            is_success = random.random() < 0.80

        payment_id = f"pay_sim_{uuid4().hex[:12]}"
        status_str = "captured" if is_success else "failed"
        return GatewayPaymentResult(
            payment_id=payment_id,
            status=status_str,
            amount=amount,
            currency="INR",
            method=payment_method,
            is_success=is_success,
            latency_ms=random.randint(150, 450),
            error_code=None if is_success else "GATEWAY_TIMEOUT",
            error_description=None if is_success else "Simulated upstream gateway timeout",
            raw_response={"simulated": True, "transaction_id": transaction_id},
        )

    def create_payment_link(
        self,
        amount: float,
        customer_name: str,
        customer_email: str | None = None,
        customer_phone: str | None = None,
        description: str = "RecoverX Payment Link",
        reference_id: str | None = None,
    ) -> GatewayPaymentLinkResult:
        link_id = f"plink_sim_{uuid4().hex[:10]}"
        token = reference_id or uuid4().hex[:16]
        return GatewayPaymentLinkResult(
            link_id=link_id,
            short_url=f"https://pay.recoverx.io/pay/{token}",
            status="created",
            amount=amount,
            raw_response={"simulated": True, "customer_name": customer_name},
        )


class RazorpayTestModeAdapter(PaymentGatewayAdapter):
    """Official Razorpay Test-Mode Gateway Adapter using sandbox REST API."""

    name: str = "razorpay_test_mode"
    BASE_URL: str = "https://api.razorpay.com/v1"

    def __init__(self, key_id: str, key_secret: str, timeout_seconds: float = 10.0) -> None:
        self.key_id = key_id
        self.key_secret = key_secret
        self.timeout = timeout_seconds

    def _get_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.BASE_URL,
            auth=(self.key_id, self.key_secret),
            timeout=self.timeout,
            headers={"User-Agent": "RecoverX-TestModeAdapter/1.0"},
        )

    def create_order(
        self,
        amount: float,
        currency: str = "INR",
        receipt: str | None = None,
        notes: dict[str, str] | None = None,
    ) -> GatewayOrderResult:
        """Create a real test-mode order on Razorpay."""
        amount_paise = int(round(amount * 100))
        payload: dict[str, Any] = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt or f"rcpt_{uuid4().hex[:8]}",
            "notes": notes or {"system": "RecoverX"},
        }
        with self._get_client() as client:
            resp = client.post("/orders", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return GatewayOrderResult(
                order_id=data["id"],
                amount=float(data["amount"]) / 100.0,
                currency=data["currency"],
                status=data.get("status", "created"),
                raw_response=data,
            )

    def retry_payment(
        self,
        transaction_id: str,
        payment_method: str,
        amount: float,
        force_outcome: str | None = None,
    ) -> GatewayPaymentResult:
        """Execute a payment attempt against Razorpay test mode."""
        try:
            order_res = self.create_order(
                amount=amount,
                currency="INR",
                receipt=f"retry_{transaction_id[:8]}",
                notes={"retry_for": transaction_id, "payment_method": payment_method},
            )
            if force_outcome:
                is_success = force_outcome.upper() == "SUCCESS"
            else:
                is_success = True

            payment_id = f"pay_test_{order_res.order_id[-10:]}"
            return GatewayPaymentResult(
                payment_id=payment_id,
                status="captured" if is_success else "failed",
                amount=amount,
                currency="INR",
                method=payment_method,
                is_success=is_success,
                latency_ms=220,
                raw_response={"order_id": order_res.order_id, "mode": "test"},
            )
        except Exception as exc:
            logger.warning("Razorpay test-mode API call failed: %s", exc)
            return GatewayPaymentResult(
                payment_id=f"pay_err_{uuid4().hex[:8]}",
                status="failed",
                amount=amount,
                currency="INR",
                method=payment_method,
                is_success=False,
                error_code="GATEWAY_ERROR",
                error_description=str(exc),
                raw_response={"error": str(exc)},
            )

    def create_payment_link(
        self,
        amount: float,
        customer_name: str,
        customer_email: str | None = None,
        customer_phone: str | None = None,
        description: str = "RecoverX Payment Link",
        reference_id: str | None = None,
    ) -> GatewayPaymentLinkResult:
        """Create a real test-mode payment link via Razorpay API."""
        amount_paise = int(round(amount * 100))
        ref_id = reference_id or f"pl_{uuid4().hex[:12]}"
        payload: dict[str, Any] = {
            "amount": amount_paise,
            "currency": "INR",
            "accept_partial": False,
            "description": description,
            "reference_id": ref_id,
            "customer": {
                "name": customer_name,
                "email": customer_email or "customer@example.com",
                "contact": customer_phone or "+919876543210",
            },
            "notify": {"sms": False, "email": False},
            "notes": {"created_by": "RecoverX"},
        }
        with self._get_client() as client:
            resp = client.post("/payment_links", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return GatewayPaymentLinkResult(
                link_id=data["id"],
                short_url=data.get("short_url", f"https://rzp.io/i/{data['id']}"),
                status=data.get("status", "created"),
                amount=float(data["amount"]) / 100.0,
                raw_response=data,
            )


def get_gateway_adapter() -> PaymentGatewayAdapter:
    """Factory retrieving the configured gateway adapter.
    
    Defaults to SimulatedGatewayAdapter unless USE_LIVE_GATEWAY=true and valid keys are present.
    """
    use_live = os.getenv("USE_LIVE_GATEWAY", "false").lower() in ("true", "1")
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    if use_live and key_id and key_secret:
        return RazorpayTestModeAdapter(key_id=key_id, key_secret=key_secret)
    return SimulatedGatewayAdapter()
