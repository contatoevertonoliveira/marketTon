"""Verificação barata do sistema (sem IA) e relatório do agente.

Quatro vezes por dia o supervisor olha o sistema **por código**: vendas e cliques novos, anúncios com problema,
criativos que terminaram, integrações com erro. Se nada merece atenção, a verificação termina aqui (custo zero de token)
e fica registrada no relatório. Só quando há algo relevante o Claude é chamado, já recebendo este resumo no pedido.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.ads import AdCampaign
from core.db.agent_reports import KINDS, AgentReport
from core.db.creatives import CreativeCampaign
from core.db.service_credentials import ServiceCredential
from core.db.tracking import ClickEvent, Sale

CLICKS_NOTABLE = 25  # cliques novos na loja a partir dos quais vale uma análise
META_OK = {None, "", "ACTIVE", "PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED", "IN_PROCESS", "PENDING_REVIEW"}


class ReportError(ValueError):
    """Dado de relatório inválido; a mensagem é segura para exibir."""


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def _since(dt: datetime | None, since: datetime) -> bool:
    a = _aware(dt)
    return a is not None and a >= since


def digest(session: Session, since: datetime) -> dict:
    """O que mudou desde `since`, em números e em frases curtas. Só leitura."""
    since = _aware(since)
    sales = sum(1 for (t,) in session.execute(select(Sale.created_at)) if _since(t, since))
    clicks = sum(1 for (t,) in session.execute(select(ClickEvent.created_at)) if _since(t, since))

    ad_alerts: list[str] = []
    for ad in session.scalars(select(AdCampaign).where(AdCampaign.status == "active")):
        label = f"anúncio {ad.id}"
        if (ad.spent_brl or 0) > 0 and not ad.clicks:
            ad_alerts.append(f"{label} gastou R$ {ad.spent_brl:.2f} sem nenhum clique")
        if ad.meta_status not in META_OK:
            ad_alerts.append(f"{label} com estado {ad.meta_status} na Meta")

    creative_events: list[str] = []
    for c in session.scalars(select(CreativeCampaign).where(CreativeCampaign.finished_at.is_not(None))):
        if _since(c.finished_at, since):
            creative_events.append(f"criativo {c.id} terminou ({c.status})")

    integrations = [f"{s.service}: {s.last_check_message or 'com erro'}"[:120]
                    for s in session.scalars(select(ServiceCredential).where(
                        ServiceCredential.enabled.is_(True), ServiceCredential.last_check_status == "error"))]

    notable = bool(sales or ad_alerts or creative_events or integrations or clicks >= CLICKS_NOTABLE)
    return {"since": since.isoformat(), "sales": sales, "clicks": clicks, "ad_alerts": ad_alerts,
            "creative_events": creative_events, "integration_errors": integrations, "notable": notable}


def digest_text(d: dict) -> str:
    """O resumo em poucas linhas: vai no pedido ao Claude e no relatório."""
    parts = [f"vendas novas: {d['sales']}", f"cliques novos na loja: {d['clicks']}"]
    for key, label in (("ad_alerts", "anúncios"), ("creative_events", "criativos"), ("integration_errors", "integrações")):
        if d[key]:
            parts.append(f"{label}: " + "; ".join(d[key][:5]))
    return " | ".join(parts)


def add_report(session: Session, *, kind: str, title: str, body: str | None = None, run_id: int | None = None,
               author: str = "agent") -> AgentReport:
    if kind not in KINDS:
        raise ReportError(f"tipo inválido: use {', '.join(KINDS)}")
    title = (title or "").strip()
    if not title:
        raise ReportError("o relatório precisa de um título")
    report = AgentReport(kind=kind, title=title[:160], body=(body or "").strip()[:4000] or None, run_id=run_id, author=author)
    session.add(report)
    session.flush()
    return report


def report_out(r: AgentReport) -> dict:
    return {"id": r.id, "run_id": r.run_id, "kind": r.kind, "title": r.title, "body": r.body, "author": r.author,
            "created_at": r.created_at.isoformat() if r.created_at else None}


def list_reports(session: Session, *, kind: str | None = None, limit: int = 100) -> list[dict]:
    query = select(AgentReport).order_by(AgentReport.id.desc()).limit(max(1, min(limit, 300)))
    if kind:
        query = query.where(AgentReport.kind == kind)
    return [report_out(r) for r in session.scalars(query)]
