"""Base de integração de pagamentos."""
from __future__ import annotations

from abc import abstractmethod

class PaymentError(Exception):
    pass


class PaymentResult:
    def __init__(self, ok: bool, tx_id: str | None = None, status: str = "unknown", raw: dict | None = None):
        self.ok = ok
        self.tx_id = tx_id
        self.status = status
        self.raw = raw or {}

    def to_dict(self) -> dict:
        return {"ok": self.ok, "tx_id": self.tx_id, "status": self.status, "raw": self.raw}


class PaymentGateway(ABC):
    name: str = "base"

    @abstractmethod
    def create_payment(self, amount_cents: int, currency: str = "BRL", metadata: dict | None = None) -> PaymentResult:
        ...

    @abstractmethod
    def get_status(self, tx_id: str) -> PaymentResult:
        ...
