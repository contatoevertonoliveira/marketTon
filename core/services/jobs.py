"""Registro de execução de jobs (briefing seção 15).

Antes: o orquestrador guardava apenas o **último** `last_task` em `memory/state.json`.
Um arquivo com um registro só não é histórico de execução — é uma foto. O briefing
pede observabilidade, e observabilidade implica poder responder "o que rodou ontem
às 3h e falhou?".

Este módulo dá o invólucro que os agentes e o orquestrador usam:

    with job_run(session, job_type="collect", agent="product_hunter") as job:
        ...                      # trabalho
        job.add_event("coletados 42 itens", level="INFO", payload={"count": 42})
        job.finish(result_summary="42 itens", result={"rows": 42})

Em caso de exceção o job é gravado como `FAILED` com tipo, mensagem e traceback, e a
exceção **propaga** — o invólucro observa, não engole.
"""
from __future__ import annotations

import logging
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.db.base import JobStatus
from core.db.jobs import Job, JobEvent

logger = logging.getLogger(__name__)


@dataclass
class JobHandle:
    """Job em execução. O chamador usa para registrar progresso e resultado."""

    job: Job
    session: Session
    _events: list[JobEvent] = field(default_factory=list)

    @property
    def id(self) -> int:
        return self.job.id

    def add_event(
        self,
        message: str,
        *,
        level: str = "INFO",
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Registra um marco da execução.

        O evento é adicionado e sofre flush imediato para que, se o job travar, o
        que já aconteceu esteja gravado.
        """
        event = JobEvent(
            job_id=self.job.id,
            occurred_at=datetime.now(UTC),
            level=level,
            message=message,
            payload=payload,
        )
        self.session.add(event)
        self.session.flush()
        self._events.append(event)

    def set_progress(self, percent: float) -> None:
        self.job.progress_pct = max(0.0, min(100.0, percent))
        self.session.flush()

    def finish(
        self,
        *,
        summary: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> Job:
        """Marca o job como concluído com sucesso."""
        self.job.status = JobStatus.SUCCEEDED
        self.job.finished_at = datetime.now(UTC)
        self.job.result_summary = summary
        self.job.result = result
        self.job.progress_pct = 100.0
        self._stamp_duration()
        self.session.flush()
        return self.job

    def fail(self, error: BaseException) -> Job:
        """Marca o job como falho, preservando tipo, mensagem e traceback."""
        self.job.status = JobStatus.FAILED
        self.job.finished_at = datetime.now(UTC)
        self.job.error_type = type(error).__name__
        self.job.error_message = str(error)[:2000]
        self.job.error_traceback = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )[:8000]
        self._stamp_duration()
        self.session.flush()
        return self.job

    def _stamp_duration(self) -> None:
        if self.job.started_at is None:
            return
        finished = self.job.finished_at or datetime.now(UTC)
        started = _aware(self.job.started_at)
        self.job.duration_seconds = round((finished - started).total_seconds(), 3)


def _aware(value: datetime) -> datetime:
    """SQLite devolve datetime sem tzinfo; subtrair de aware levanta TypeError."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@contextmanager
def job_run(
    session: Session,
    *,
    job_type: str,
    agent: str | None = None,
    params: dict[str, Any] | None = None,
    triggered_by: str | None = None,
    idempotency_key: str | None = None,
    commit: bool = True,
) -> Iterator[JobHandle]:
    """Abre um job, executa o bloco e grava o desfecho.

    `idempotency_key` evita disparar o mesmo job duas vezes — útil quando o
    scheduler reenvia uma execução perdida.
    """
    if idempotency_key is not None:
        existing = session.scalar(
            select(Job).where(Job.idempotency_key == idempotency_key)
        )
        if existing is not None:
            # Já existe: devolve o registro existente sem reexecutar o trabalho.
            # Pular silenciosamente esconderia uma reexecução legítima, então o
            # evento é registrado no job existente.
            existing_handle = JobHandle(job=existing, session=session)
            existing_handle.add_event(
                f"execução ignorada: idempotency_key '{idempotency_key}' já registrada",
                level="WARNING",
            )
            if commit:
                session.commit()
            yield existing_handle
            return

    now = datetime.now(UTC)
    job = Job(
        job_type=job_type,
        agent=agent,
        status=JobStatus.RUNNING,
        started_at=now,
        params=params,
        triggered_by=triggered_by,
        idempotency_key=idempotency_key,
    )
    session.add(job)
    session.flush()

    handle = JobHandle(job=job, session=session)
    handle.add_event(f"job '{job_type}' iniciado" + (f" por {agent}" if agent else ""))

    try:
        yield handle
    except Exception as exc:
        handle.fail(exc)
        if commit:
            session.commit()
        logger.exception("job '%s' falhou", job_type)
        raise
    else:
        # Se o bloco terminou sem chamar `finish`, marcamos sucesso mesmo assim:
        # deixar em RUNNING para sempre é pior do que assumir conclusão normal.
        if job.status == JobStatus.RUNNING:
            handle.finish()
        if commit:
            session.commit()
    finally:
        if not commit:
            session.flush()


# --- Consultas ----------------------------------------------------------------


def recent_jobs(
    session: Session,
    *,
    job_type: str | None = None,
    agent: str | None = None,
    status: JobStatus | None = None,
    limit: int = 50,
) -> list[Job]:
    statement = select(Job)
    if job_type:
        statement = statement.where(Job.job_type == job_type)
    if agent:
        statement = statement.where(Job.agent == agent)
    if status is not None:
        statement = statement.where(Job.status == status)
    return list(
        session.scalars(statement.order_by(desc(Job.created_at)).limit(limit))
    )


def last_successful_job(session: Session, *, job_type: str) -> Job | None:
    """Última execução bem-sucedida de um tipo de job.

    Usado para saber "desde quando não coletamos?" — pergunta que o arquivo de
    estado de registro único não respondia.
    """
    return session.scalar(
        select(Job)
        .where(Job.job_type == job_type, Job.status == JobStatus.SUCCEEDED)
        .order_by(desc(Job.finished_at))
        .limit(1)
    )


def job_health(session: Session) -> dict[str, Any]:
    """Panorama de saúde por tipo de job.

    `stale` é o mais útil na prática: um job que deveria rodar de hora em hora e
    não roda há seis é um problema que nenhum log mostra diretamente.
    """
    from sqlalchemy import func

    rows = session.execute(
        select(
            Job.job_type,
            Job.status,
            func.count(Job.id),
            func.avg(Job.duration_seconds),
            func.max(Job.finished_at),
        ).group_by(Job.job_type, Job.status)
    ).all()

    by_type: dict[str, dict[str, Any]] = {}
    for job_type, status, count, avg, last in rows:
        entry = by_type.setdefault(
            job_type,
            {"job_type": job_type, "total": 0, "by_status": {}, "avg_duration_seconds": None, "last_finished_at": None},
        )
        entry["total"] += int(count)
        entry["by_status"][status.value if hasattr(status, "value") else str(status)] = int(count)
        if avg is not None:
            entry["avg_duration_seconds"] = round(float(avg), 3)
        if last is not None:
            last_iso = last.isoformat()
            if entry["last_finished_at"] is None or last_iso > entry["last_finished_at"]:
                entry["last_finished_at"] = last_iso

    now = datetime.now(UTC)
    for entry in by_type.values():
        last = entry["last_finished_at"]
        if last is None:
            entry["hours_since_last"] = None
            entry["stale"] = None
            continue
        # `fromisoformat` preserva a ausência de timezone que o SQLite devolve, e
        # subtrair naive de aware levanta TypeError. Normalizamos antes.
        delta = now - _aware(datetime.fromisoformat(last))
        hours = round(delta.total_seconds() / 3600, 2)
        entry["hours_since_last"] = hours
        entry["stale"] = hours > 24

    return {
        "types": sorted(by_type.values(), key=lambda item: item["job_type"]),
        "running": len(recent_jobs(session, status=JobStatus.RUNNING, limit=200)),
    }


__all__ = [
    "JobHandle",
    "job_health",
    "job_run",
    "last_successful_job",
    "recent_jobs",
]
