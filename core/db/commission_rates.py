"""Comissão de afiliado por categoria, informada pelo operador.

A API da Mercado Livre não expõe comissão por produto; a taxa vem da tabela do
programa de afiliados, que varia por categoria e por tipo de conta. Por isso o
sistema não traz valores embutidos: quem digita é o operador, a partir do painel
dele. Um produto só recebe comissão estimada quando existe linha aqui.
"""
from __future__ import annotations

from sqlalchemy import Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, Marketplace, TimestampMixin, enum_column


class CommissionRate(Base, TimestampMixin):
    __tablename__ = "commission_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[Marketplace] = mapped_column(enum_column(Marketplace, "marketplace"), nullable=False)
    category_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rate_pct: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (UniqueConstraint("marketplace", "category_id", name="uq_commission_rates_marketplace_category"),)
