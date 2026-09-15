"""Endpoints de jobs e observabilidade (briefing seção 15).

Jobs precisam de histórico de execução. Estes endpoints expõem o que o orquestrador
e os agentes gravam — inclusive as falhas, que são a parte que costuma sumir.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.schemas import JobEventOut, JobOut
from backend.security import require
from backend.serializers import job_event_out, job_out
from core.db.base import JobStatus
from core.db.jobs import Job, JobEvent
from core.services.jobs import job_health

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require("jobs.view"))],
)


@router.get("/health")
def pipeline_health(session: Session = Depends(get_session)) -> dict:
    """Saúde do pipeline por tipo de job.

    `stale` é o campo mais útil na prática: um job que deveria rodar de hora em hora
    e não roda há seis é um problema que nenhum log mostra diretamente. O campo
    responde "o pipeline está rodando?" sem exigir leitura de log de servidor.
    """
    return job_health(session)


@router.get("", response_model=list[JobOut])
def list_jobs(
    session: Session = Depends(get_session),
    status: JobStatus | None = None,
    job_type: str | None = None,
    agent: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[JobOut]:
    statement = select(Job)
    if status is not None:
        statement = statement.where(Job.status == status)
    if job_type:
        statement = statement.where(Job.job_type == job_type)
    if agent:
        statement = statement.where(Job.agent == agent)
    statement = statement.order_by(desc(Job.created_at)).limit(limit).offset(offset)
    return [job_out(job) for job in session.scalars(statement)]


@router.get("/stats")
def job_stats(session: Session = Depends(get_session)) -> dict:
    """Taxa de sucesso e duração por tipo de job.

    Complementa `/jobs/health`: aqui o foco é qualidade das execuções, lá é
    atualidade delas.
    """
    by_status = session.execute(
        select(Job.status, func.count(Job.id)).group_by(Job.status)
    ).all()

    by_type = session.execute(
        select(
            Job.job_type,
            func.count(Job.id),
            func.avg(Job.duration_seconds),
            func.max(Job.finished_at),
        ).group_by(Job.job_type)
    ).all()

    failures = session.scalars(
        select(Job).where(Job.status == JobStatus.FAILED).order_by(desc(Job.created_at)).limit(5)
    ).all()

    counts = {status.value: int(count) for status, count in by_status}
    total = sum(counts.values())
    succeeded = counts.get(JobStatus.SUCCEEDED.value, 0)

    return {
        "total_jobs": total,
        "by_status": counts,
        "success_rate": round(succeeded / total, 4) if total else None,
        "by_type": [
            {
                "job_type": job_type,
                "jobs": int(count),
                "avg_duration_seconds": round(float(avg), 3) if avg is not None else None,
                "last_finished_at": last.isoformat() if last else None,
            }
            for job_type, count, avg, last in by_type
        ],
        "recent_failures": [job_out(job) for job in failures],
    }


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, session: Session = Depends(get_session)) -> JobOut:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} não encontrado")
    return job_out(job)


@router.get("/{job_id}/events", response_model=list[JobEventOut])
def job_events(job_id: int, session: Session = Depends(get_session)) -> list[JobEventOut]:
    """Trilha estruturada do job: o que aconteceu, em ordem."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} não encontrado")

    events = session.scalars(
        select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.occurred_at)
    )
    return [job_event_out(event) for event in events]
