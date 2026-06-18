"""Stub MercadoPago (preview/baseado em docs públicas)."""
from __future__ import annotations

from typing import Any

from integrations.payments.base import PaymentResult, PaymentGateway


class MercadoPagoGateway(PaymentGateway):
    name = "mercadopago"

    def __init__(self, access_token: str | None = None):
        self.access_token = access_token or "TEST-ACCESS-TOKEN"

    def create_payment(self, amount_cents: int, currency: str = "BRL", metadata: dict | None = None) -> PaymentResult:
        return PaymentResult(
            ok=True,
            tx_id="MP_" + __import__("uuid").uuid4().hex[:10],
            status="pending",
            raw={"gateway": self.name, "amount_cents": amount_cents, "currency": currency, "metadata": metadata},
        )

    def get_status(self, tx_id: str) -> PaymentResult:
        return PaymentResult(ok=True, tx_id=tx_id, status="approved", raw={"gateway": self.name})
