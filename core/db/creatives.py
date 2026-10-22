"""Campanhas de criativos pedidas ao AI Studio (vídeos, imagens e textos de anúncio) e os eventos recebidos por webhook."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin

FINAL_STATUSES = ("completed", "partial", "failed", "canceled")


class CreativeCampaign(Base, TimestampMixin):
    __tablename__ = "creative_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    external_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(String(64))  # id do AI Studio
    mode: Mapped[str] = mapped_column(String(8), nullable=False, default="sandbox")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="requested", index=True)
    quality: Mapped[str] = mapped_column(String(12), nullable=False, default="economy")
    angle: Mapped[str | None] = mapped_column(String(32))
    budget_usd: Mapped[float] = mapped_column(Float, nullable=False)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    request: Mapped[dict | None] = mapped_column(JSON)
    manifest: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("external_ref", name="uq_creative_campaigns_external_ref"),)


class CreativeEvent(Base, TimestampMixin):
    """Eventos de webhook já processados (o AI Studio pode reenviar e entregar fora de ordem)."""

    __tablename__ = "creative_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    event: Mapped[str] = mapped_column(String(48), nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (UniqueConstraint("event_id", name="uq_creative_events_event_id"),)
