"""Credenciais de serviços de dados que não são marketplaces (ex.: Google Ads).

`marketplace_credentials` é indexada pelo enum `Marketplace` e alimenta abas e
adapters de venda; um serviço de métricas de busca não pertence a esse enum
(entraria nas abas de marketplace da interface). Por isso tabela própria, com o
mesmo formato: `values` em JSON, semáforo de teste real, segredos nunca
devolvidos pela API.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class ServiceCredential(Base, TimestampMixin):
    __tablename__ = "service_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String(48), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    last_check_status: Mapped[str | None] = mapped_column(String(16))  # "ok" | "error"
    last_check_message: Mapped[str | None] = mapped_column(String(500))
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("service", name="uq_service_credentials_service"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ServiceCredential {self.service} enabled={self.enabled}>"
