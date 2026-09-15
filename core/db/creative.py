"""Pipeline criativo e publicação.

Briefing seção 8: cada produto tem estados independentes para COPY, IMAGE,
VIDEO, VOICE/NARRATION, EDIT, APPROVAL e PUBLICATION, e o operador pode
atualizar manualmente o status pela interface. A arquitetura precisa permitir
integração futura via API com o AI Studio sem exigir reconstrução do módulo —
por isso `external_ref`/`external_system` existem desde o início.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import (
    Base,
    BigIntPK,
    CreativeAssetType,
    CreativeStatus,
    Marketplace,
    PublicationStatus,
    TimestampMixin,
    enum_column,
)

# Associação N:N entre publicação e links de afiliado: uma publicação pode
# carregar vários links e um link pode aparecer em várias publicações.
publication_links = Table(
    "publication_links",
    Base.metadata,
    Column("publication_id", ForeignKey("publications.id", ondelete="CASCADE"), primary_key=True),
    Column("affiliate_link_id", ForeignKey("affiliate_links.id", ondelete="CASCADE"), primary_key=True),
)


class CreativeAsset(Base, TimestampMixin):
    """Um material do pipeline para um produto/item de portfólio.

    Um asset por (item, tipo) é o caso comum, mas `version` permite manter
    histórico de revisões sem perder o que já foi publicado.
    """

    __tablename__ = "creative_assets"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    portfolio_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )

    asset_type: Mapped[CreativeAssetType] = mapped_column(
        enum_column(CreativeAssetType, "creative_asset_type"),
        nullable=False,
        index=True,
    )
    status: Mapped[CreativeStatus] = mapped_column(
        enum_column(CreativeStatus, "creative_status"),
        nullable=False,
        default=CreativeStatus.PENDING,
        index=True,
    )
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str | None] = mapped_column(String(255))

    # --- Conteúdo -------------------------------------------------------------
    # Para COPY, o texto. Para mídia, a referência/URL do arquivo.
    content_text: Mapped[str | None] = mapped_column(Text)
    content_url: Mapped[str | None] = mapped_column(String(1024))
    content_metadata: Mapped[dict | None] = mapped_column(JSON)

    # --- Integração futura com o AI Studio (briefing seção 8) -----------------
    external_system: Mapped[str | None] = mapped_column(String(64))
    external_ref: Mapped[str | None] = mapped_column(String(255), index=True)

    # --- Aprovação ------------------------------------------------------------
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    blocked_reason: Mapped[str | None] = mapped_column(Text)

    # --- Desempenho real (Creative Score, briefing seção 5) -------------------
    score_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("score_runs.id", ondelete="SET NULL"), index=True
    )
    performance_metrics: Mapped[dict | None] = mapped_column(JSON)

    events: Mapped[list[CreativeAssetEvent]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="CreativeAssetEvent.occurred_at",
    )
    publications: Mapped[list[Publication]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "portfolio_item_id", "asset_type", "version", name="uq_creative_assets_item_type_version"
        ),
        Index("ix_creative_assets_type_status", "asset_type", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CreativeAsset {self.asset_type.value}:{self.status.value} v{self.version}>"


class CreativeAssetEvent(Base, TimestampMixin):
    """Histórico de mudanças de status de um material criativo."""

    __tablename__ = "creative_asset_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    asset_id: Mapped[int] = mapped_column(
        ForeignKey("creative_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[CreativeStatus | None] = mapped_column(
        enum_column(CreativeStatus, "creative_status")
    )
    to_status: Mapped[CreativeStatus] = mapped_column(
        enum_column(CreativeStatus, "creative_status"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    asset: Mapped[CreativeAsset] = relationship(back_populates="events")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CreativeAssetEvent {self.from_status}->{self.to_status}>"


class Publication(Base, TimestampMixin):
    """Onde e quando um material foi publicado. Fecha o elo com o tracking."""

    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    creative_asset_id: Mapped[int] = mapped_column(
        ForeignKey("creative_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    portfolio_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="SET NULL"), index=True
    )

    channel: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_ref: Mapped[str | None] = mapped_column(String(255))
    external_post_id: Mapped[str | None] = mapped_column(String(255), index=True)

    status: Mapped[PublicationStatus] = mapped_column(
        enum_column(PublicationStatus, "publication_status"),
        nullable=False,
        default=PublicationStatus.DRAFT,
        index=True,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    marketplace: Mapped[Marketplace | None] = mapped_column(enum_column(Marketplace, "marketplace"))
    url: Mapped[str | None] = mapped_column(String(1024))
    failure_reason: Mapped[str | None] = mapped_column(Text)

    # Métricas do canal, quando a rede expõe.
    impressions: Mapped[int | None] = mapped_column(Integer)
    clicks: Mapped[int | None] = mapped_column(Integer)
    ctr: Mapped[float | None] = mapped_column(Float)
    metrics_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    asset: Mapped[CreativeAsset] = relationship(back_populates="publications")
    # N:N com links de afiliado. `secondary` em forma de string porque a tabela
    # `affiliate_links` vive em `core.db.tracking`, importado depois deste módulo.
    affiliate_links: Mapped[list] = relationship(
        "AffiliateLink",
        secondary=publication_links,
        back_populates="publications",
    )

    __table_args__ = (
        Index("ix_publications_status_published", "status", "published_at"),
        Index("ix_publications_channel_published", "channel", "published_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Publication {self.channel}:{self.status.value}>"
