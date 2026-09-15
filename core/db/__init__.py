"""Camada de persistência do Affiliate Intelligence System.

Todos os modelos são importados aqui para que `Base.metadata` fique completo —
o Alembic e o `create_all` dos testes dependem disso.
"""
from __future__ import annotations

from core.db.base import (
    Base,
    ConnectorKind,
    CreativeAssetType,
    CreativeStatus,
    JobStatus,
    Marketplace,
    PortfolioState,
    PublicationStatus,
    RecommendationKind,
    ScoreDimension,
    ScoreRunStatus,
    TimestampMixin,
)
from core.db.ai import AIInterpretation, AIInterpretationKind
from core.db.auth import AuditLog, RefreshToken, Role, User
from core.db.catalog import (
    PriceHistory,
    Product,
    ProductMetric,
    Seller,
    SourceRecord,
)
from core.db.creative import CreativeAsset, CreativeAssetEvent, Publication
from core.db.jobs import Job, JobEvent
from core.db.learning import PredictionOutcome, ScoreCalibration
from core.db.portfolio import (
    PortfolioItem,
    PortfolioTransition,
    Recommendation,
)
from core.db.scoring import ScoreAlgorithm, ScoreContribution, ScoreRun
from core.db.support import (
    SUPPORT_MODELS,
    SupportAgendaItem,
    SupportFeedback,
    SupportGroup,
    SupportPayment,
    SupportPreference,
    SupportTrendAlert,
)
from core.db.tracking import AffiliateLink, ClickEvent, Commission, Sale
from core.db.trends import TrendKeyword, TrendObservation

__all__ = [
    # base
    "Base",
    "TimestampMixin",
    # enums
    "ConnectorKind",
    "CreativeAssetType",
    "CreativeStatus",
    "JobStatus",
    "Marketplace",
    "PortfolioState",
    "PublicationStatus",
    "RecommendationKind",
    "ScoreDimension",
    "ScoreRunStatus",
    # catalog
    "SourceRecord",
    "Seller",
    "Product",
    "ProductMetric",
    "PriceHistory",
    # scoring
    "ScoreAlgorithm",
    "ScoreRun",
    "ScoreContribution",
    # portfolio
    "PortfolioItem",
    "PortfolioTransition",
    "Recommendation",
    # creative
    "CreativeAsset",
    "CreativeAssetEvent",
    "Publication",
    # tracking
    "AffiliateLink",
    "ClickEvent",
    "Sale",
    "Commission",
    # tendências
    "TrendKeyword",
    "TrendObservation",
    # jobs
    "Job",
    "JobEvent",
    # learning
    "PredictionOutcome",
    "ScoreCalibration",
    # ai
    "AIInterpretation",
    "AIInterpretationKind",
    # autenticação
    "User",
    "Role",
    "RefreshToken",
    "AuditLog",
    # tabelas de suporte herdadas
    "SUPPORT_MODELS",
    "SupportAgendaItem",
    "SupportFeedback",
    "SupportGroup",
    "SupportPayment",
    "SupportPreference",
    "SupportTrendAlert",
]
