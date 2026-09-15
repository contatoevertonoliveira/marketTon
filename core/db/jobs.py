"""Jobs e observabilidade de execução.

Briefing seção 15: jobs devem possuir observabilidade e histórico de execução.
O orquestrador em memória não basta — cada execução precisa deixar registro
consultável, com duração, resultado e erro.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import (
    Base,
    BigIntPK,
    JobStatus,
    TimestampMixin,
    enum_column,
)


class Job(Base, TimestampMixin):
    """Uma execução de trabalho do pipeline (coleta, score, relatório, etc.)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Nome do agente/serviço que executou (ex.: "product_hunter", "scheduler").
    agent: Mapped[str | None] = mapped_column(String(64), index=True)

    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus, "job_status"),
        nullable=False,
        default=JobStatus.PENDING,
        index=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Persistido para não depender de cálculo em consulta de relatório.
    duration_seconds: Mapped[float | None] = mapped_column(Float)

    progress_pct: Mapped[float | None] = mapped_column(Float)
    params: Mapped[dict | None] = mapped_column(JSON)
    result_summary: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSON)

    error_type: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_traceback: Mapped[str | None] = mapped_column(Text)

    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Encadeamento para reprocessamento.
    parent_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    # Chave de idempotência: evita disparar o mesmo job duas vezes.
    idempotency_key: Mapped[str | None] = mapped_column(String(128))

    triggered_by: Mapped[str | None] = mapped_column(String(128))

    events: Mapped[list[JobEvent]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobEvent.occurred_at",
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        Index("ix_jobs_type_status_started", "job_type", "status", "started_at"),
        Index("ix_jobs_status_started", "status", "started_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Job {self.id} {self.job_type}:{self.status.value}>"


class JobEvent(Base):
    """Log estruturado de um job. É a trilha de observabilidade."""

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    level: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON)

    job: Mapped[Job] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_job_events_job_occurred", "job_id", "occurred_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JobEvent {self.level} {self.message[:40]!r}>"
