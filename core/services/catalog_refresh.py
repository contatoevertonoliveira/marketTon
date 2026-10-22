"""Atualização do catálogo por ferramenta (a mesma coleta do `scripts/ingest.py`, sem depender de script).

Quem usa: o agente Claude, quando o catálogo envelhece ou quando precisa de produtos de um nicho novo
(`refresh_catalog`); e qualquer operador com permissão de coleta.

Regras para o agente não martelar as APIs dos marketplaces:

* **uma atualização por vez** (travinha em processo + estado no banco com validade);
* **intervalo mínimo por marketplace** (`MIN_INTERVAL`): pedido antes disso é recusado com o motivo,
  salvo `force=True` (que o operador pode usar);
* só marketplaces **configurados e testados**; plataformas que não têm catálogo de produtos para afiliar
  (Hotmart, Eduzz) ficam de fora;
* roda **em segundo plano** (a coleta + score leva minutos) e avisa o resultado no chat.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from core.db.session import session_scope
from core.services.agent_chat import post_message
from core.services.app_settings import _row  # noqa: PLC2701 - mesma camada de serviços
from core.db.app_settings import AppSetting

logger = logging.getLogger(__name__)

MIN_INTERVAL = timedelta(hours=6)
STALE_RUNNING = timedelta(minutes=40)
NO_CATALOG = {"hotmart", "eduzz"}  # a API lista só produtos do produtor: o que se divulga aparece pelas vendas
STATE_KEY = "catalog_refresh_state"
_lock = threading.Lock()


def _state(session: Session) -> dict:
    row = _row(session, STATE_KEY)
    return dict(row.value) if row else {}


def _save_state(session: Session, state: dict) -> None:
    row = _row(session, STATE_KEY)
    if row is None:
        row = AppSetting(key=STATE_KEY, value={})
        session.add(row)
    row.value = state
    row.changed_at = datetime.now(UTC)
    session.flush()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def status(session: Session) -> dict:
    state = _state(session)
    started = _parse(state.get("started_at"))
    running = bool(state.get("running") and started and datetime.now(UTC) - started < STALE_RUNNING)
    return {**state, "running": running, "min_interval_hours": MIN_INTERVAL.total_seconds() / 3600}


def plan(session: Session, adapters: dict, *, marketplaces: list[str] | None, force: bool) -> tuple[list[str], dict[str, str]]:
    """Quais marketplaces atualizar agora e quais ficam de fora (com o motivo)."""
    state = _state(session)
    last = state.get("last_by_marketplace", {})
    chosen: list[str] = []
    skipped: dict[str, str] = {}
    for name, adapter in adapters.items():
        if marketplaces and name not in marketplaces:
            continue
        if name in NO_CATALOG:
            skipped[name] = "não tem catálogo de produtos para afiliar pela API (os produtos aparecem pelas vendas)"
        elif not adapter.is_configured():
            skipped[name] = "sem credencial configurada"
        elif not force and (at := _parse(last.get(name))) and datetime.now(UTC) - at < MIN_INTERVAL:
            wait = MIN_INTERVAL - (datetime.now(UTC) - at)
            skipped[name] = f"atualizado há pouco; só pode de novo em ~{int(wait.total_seconds() // 60)} min"
        else:
            chosen.append(name)
    return chosen, skipped


def start_refresh(
    session: Session,
    adapters: dict,
    *,
    marketplaces: list[str] | None = None,
    keywords: list[str] | None = None,
    limit: int = 50,
    force: bool = False,
    hunter: Callable[..., Any] | None = None,
    background: bool = True,
) -> dict:
    """Valida, marca como em andamento e dispara a coleta. Devolve o que vai (ou não) acontecer."""
    st = status(session)
    if st["running"]:
        return {"started": False, "reason": "já há uma atualização do catálogo em andamento", "skipped": {}}
    chosen, skipped = plan(session, adapters, marketplaces=marketplaces, force=force)
    if not chosen:
        return {"started": False, "reason": "nenhum marketplace elegível agora", "skipped": skipped}

    state = _state(session)
    _save_state(session, {**state, "running": True, "started_at": datetime.now(UTC).isoformat(),
                          "marketplaces": chosen, "keywords": keywords or None})
    session.commit()

    args = (adapters, chosen, keywords, max(1, min(limit, 100)), hunter)
    if background:
        threading.Thread(target=_work, args=args, daemon=True, name="catalog-refresh").start()
    else:  # usado nos testes
        _work(*args)
    return {"started": True, "marketplaces": chosen, "keywords": keywords or "padrão do Product Hunter", "skipped": skipped}


def _work(adapters: dict, chosen: list[str], keywords: list[str] | None, limit: int, hunter: Callable[..., Any] | None) -> None:
    from agents.product_hunter.agent import DEFAULT_KEYWORDS, HunterOptions, run

    hunter = hunter or run
    with _lock:
        summary, ok = "", False
        try:
            options = HunterOptions(
                keywords=list(keywords) if keywords else list(DEFAULT_KEYWORDS),
                adapter_names=chosen, max_items_per_adapter=limit, use_ai=False,
            )
            with session_scope() as session:
                result = hunter({}, session=session, adapters=adapters, options=options)
            ok, summary = bool(result.ok), str(result.summary)[:400]
            errors = (result.artifacts or {}).get("collect_errors") or []
            if errors:
                summary += " | avisos: " + "; ".join(str(e) for e in errors[:3])[:300]
        except Exception as exc:  # noqa: BLE001 - a thread não pode morrer calada
            logger.exception("falha ao atualizar o catálogo")
            summary = f"falhou: {exc}"[:300]

        with session_scope() as session:
            state = _state(session)
            now = datetime.now(UTC).isoformat()
            last = dict(state.get("last_by_marketplace", {}))
            if ok:
                for name in chosen:
                    last[name] = now
            _save_state(session, {**state, "running": False, "finished_at": now, "ok": ok, "summary": summary,
                                  "last_by_marketplace": last})
            post_message(session, author="system", kind="alert" if not ok else "message",
                         text=(f"📦 Catálogo atualizado ({', '.join(chosen)}): {summary}" if ok
                               else f"⚠️ A atualização do catálogo não terminou bem ({', '.join(chosen)}): {summary}"))
