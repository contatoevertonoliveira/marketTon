"""Sincroniza vendas dos marketplaces, aprende comissão e avisa no chat.

É a ponte que faltava entre "a venda aconteceu" e "o operador ficou sabendo": o
mesmo caminho do `scripts/ingest.py --sales`, só que chamável pela API e pelo agente,
e que deixa um alerta no chat para cada venda nova. Só coleta o que a API do
marketplace entrega — se ela não trouxer uma venda, ela não aparece aqui.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import Marketplace
from core.db.tracking import Sale
from core.services.agent_chat import post_message
from core.services.commission_learning import apply_commissions, propose_commissions
from core.services.sales_ingestion import ingest_sales

MAX_ALERTS = 10


def _brl(value: float | None) -> str:
    return "—" if value is None else f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _alert_text(name: str, record) -> str:
    status = (record.status or "").upper()
    commission = record.commission_confirmed if record.commission_confirmed is not None else record.commission_estimated
    kind = "confirmada" if record.commission_confirmed is not None else "pendente (estimada)"
    if status == "CANCELLED":
        return f"Venda cancelada na {name}: {record.product_title or record.product_external_id or 'produto'}."
    return (
        f"💰 Nova venda na {name}: {record.product_title or record.product_external_id or 'produto'} — "
        f"{record.quantity} un., {_brl(record.gross_amount)}. Comissão {kind}: {_brl(commission)}."
    )


def sync_sales(session: Session, adapters: dict, *, since_days: int = 30, only: list[str] | None = None) -> dict:
    """Busca vendas de cada marketplace configurado. Devolve o resumo e avisa as vendas novas."""
    since = datetime.now(UTC) - timedelta(days=since_days)
    summary: list[dict] = []
    new_total = 0

    for name, adapter in adapters.items():
        if only and name not in only:
            continue
        entry = {"marketplace": name, "new_sales": 0, "skipped": None, "error": None, "commissions_learned": 0}
        if not adapter.is_configured():
            entry["skipped"] = "sem credencial configurada"
            summary.append(entry)
            continue
        try:
            records = adapter.fetch_sales(since=since)
        except NotImplementedError:
            entry["skipped"] = "este marketplace não entrega vendas por API"
            summary.append(entry)
            continue
        except Exception as exc:  # noqa: BLE001 - um marketplace com problema não impede os outros
            entry["error"] = str(exc)[:200]
            summary.append(entry)
            continue

        ids = [r.external_order_id for r in records if r.external_order_id]
        known = set(session.scalars(
            select(Sale.external_order_id).where(Sale.marketplace == Marketplace(name), Sale.external_order_id.in_(ids))
        )) if ids else set()
        new_records = [r for r in records if r.external_order_id and r.external_order_id not in known]

        ingest_sales(session, records, name)
        entry["commissions_learned"] = apply_commissions(session, propose_commissions(session, marketplace=Marketplace(name)))
        entry["new_sales"] = len(new_records)
        new_total += len(new_records)

        for record in new_records[:MAX_ALERTS]:
            post_message(session, author="system", kind="alert", text=_alert_text(name, record),
                         meta={"marketplace": name, "order": record.external_order_id})
        if len(new_records) > MAX_ALERTS:
            post_message(session, author="system", kind="alert",
                         text=f"+ {len(new_records) - MAX_ALERTS} venda(s) nova(s) na {name} (veja em Produtos > Desempenho).")
        summary.append(entry)

    return {"new_sales": new_total, "marketplaces": summary}
