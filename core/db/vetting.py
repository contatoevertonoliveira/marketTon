"""Triagem de produtos: o parecer, com os números, de se um produto tem procura e demanda para receber dinheiro de anúncio."""
from __future__ import annotations

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class ProductVetting(Base, TimestampMixin):
    __tablename__ = "product_vettings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(120), nullable=False)
    # aprovado_pago | so_organico | reprovado | teste_operador (exceção do operador, 14 dias)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    monthly_volume: Mapped[int | None] = mapped_column(Integer)
    cpc_brl: Mapped[float | None] = mapped_column(Float)
    trend_direction: Mapped[str | None] = mapped_column(String(10))
    growth_pct_30d: Mapped[float | None] = mapped_column(Float)
    platform_sold: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    commission_per_sale_brl: Mapped[float | None] = mapped_column(Float)
    breakeven_conversion: Mapped[float | None] = mapped_column(Float)  # fração dos cliques que precisa virar venda para o anúncio empatar
    delivery_days: Mapped[int | None] = mapped_column(Integer)
    ship_from: Mapped[str | None] = mapped_column(String(32))
    reasons: Mapped[list | None] = mapped_column(JSON)
    created_by: Mapped[str | None] = mapped_column(String(64))
