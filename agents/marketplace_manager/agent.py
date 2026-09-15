"""Marketplace Manager — saúde do catálogo e leitura por IA.

O que fazia antes: escrevia `reports/marketplace_health_*.csv` com uma flag
`_value_presentation_ok = estoque > 0` e mais nada. O CSV ninguém consumia.

Agora:

* a análise roda sobre o **catálogo persistido**, não sobre uma coleta efêmera;
* problemas são detectados por regra explícita (estoque zerado, preço sem
  alteração suspeita, produto inativo há muito tempo, queda de nota);
* a IA lê o conjunto e prioriza — uma chamada para o grupo, não uma por produto,
  porque o valor aqui é comparar e ordenar, não descrever cada item;
* quando não há IA, as regras determinísticas continuam produzindo a análise. A IA
  é enriquecimento, não dependência.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from core.db.catalog import PriceHistory, Product
from core.services.ai.client import AIClient
from core.services.ai.interpreter import run_interpretation
from core.services.ai.prompts import get_prompt
from core.services.jobs import JobHandle, job_run
from core.tasks import TaskResult

logger = logging.getLogger(__name__)

# Um produto ativo sem ser visto há mais que isso provavelmente saiu do ar.
STALE_DAYS = 7
# Queda de preço acima disso merece atenção: pode ser o vendedor quebrando, ou
# erro de coleta.
SHARP_DROP_PCT = 25.0
# Queda de nota acima disso é sinal de problema com o produto ou o vendedor.
RATING_DROP_THRESHOLD = 0.5


@dataclass
class CatalogOptions:
    stale_days: int = STALE_DAYS
    max_findings: int = 50
    use_ai: bool = True


@dataclass
class CatalogFinding:
    """Um problema detectado, com a regra que o detectou.

    A `rule` fica registrada para que o alerta seja auditável: o operador sabe por
    que aquilo apareceu, e não apenas que apareceu.
    """

    product_id: int
    title: str
    marketplace: str
    issue: str
    rule: str
    severity: str  # "critical" | "warning" | "info"
    detail: dict[str, Any] = field(default_factory=dict)


def detect_issues(
    session: Session,
    *,
    options: CatalogOptions | None = None,
    now: datetime | None = None,
) -> list[CatalogFinding]:
    """Detecta problemas no catálogo por regra determinística.

    Função pura em relação à IA: os achados existem com ou sem LLM. É o que
    permite que a análise funcione com a IA desligada.
    """
    options = options or CatalogOptions()
    now = now or datetime.now(UTC)
    findings: list[CatalogFinding] = []

    # --- Produto ativo sem ser visto há muito tempo ---------------------------
    stale_cutoff = now - timedelta(days=options.stale_days)
    stale = session.scalars(
        select(Product)
        .where(Product.is_active.is_(True), Product.last_seen_at < stale_cutoff)
        .order_by(Product.last_seen_at)
        .limit(options.max_findings)
    ).all()
    for product in stale:
        seen = product.last_seen_at
        seen_aware = seen if seen.tzinfo else seen.replace(tzinfo=UTC)
        days = (now - seen_aware).days
        findings.append(
            CatalogFinding(
                product_id=product.id,
                title=product.title,
                marketplace=product.marketplace.value,
                issue=f"sem coleta há {days} dias",
                rule=f"stale_product>{options.stale_days}d",
                severity="warning",
                detail={"last_seen_at": seen.isoformat()},
            )
        )

    # --- Estoque zerado em produto ativo --------------------------------------
    out_of_stock = session.scalars(
        select(Product)
        .where(
            Product.is_active.is_(True),
            Product.available_quantity.is_not(None),
            Product.available_quantity <= 0,
        )
        .limit(options.max_findings)
    ).all()
    for product in out_of_stock:
        findings.append(
            CatalogFinding(
                product_id=product.id,
                title=product.title,
                marketplace=product.marketplace.value,
                issue="estoque zerado",
                rule="stock_zero",
                # Crítico: publicar ou manter campanha apontando para produto sem
                # estoque gera clique sem conversão.
                severity="critical",
                detail={"available_quantity": product.available_quantity},
            )
        )

    # --- Queda forte de preço desde a primeira observação ---------------------
    for product in _products_with_price_history(session, limit=options.max_findings):
        first_price = session.scalar(
            select(PriceHistory.price)
            .where(PriceHistory.product_id == product.id, PriceHistory.price.is_not(None))
            .order_by(PriceHistory.observed_at)
            .limit(1)
        )
        if first_price in (None, 0) or product.price is None:
            continue
        drop_pct = (float(first_price) - float(product.price)) / float(first_price) * 100
        if drop_pct >= SHARP_DROP_PCT:
            findings.append(
                CatalogFinding(
                    product_id=product.id,
                    title=product.title,
                    marketplace=product.marketplace.value,
                    issue=f"preço caiu {drop_pct:.1f}% desde a primeira coleta",
                    rule=f"price_drop>={SHARP_DROP_PCT:.0f}%",
                    # Informativo, não alerta: queda de preço pode ser oportunidade
                    # (margem melhor) ou sinal de problema. Quem decide é o operador.
                    severity="info",
                    detail={"first_price": float(first_price), "current_price": product.price},
                )
            )

    # --- Produto sem preço ----------------------------------------------------
    without_price = session.scalar(
        select(func.count())
        .select_from(Product)
        .where(Product.is_active.is_(True), Product.price.is_(None))
    )
    if without_price:
        findings.append(
            CatalogFinding(
                product_id=0,
                title=f"{int(without_price)} produto(s) ativos sem preço",
                marketplace="*",
                issue="preço ausente: a fonte não informou",
                rule="missing_price",
                severity="warning",
                detail={"count": int(without_price)},
            )
        )

    return findings


def _products_with_price_history(session: Session, *, limit: int):
    """Produtos que têm ao menos dois pontos de preço, para permitir comparação."""
    ids = session.scalars(
        select(PriceHistory.product_id)
        .group_by(PriceHistory.product_id)
        .having(func.count(PriceHistory.id) >= 2)
        .limit(limit)
    ).all()
    if not ids:
        return []
    return list(session.scalars(select(Product).where(Product.id.in_(ids), Product.is_active.is_(True))))


def prioritize_with_ai(
    session: Session,
    findings: list[CatalogFinding],
    *,
    ai: AIClient | None = None,
    handle: JobHandle | None = None,
) -> dict[str, Any] | None:
    """Pede à IA priorização do que exige ação imediata."""
    if not findings:
        return None

    ai = ai or AIClient()
    payload = [
        {
            "produto": finding.title,
            "marketplace": finding.marketplace,
            "problema": finding.issue,
            "regra": finding.rule,
            "severidade": finding.severity,
        }
        for finding in findings[:30]
    ]

    result = run_interpretation(
        session,
        ai=ai,
        agent="marketplace_manager",
        kind=_health_kind(),
        prompt=get_prompt("marketplace_health_reader"),
        inputs={"achados": payload},
        target_type="catalog",
    )

    if not result.ok:
        if handle:
            handle.add_event(
                f"leitura de catálogo por IA indisponível: {result.skipped_reason or result.error}",
                level="WARNING",
            )
        return None

    return result.output


def _health_kind():
    from core.db.ai import AIInterpretationKind

    return AIInterpretationKind.CATALOG_HEALTH_READING


def run(
    memory: dict,
    *,
    session: Session | None = None,
    ai: AIClient | None = None,
    options: CatalogOptions | None = None,
) -> TaskResult:
    """Execução como task do pipeline."""
    options = options or CatalogOptions()

    if session is None:
        return TaskResult(
            task_id="marketplace_manager",
            ok=True,
            summary="sem sessão de banco: catálogo não analisado",
            artifacts={"findings": 0},
        )

    with job_run(
        session,
        job_type="marketplace_manager.health",
        agent="marketplace_manager",
        params={"stale_days": options.stale_days},
    ) as handle:
        findings = detect_issues(session, options=options)

        by_severity: dict[str, int] = {}
        for finding in findings:
            by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
            if finding.severity == "critical":
                handle.add_event(
                    f"[{finding.marketplace}] {finding.title}: {finding.issue}",
                    level="ERROR",
                    payload={"rule": finding.rule, "product_id": finding.product_id},
                )

        interpretation = None
        if options.use_ai and findings:
            interpretation = prioritize_with_ai(session, findings, ai=ai, handle=handle)

        summary = (
            f"{len(findings)} achado(s) no catálogo: "
            f"{by_severity.get('critical', 0)} crítico(s), "
            f"{by_severity.get('warning', 0)} alerta(s), "
            f"{by_severity.get('info', 0)} informativo(s)"
        )
        if interpretation:
            summary += " | com priorização por IA"

        handle.add_event(summary)

        return TaskResult(
            task_id="marketplace_manager",
            ok=True,
            summary=summary,
            artifacts={
                "job_id": handle.id,
                "findings_count": len(findings),
                "by_severity": by_severity,
                "findings": [
                    {
                        "product_id": finding.product_id,
                        "title": finding.title,
                        "marketplace": finding.marketplace,
                        "issue": finding.issue,
                        "rule": finding.rule,
                        "severity": finding.severity,
                        "detail": finding.detail,
                    }
                    for finding in findings
                ],
                "interpretation": interpretation,
            },
        )


__all__ = [
    "RATING_DROP_THRESHOLD",
    "SHARP_DROP_PCT",
    "STALE_DAYS",
    "CatalogFinding",
    "CatalogOptions",
    "detect_issues",
    "prioritize_with_ai",
    "run",
]
