"""Stub Pagar.me (comportamento padrão para homologação)."""
from __future__ import annotations

from typing import Any

from integrations.payments.base import PaymentResult, PaymentGateway


class PagarMeGateway(PaymentGateway):
    name = "pagarme"

    def __init__(self, secret_key: str | None = None):
        self.secret_key = secret_key or "sk_test_xxx"

    def create_payment(self, amount_cents: int, currency: str = "BRL", metadata: dict | None = None) -> PaymentResult:
        return PaymentResult(
            ok=True,
            tx_id="PG_" + __import__("uuid").uuid4().hex[:10],
            status="processing",
            raw={"gateway": self.name, "amount_cents": amount_cents, "currency": currency, "metadata": metadata},
        )

    def get_status(self, tx_id: str) -> PaymentResult:
        return PaymentResult(ok=True, tx_id=tx_id, status="paid", raw={"gateway": self.name})
