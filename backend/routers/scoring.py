"""Endpoints de scoring (briefing seções 5 e 6).

Duas superfícies distintas:

* **Leitura para decisão** — `/targets/{type}/{id}` devolve o score mais recente de
  cada dimensão já com a explicação, que é o que o operador precisa.
* **Auditoria** — `/runs/{id}` devolve o cálculo inteiro: inputs, pesos, fórmula,
  versão e cada contribuição. É o que responde "de onde veio este número?".

E uma superfície de escrita: `/compute`, que roda o motor de verdade e persiste o
cálculo. Não existe endpoint para *definir* um score à mão — um número sem cálculo
não teria procedência, e o briefing seção 5 exige inputs, pesos e fórmula gravados.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from backend.deps import get_session
from backend.security import require
from backend.serializers import score_explanation, score_run_out
from backend.schemas import ScoreAlgorithmOut, ScoreExplanation, ScoreRunOut
from core.db.base import Marketplace, ScoreDimension
from core.db.catalog import Product
from core.db.scoring import ScoreAlgorithm, ScoreRun
from core.services.scoring.engine import (
    all_specs,
    compute,
    get_spec,
    load_specs,
    persist_run,
)

router = APIRouter(
    prefix="/scoring",
    tags=["scoring"],
    dependencies=[Depends(require("scoring.view"))],
)


@router.get("/algorithms", response_model=list[ScoreAlgorithmOut])
def list_algorithms(session: Session = Depends(get_session)) -> list[ScoreAlgorithmOut]:
    """Versões de algoritmo registradas.

    Combina o que está em código com o que está no banco: uma versão pode existir
    em código sem nunca ter sido executada, e isso é informação útil.
    """
    load_specs()

    persisted = {
        (algorithm.dimension.value, algorithm.version): algorithm
        for algorithm in session.scalars(select(ScoreAlgorithm))
    }

    result: list[ScoreAlgorithmOut] = []
    for spec in all_specs():
        stored = persisted.get((spec.dimension, spec.version))
        result.append(
            ScoreAlgorithmOut(
                id=stored.id if stored else 0,
                dimension=spec.dimension,
                version=spec.version,
                name=spec.name,
                description=spec.description,
                algorithm_key=spec.algorithm_key,
                weights=dict(spec.weights),
                parameters=dict(spec.parameters),
                formula=spec.formula_text(),
                is_active=stored.is_active if stored else True,
                effective_from=stored.effective_from if stored else datetime.now(UTC),
            )
        )
    return sorted(result, key=lambda item: (item.dimension, item.version))


@router.get("/algorithms/{dimension}/{version}", response_model=ScoreAlgorithmOut)
def get_algorithm(dimension: str, version: str) -> ScoreAlgorithmOut:
    """Uma versão específica: pesos, parâmetros e fórmula legível."""
    load_specs()
    try:
        spec = get_spec(dimension, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ScoreAlgorithmOut(
        id=0,
        dimension=spec.dimension,
        version=spec.version,
        name=spec.name,
        description=spec.description,
        algorithm_key=spec.algorithm_key,
        weights=dict(spec.weights),
        parameters=dict(spec.parameters),
        formula=spec.formula_text(),
        is_active=True,
        effective_from=datetime.now(UTC),
    )


@router.get("/targets/{target_type}/{target_id}", response_model=list[ScoreExplanation])
def scores_for_target(
    target_type: str,
    target_id: int,
    session: Session = Depends(get_session),
    dimension: ScoreDimension | None = None,
) -> list[ScoreExplanation]:
    """Score mais recente por dimensão, **com a explicação**.

    Esta é a chamada que responde "por que este produto foi recomendado?": devolve
    a lista `+ motivo` / `- motivo` junto com os inputs, pesos e versão do cálculo.
    """
    statement = (
        select(ScoreRun)
        .where(ScoreRun.target_type == target_type, ScoreRun.target_id == target_id)
        .options(selectinload(ScoreRun.contributions))
        .order_by(ScoreRun.dimension, desc(ScoreRun.computed_at))
    )
    if dimension is not None:
        statement = statement.where(ScoreRun.dimension == dimension)

    runs = list(session.scalars(statement))

    # Apenas a execução mais recente de cada dimensão.
    latest: dict[str, ScoreRun] = {}
    for run in runs:
        key = run.dimension.value
        if key not in latest:
            latest[key] = run

    return [score_explanation(run) for run in latest.values()]


@router.get("/runs", response_model=list[ScoreRunOut])
def list_runs(
    session: Session = Depends(get_session),
    dimension: ScoreDimension | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ScoreRunOut]:
    """Histórico de cálculos. É a base para comparar previsão com resultado."""
    statement = select(ScoreRun)
    if dimension is not None:
        statement = statement.where(ScoreRun.dimension == dimension)
    if target_type:
        statement = statement.where(ScoreRun.target_type == target_type)
    if target_id is not None:
        statement = statement.where(ScoreRun.target_id == target_id)
    statement = statement.order_by(desc(ScoreRun.computed_at)).limit(limit).offset(offset)

    return [score_run_out(run) for run in session.scalars(statement)]


@router.get("/runs/{run_id}", response_model=ScoreExplanation)
def get_run(run_id: int, session: Session = Depends(get_session)) -> ScoreExplanation:
    """Auditoria completa de um cálculo: inputs, pesos, fórmula e contribuições."""
    run = session.scalar(
        select(ScoreRun).where(ScoreRun.id == run_id).options(selectinload(ScoreRun.contributions))
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"score run {run_id} não encontrado")
    return score_explanation(run)


@router.post(
    "/compute",
    response_model=ScoreExplanation,
    status_code=201,
    dependencies=[Depends(require("scoring.compute"))],
)
def compute_score(
    payload: dict,
    session: Session = Depends(get_session),
) -> ScoreExplanation:
    """Executa um score e persiste o cálculo.

    Corpo esperado::

        {"dimension": "OPPORTUNITY", "target_type": "product", "target_id": 12}

    O motor roda de verdade e grava inputs, pesos, fórmula, versão e cada
    contribuição — é o que torna o número auditável depois.
    """
    load_specs()

    dimension = payload.get("dimension")
    target_type = payload.get("target_type", "product")
    target_id = payload.get("target_id")

    if not dimension or target_id is None:
        raise HTTPException(
            status_code=422, detail="campos obrigatórios: dimension, target_id"
        )

    from core.services.scoring_inputs import build_inputs

    try:
        inputs = build_inputs(session, dimension=dimension, target_type=target_type, target_id=int(target_id))
    except NotImplementedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        spec = get_spec(dimension, payload.get("version") or _active_version(dimension))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    result = compute(spec, inputs)

    marketplace = None
    if target_type == "product":
        product = session.get(Product, int(target_id))
        if product is not None:
            marketplace = product.marketplace

    run = persist_run(
        session,
        spec=spec,
        result=result,
        target_type=target_type,
        target_id=int(target_id),
        marketplace=marketplace,
    )
    session.commit()
    session.refresh(run)

    reloaded = session.scalar(
        select(ScoreRun).where(ScoreRun.id == run.id).options(selectinload(ScoreRun.contributions))
    )
    assert reloaded is not None
    return score_explanation(reloaded)


def _active_version(dimension: str) -> str:
    from core.services.scoring.engine import active_spec

    return active_spec(dimension).version


__all__ = ["router"]
