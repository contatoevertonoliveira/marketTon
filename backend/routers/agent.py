"""Administração pelo agente Claude: interruptor, status e checklist.

O agente (papel BOT, via servidor MCP em `mcp_server/`) usa estes endpoints para
saber se pode agir e o que falta para vender. O interruptor só é alterado por
quem tem `users.manage`; a trava em si está em `backend/security.py`.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dataclasses import asdict

from backend.deps import get_session
from backend.routers.marketplaces import CREDENTIAL_FIELDS
from backend.security import CurrentUser, Principal, record_action, require
from core.db.auth import Role, User
from core.db.base import PortfolioState
from core.db.catalog import Product
from core.db.marketplace_credentials import MarketplaceCredential
from core.db.portfolio import PortfolioItem
from core.db.service_credentials import ServiceCredential
from core.db.tracking import Sale
from core.db.base import Marketplace
from core.services.app_settings import agent_mode_info, set_agent_mode
from core.services.auth import create_user, get_user_by_username, set_password
from core.services.security import validate_password_strength
from core.services.commission_learning import apply_commissions, propose_commissions
from integrations.google_ads import GoogleAdsConfig

router = APIRouter(prefix="/agent", tags=["agente"])

STUCK_DAYS = 7
SALES_WINDOW_DAYS = 30


AGENT_USERNAME = "claude_agent"


class AgentModeOut(BaseModel):
    enabled: bool
    updated_by: str | None = None
    changed_at: str | None = None
    # Há acesso do agente criado? E quando o Claude entrou pela última vez? É o que a tela
    # usa para dizer "Claude conectado" — o login do agente acontece quando o servidor MCP sobe.
    agent_user_exists: bool = False
    agent_last_login_at: str | None = None


class AgentModeUpdate(BaseModel):
    enabled: bool


@router.get("/mode", response_model=AgentModeOut, summary="Modo agente (qualquer usuário autenticado)")
def get_mode(principal: CurrentUser, session: Session = Depends(get_session)) -> AgentModeOut:
    return _mode_out(session)


def _mode_out(session: Session) -> AgentModeOut:
    agent = get_user_by_username(session, AGENT_USERNAME)
    return AgentModeOut(
        **agent_mode_info(session),
        agent_user_exists=agent is not None and agent.role == Role.BOT,
        agent_last_login_at=agent.last_login_at.isoformat() if agent is not None and agent.last_login_at else None,
    )


@router.put("/mode", response_model=AgentModeOut, summary="Ligar ou desligar a administração pelo agente")
def put_mode(
    payload: AgentModeUpdate,
    principal: Principal = Depends(require("users.manage")),
    session: Session = Depends(get_session),
) -> AgentModeOut:
    info = set_agent_mode(session, enabled=payload.enabled, actor=principal.username)
    record_action(
        session,
        principal,
        action="agent.mode_changed",
        resource_type="setting",
        resource_id="agent_mode",
        detail="ligado" if payload.enabled else "desligado",
    )
    session.commit()
    return _mode_out(session)


class AgentAccessOut(BaseModel):
    username: str
    password: str  # mostrada uma única vez: não é guardada em texto em lugar nenhum
    rotated: bool


@router.post("/access", response_model=AgentAccessOut, summary="Gerar (ou renovar) o acesso do agente Claude")
def generate_access(
    principal: Principal = Depends(require("users.manage")), session: Session = Depends(get_session)
) -> AgentAccessOut:
    """Cria o usuário do agente (papel BOT) com senha aleatória forte, ou troca a senha dele.

    Evita que alguém invente usuário/senha à mão. Renovar derruba as sessões do agente: ele
    precisa da senha nova. Nunca assume um usuário que não seja do agente.
    """
    from fastapi import HTTPException

    password = ""
    while validate_password_strength(password):
        password = secrets.token_urlsafe(24)

    user = get_user_by_username(session, AGENT_USERNAME)
    rotated = user is not None
    if user is None:
        create_user(session, username=AGENT_USERNAME, password=password, role=Role.BOT, created_by=principal.username)
    elif user.role != Role.BOT:
        raise HTTPException(status_code=409, detail=f"o usuário '{AGENT_USERNAME}' já existe e não é um agente")
    else:
        if not user.is_active:
            user.is_active = True
        set_password(session, user, password)
    record_action(
        session, principal, action="agent.access_generated", resource_type="user", resource_id=AGENT_USERNAME,
        detail="senha renovada" if rotated else "usuário do agente criado",
    )
    session.commit()
    return AgentAccessOut(username=AGENT_USERNAME, password=password, rotated=rotated)


def _integrations(session: Session) -> list[dict]:
    """Estado das integrações, sem nenhum valor de credencial."""
    rows = {row.marketplace.value: row for row in session.scalars(select(MarketplaceCredential))}
    out = []
    for slug, fields in CREDENTIAL_FIELDS.items():
        row = rows.get(slug)
        filled = bool(row) and any(bool(row.values.get(f["name"])) for f in fields)
        out.append({
            "name": slug,
            "enabled": bool(row and row.enabled),
            "has_credentials": filled,
            "last_check_status": row.last_check_status if row else None,
            "last_check_message": row.last_check_message if row else None,
        })
    google = session.scalar(select(ServiceCredential).where(ServiceCredential.service == "google_ads"))
    out.append({
        "name": "google_ads",
        "enabled": bool(google and google.enabled),
        "has_credentials": bool(google) and GoogleAdsConfig.from_values(google.values).is_complete(),
        "last_check_status": google.last_check_status if google else None,
        "last_check_message": google.last_check_message if google else None,
    })
    return out


@router.get("/status", summary="Estado geral para o agente decidir o que fazer")
def status(
    principal: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)
) -> dict:
    since = datetime.now(UTC) - timedelta(days=SALES_WINDOW_DAYS)
    return {
        "agent_mode": agent_mode_info(session),
        "integrations": _integrations(session),
        "counts": {
            "products_in_catalog": session.scalar(select(func.count()).select_from(Product)) or 0,
            "portfolio_items": session.scalar(
                select(func.count()).select_from(PortfolioItem).where(PortfolioItem.state != PortfolioState.REMOVED)
            ) or 0,
            f"sales_last_{SALES_WINDOW_DAYS}_days": session.scalar(
                select(func.count()).select_from(Sale).where(Sale.occurred_at >= since)
            ) or 0,
        },
    }


@router.get("/checklist", summary="O que falta fazer para vender")
def checklist(
    principal: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)
) -> dict:
    """Lacunas objetivas, da mais à menos grave. Cada uma diz como resolver.

    Regras determinísticas sobre o que está no banco — o agente decide o que fazer
    com elas, mas a lista em si não depende de IA.
    """
    items: list[dict] = []

    def add(severity: str, key: str, title: str, how: str) -> None:
        items.append({"severity": severity, "key": key, "title": title, "how_to_fix": how})

    integrations = _integrations(session)
    enabled_marketplaces = [i["name"] for i in integrations if i["enabled"] and i["name"] in CREDENTIAL_FIELDS]
    if not enabled_marketplaces:
        add("alta", "no_marketplace", "Nenhum marketplace ativo",
            "Ative e configure Mercado Livre e/ou Shopee em Integrações.")

    for integ in integrations:
        name = integ["name"]
        if name == "google_ads":
            if not integ["has_credentials"]:
                add("média", "google_ads_missing", "Google Ads não conectado (sem volume, CPC e disputa)",
                    "Preencher o card Google Ads em Integrações e testar a conexão.")
            elif integ["last_check_status"] == "error":
                add("alta", "google_ads_error", f"Google Ads com falha: {integ['last_check_message']}",
                    "Revisar as credenciais no card Google Ads e testar de novo.")
            elif integ["last_check_status"] is None:
                add("baixa", "google_ads_untested", "Google Ads configurado mas não testado",
                    "Clicar em Testar conexão no card Google Ads.")
            continue
        if not integ["enabled"]:
            continue
        if integ["last_check_status"] == "error":
            add("alta", f"{name}_error", f"Conexão com {name} falhando: {integ['last_check_message']}",
                f"Revisar as credenciais de {name} em Integrações e testar de novo.")
        elif integ["last_check_status"] is None:
            add("baixa", f"{name}_untested", f"Conexão com {name} nunca foi testada",
                f"Clicar em Testar conexão no card de {name}.")

    since = datetime.now(UTC) - timedelta(days=SALES_WINDOW_DAYS)
    stuck_before = datetime.now(UTC) - timedelta(days=STUCK_DAYS)
    for mp in enabled_marketplaces:
        products = session.scalar(select(func.count()).select_from(Product).where(Product.marketplace == mp)) or 0
        if products == 0:
            add("alta", f"{mp}_catalog_empty", f"Catálogo de {mp} vazio",
                f"Coletar produtos: scripts/ingest.py --marketplace {mp}.")
        linked = session.scalar(
            select(func.count()).select_from(PortfolioItem).where(
                PortfolioItem.marketplace == mp, PortfolioItem.state != PortfolioState.REMOVED
            )
        ) or 0
        if products and linked == 0:
            add("alta", f"{mp}_nothing_linked", f"Nenhum produto vinculado em {mp}",
                "Escolher entre os sugeridos (Produtos > Sugeridos), conferindo o funil de venda, e vincular.")
        sales = session.scalar(
            select(func.count()).select_from(Sale).where(Sale.marketplace == mp, Sale.occurred_at >= since)
        ) or 0
        if linked and sales == 0:
            add("média", f"{mp}_no_sales", f"Sem vendas em {mp} nos últimos {SALES_WINDOW_DAYS} dias",
                "Conferir a ingestão (scripts/ingest.py --sales) e reforçar a divulgação dos produtos vinculados.")
        stuck = session.scalar(
            select(func.count()).select_from(PortfolioItem).where(
                PortfolioItem.marketplace == mp,
                PortfolioItem.state.in_([PortfolioState.DISCOVERED, PortfolioState.AFFILIATION_PENDING]),
                PortfolioItem.state_changed_at < stuck_before,
            )
        ) or 0
        if stuck:
            add("média", f"{mp}_stuck", f"{stuck} produto(s) de {mp} parado(s) há mais de {STUCK_DAYS} dias antes da afiliação",
                "Decidir: concluir a afiliação ou remover do portfólio.")

    missing = session.scalar(
        select(func.count()).select_from(Product).where(Product.affiliate_commission_pct.is_(None), Product.is_active.is_(True))
    ) or 0
    if missing:
        learnable = len(propose_commissions(session))
        add("média" if learnable else "baixa", "commission_missing",
            f"{missing} produto(s) do catálogo sem comissão informada"
            + (f"; {learnable} já venderam e a taxa pode ser calculada" if learnable else ""),
            "Rodar a ferramenta de comissão observada nas vendas (agent/commissions/apply)." if learnable
            else "A comissão passa a ser aprendida assim que o produto vender; ou informe a taxa do painel do marketplace.")

    order = {"alta": 0, "média": 1, "baixa": 2}
    items.sort(key=lambda i: order[i["severity"]])
    return {"count": len(items), "items": items}


# --- Comissão aprendida nas vendas ------------------------------------------------


@router.get("/commissions/proposals", summary="Produtos sem comissão que já venderam: taxa observada")
def commission_proposals(
    marketplace: Marketplace | None = None,
    min_sales: int = 1,
    principal: Principal = Depends(require("operations.view")),
    session: Session = Depends(get_session),
) -> dict:
    """Só calcula e mostra (não grava). `confidence` cai com poucas vendas."""
    proposals = propose_commissions(session, marketplace=marketplace, min_sales=max(1, min_sales))
    return {"count": len(proposals), "proposals": [asdict(p) for p in proposals]}


@router.post("/commissions/apply", summary="Grava a comissão observada nos produtos elegíveis")
def commission_apply(
    marketplace: Marketplace | None = None,
    min_sales: int = 1,
    principal: Principal = Depends(require("portfolio.manage")),
    session: Session = Depends(get_session),
) -> dict:
    proposals = propose_commissions(session, marketplace=marketplace, min_sales=max(1, min_sales))
    applied = apply_commissions(session, proposals)
    record_action(
        session, principal, action="agent.commissions_learned", resource_type="product",
        detail=f"{applied} produto(s) atualizado(s) com a comissão observada nas vendas",
    )
    session.commit()
    return {"applied": applied, "proposals": [asdict(p) for p in proposals]}
