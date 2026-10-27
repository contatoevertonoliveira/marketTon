"""Posts publicados (ou que falharam) nas redes do Mural na Web: o histórico do que saiu, em qual rede, com qual texto e o link."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class SocialPost(Base, TimestampMixin):
    __tablename__ = "social_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # instagram
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="image")  # image | reel
    creative_campaign_id: Mapped[int | None] = mapped_column(ForeignKey("creative_campaigns.id", ondelete="SET NULL"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    deliverable_id: Mapped[str | None] = mapped_column(String(64))
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="published", index=True)  # published | failed
    external_id: Mapped[str | None] = mapped_column(String(64))
    permalink: Mapped[str | None] = mapped_column(String(300))
    error: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str | None] = mapped_column(String(64))
