"""Anúncios criados em cima de um criativo (Meta hoje; Google depois) e as métricas lidas da plataforma.

Todas as métricas são anuláveis: `None` quer dizer "a plataforma ainda não informou", nunca zero inventado.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class AdCampaign(Base, TimestampMixin):
    __tablename__ = "ad_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creative_campaign_id: Mapped[int | None] = mapped_column(ForeignKey("creative_campaigns.id", ondelete="SET NULL"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False, default="meta")
    # draft (planejado) | paused | active | ended | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    variant: Mapped[str | None] = mapped_column(String(8))  # gancho A/B do criativo
    external_campaign_id: Mapped[str | None] = mapped_column(String(64))
    external_adset_id: Mapped[str | None] = mapped_column(String(64))
    external_ad_id: Mapped[str | None] = mapped_column(String(64))
    duration_days: Mapped[int | None] = mapped_column(Integer)
    destination_url: Mapped[str | None] = mapped_column(String(1024))
    meta_status: Mapped[str | None] = mapped_column(String(32))  # estado efetivo informado pela Meta
    daily_budget_brl: Mapped[float | None] = mapped_column(Float)
    spent_brl: Mapped[float | None] = mapped_column(Float)
    impressions: Mapped[int | None] = mapped_column(Integer)
    clicks: Mapped[int | None] = mapped_column(Integer)  # cliques no link do anúncio, segundo a plataforma
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_metrics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64))
