"""Base declarativa, mixins e enums compartilhados do modelo de domínio.

Regra de proveniência (briefing seção 4): todo dado coletado carrega origem,
timestamp, marketplace e nível de confiabilidade. Regra de honestidade
(briefing seção 2): campo indisponível é `NULL`, nunca 0 nem estimativa
silenciosa. Por isso os campos numéricos de catálogo são anuláveis.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, ForeignKey, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarativa do SQLAlchemy 2.0."""


# Chave primária de 64 bits no PostgreSQL, `INTEGER` no SQLite.
#
# Motivo: o SQLite só auto-incrementa quando o tipo é exatamente `INTEGER PRIMARY
# KEY`. Com `BIGINT` a coluna vira NOT NULL sem default e todo INSERT falha — o
# que impedia os testes de exercitarem o schema real. Em produção (PostgreSQL)
# o tipo continua sendo BIGINT.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")

# Idem para colunas de volume (métricas, cliques, vendas) quando usadas como PK.
BigIntCol = BigInteger().with_variant(Integer, "sqlite")


def enum_column(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Coluna de enum que persiste o *valor* (string), não o nome do membro.

    Sem `native_enum=False` o Postgres guardaria o nome do membro, o que torna
    renomeações e migrations frágeis.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=48,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )


class TimestampMixin:
    """`created_at` / `updated_at` gerenciados pelo banco."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Marketplace(str, enum.Enum):
    """Marketplaces suportados. Novos entram por adapter, sem alterar o domínio."""

    MERCADO_LIVRE = "mercado_livre"
    SHOPEE = "shopee"
    AMAZON = "amazon"
    TIKTOK_SHOP = "tiktok_shop"
    OTHER = "other"


class ConnectorKind(str, enum.Enum):
    """Natureza técnica da fonte, para auditoria de legitimidade (briefing seção 2)."""

    OFFICIAL_API = "official_api"
    AFFILIATE_API = "affiliate_api"
    ADS_LIBRARY = "ads_library"
    PUBLIC_DATASET = "public_dataset"
    MANUAL = "manual"


class PortfolioState(str, enum.Enum):
    """Máquina de estados do portfólio (briefing seção 7). Transições no backend."""

    DISCOVERED = "DISCOVERED"
    ANALYZING = "ANALYZING"
    WATCHLIST = "WATCHLIST"
    RECOMMENDED = "RECOMMENDED"
    AFFILIATION_PENDING = "AFFILIATION_PENDING"
    AFFILIATED = "AFFILIATED"
    PORTFOLIO_ACTIVE = "PORTFOLIO_ACTIVE"
    CREATIVE_PENDING = "CREATIVE_PENDING"
    READY_TO_PUBLISH = "READY_TO_PUBLISH"
    PUBLISHED = "PUBLISHED"
    MONITORING = "MONITORING"
    OPTIMIZATION_REQUIRED = "OPTIMIZATION_REQUIRED"
    SCALING = "SCALING"
    PAUSED = "PAUSED"
    REMOVED = "REMOVED"


class ScoreDimension(str, enum.Enum):
    """As seis dimensões de inteligência (briefing seção 5). Não existe 'produto quente' genérico."""

    HEAT = "HEAT"
    OPPORTUNITY = "OPPORTUNITY"
    PRODUCER_MOMENTUM = "PRODUCER_MOMENTUM"
    CREATIVE_SATURATION = "CREATIVE_SATURATION"
    PORTFOLIO = "PORTFOLIO"
    CREATIVE = "CREATIVE"


class ScoreRunStatus(str, enum.Enum):
    SUCCEEDED = "SUCCEEDED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FAILED = "FAILED"


class RecommendationKind(str, enum.Enum):
    """Saída acionável do motor de decisão (briefing seção 16)."""

    ANALYZE = "ANALYZE"
    AFFILIATE = "AFFILIATE"
    PRODUCE_CREATIVE = "PRODUCE_CREATIVE"
    PUBLISH = "PUBLISH"
    OPTIMIZE = "OPTIMIZE"
    SCALE = "SCALE"
    PAUSE = "PAUSE"
    REMOVE = "REMOVE"


class CreativeAssetType(str, enum.Enum):
    """Estágios independentes do pipeline criativo (briefing seção 8)."""

    COPY = "COPY"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    VOICE = "VOICE"
    EDIT = "EDIT"
    APPROVAL = "APPROVAL"
    PUBLICATION = "PUBLICATION"


class CreativeStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PublicationStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    REMOVED = "REMOVED"


def source_record_fk() -> Mapped[int]:
    """FK obrigatória para `source_records`: nada entra no domínio sem procedência."""
    return mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
