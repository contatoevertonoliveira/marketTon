"""Parecer do agente sobre um criativo ou slideshow antes de publicar: aprovado ou recusado, com o motivo."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class CreativeReview(Base, TimestampMixin):
    __tablename__ = "creative_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creative_campaign_id: Mapped[int] = mapped_column(ForeignKey("creative_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # image | reel
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)  # approved | rejected
    notes: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(64), nullable=False)
