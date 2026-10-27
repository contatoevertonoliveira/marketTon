"""Saldo das carteiras por plataforma. Cada lançamento fica no histórico; o saldo atual de uma plataforma é o lançamento mais recente."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class WalletBalance(Base, TimestampMixin):
    __tablename__ = "wallet_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    balance_brl: Mapped[float] = mapped_column(Float, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)  # quando o saldo valia
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="manual")  # manual | api
    note: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str | None] = mapped_column(String(64))
