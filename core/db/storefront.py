"""Vitrine pública: ajustes por produto de como ele aparece na loja (categoria, texto, destaque, oculto).

A **lista** de produtos da loja não é duplicada aqui: todo item do portfólio entra por padrão. Esta tabela guarda só o que o
operador (ou o agente) decidiu diferente do padrão, e os produtos acrescentados à mão que não estão no portfólio.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class StorefrontItem(Base, TimestampMixin):
    __tablename__ = "storefront_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str | None] = mapped_column(String(48))
    display_title: Mapped[str | None] = mapped_column(String(160))
    blurb: Mapped[str | None] = mapped_column(String(280))
    highlight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("product_id", name="uq_storefront_items_product_id"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StorefrontItem product={self.product_id} hidden={self.hidden}>"
