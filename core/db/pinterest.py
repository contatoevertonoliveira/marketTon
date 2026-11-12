"""Pins do Pinterest do Mural na Web: do rascunho (texto, imagem e link prontos) até a publicação e as métricas."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class PinterestPin(Base, TimestampMixin):
    __tablename__ = "pinterest_pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    creative_campaign_id: Mapped[int | None] = mapped_column(ForeignKey("creative_campaigns.id", ondelete="SET NULL"))
    board_name: Mapped[str] = mapped_column(String(120), nullable=False)
    board_id: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)  # até 800 caracteres (limite do Pinterest)
    alt_text: Mapped[str | None] = mapped_column(String(500))
    keywords: Mapped[str | None] = mapped_column(String(300))  # separadas por vírgula (para o operador marcar nos interesses)
    link_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    link_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="page")  # page = página do produto no Mural | direct = link rastreado
    image_ref: Mapped[str] = mapped_column(String(600), nullable=False)  # "creative:<id>:<peça>" ou "product:<url da foto>"
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", index=True)  # draft | approved | published | failed | rejected
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pinterest_id: Mapped[str | None] = mapped_column(String(64))
    permalink: Mapped[str | None] = mapped_column(String(300))
    error: Mapped[str | None] = mapped_column(String(500))
    impressions: Mapped[int | None] = mapped_column(Integer)
    saves: Mapped[int | None] = mapped_column(Integer)
    pin_clicks: Mapped[int | None] = mapped_column(Integer)
    outbound_clicks: Mapped[int | None] = mapped_column(Integer)
    metrics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(64))
