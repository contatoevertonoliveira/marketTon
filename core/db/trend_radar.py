"""Radar de tendências: um retrato por palavra e por dia da busca no Google (Trends + Planejador), para comparar semana, quinzena e mês."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class TrendSnapshot(Base, TimestampMixin):
    __tablename__ = "trend_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    geo: Mapped[str] = mapped_column(String(8), nullable=False, default="BR")
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    interest_last: Mapped[float | None] = mapped_column(Float)
    growth_7d: Mapped[float | None] = mapped_column(Float)  # % do interesse médio dos últimos 7 dias sobre os 7 anteriores
    growth_15d: Mapped[float | None] = mapped_column(Float)
    growth_30d: Mapped[float | None] = mapped_column(Float)
    monthly_volume: Mapped[int | None] = mapped_column(Integer)
    cpc_brl: Mapped[float | None] = mapped_column(Float)
    competition: Mapped[str | None] = mapped_column(String(12))
    rising: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    error: Mapped[str | None] = mapped_column(String(200))
