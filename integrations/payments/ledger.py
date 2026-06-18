"""Ledger idempotente de pagamentos."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from integrations.payments.base import PaymentResult


@dataclass
class LedgerRecord:
    tx_id: str
    gateway: str
    amount_cents: int
    currency: str
    status: str
    metadata: dict
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "gateway": self.gateway,
            "amount_cents": self.amount_cents,
            "currency": self.currency,
            "status": self.status,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class PaymentLedger:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Path(__file__).resolve().parent.parent.parent / "data" / "payments" / "ledger.jsonl"
        self._cache: dict[str, LedgerRecord] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").strip().splitlines():
            try:
                obj = json.loads(line)
                rec = LedgerRecord(
                    tx_id=obj["tx_id"],
                    gateway=obj["gateway"],
                    amount_cents=int(obj["amount_cents"]),
                    currency=obj["currency"],
                    status=obj["status"],
                    metadata=obj.get("metadata") or {},
                    created_at=obj.get("created_at", datetime.now().isoformat()),
                )
                self._cache[rec.tx_id] = rec
            except Exception:
                continue

    def append(self, result: PaymentResult, metadata: dict | None = None) -> LedgerRecord:
        tx_id = result.tx_id or uuid.uuid4().hex
        rec = LedgerRecord(
            tx_id=tx_id,
            gateway="unknown",
            amount_cents=0,
            currency="BRL",
            status=result.status,
            metadata=metadata or {},
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        self._cache[tx_id] = rec
        return rec

    def get(self, tx_id: str) -> LedgerRecord | None:
        return self._cache.get(tx_id)
