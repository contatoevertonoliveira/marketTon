"""Administração pelo agente Claude: interruptor, status e checklist.

O agente (papel BOT, via servidor MCP em `mcp_server/`) usa estes endpoints para
saber se pode agir e o que falta para vender. O interruptor só é alterado por
quem tem `users.manage`; a trava em si está em `backend/security.py`.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dataclasses import asdict

from backend.deps import get_adapters, get_session
from backend.routers.marketplaces import CREDENTIAL_FIELDS
from backend.security import CurrentUser, Principal, record_action, require
from core.roles import AGENT_ROLE
from core.db.auth import Role, User
from core.db.base import PortfolioState
from core.db.catalog import Product
from core.db.marketplace_credentials import MarketplaceCredential
from core.db.portfolio import PortfolioItem
from core.db.service_credentials import ServiceCredential
from core.db.tracking import Sale
from core.db.base import Marketplace
from core.services.agent_capabilities import capabilities, health, integration_states
from core.services import agent_chat
from core.services.app_settings import agent_autonomy, agent_mode_info, set_agent_autonomy, set_agent_mode
from core.services.agent_calibration import calibration_report
from core.services.sales_sync import sync_sales
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
    autonomy: str = "supervised"  # "supervised" | "independent"


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
        autonomy=agent_autonomy(session),
    )


@router.put("/mode", response_model=AgentModeOut, summary="Ligar ou desligar a administração pelo agente")
def put_mode(
    payload: AgentModeUpdate,
    principal: Principal = Depends(require("users.manage")),
    session: Session = Depends(get_session),
) -> AgentModeOut:
    was_enabled = agent_mode_info(session)["enabled"]
    info = set_agent_mode(session, enabled=payload.enabled, actor=principal.username)
    if payload.enabled and not was_enabled:
        # Ao ligar, o agente recebe a rotina de análise completa. Ele a lê assim que uma sessão do
        # Claude conectar — o sistema não roda o Claude por conta própria.
        agent_chat.post_activation_task(session)
    elif was_enabled and not payload.enabled:
        agent_chat.post_message(
            session, author="system", kind="message",
            text="Modo agente DESLIGADO: a partir de agora você só consulta. Nenhuma ação de escrita será aceita.",
        )
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
    return integration_states(session)


@router.get("/status", summary="Estado geral para o agente decidir o que fazer")
def status(
    principal: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)
) -> dict:
    since = datetime.now(UTC) - timedelta(days=SALES_WINDOW_DAYS)
    return {
        "agent_mode": {**agent_mode_info(session), "autonomy": agent_autonomy(session)},
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


# --- Chat com o agente ----------------------------------------------------------------


class ChatPost(BaseModel):
    text: str
    kind: str = "message"
    meta: dict | None = None


class StatusUpdate(BaseModel):
    status: str


def _is_agent(principal: Principal) -> bool:
    return principal.role == AGENT_ROLE


@router.get("/chat", summary="Conversa com o agente")
def chat_list(
    after_id: int = 0,
    limit: int = 100,
    principal: Principal = Depends(require("operations.view")),
    session: Session = Depends(get_session),
) -> dict:
    return {
        "messages": [agent_chat.serialize(m) for m in agent_chat.list_messages(session, after_id=after_id, limit=limit)],
        "counts": agent_chat.counts(session),
    }


@router.post("/chat", summary="Enviar mensagem (operador) ou responder (agente)")
def chat_send(
    payload: ChatPost,
    principal: Principal = Depends(require("operations.view")),
    session: Session = Depends(get_session),
) -> dict:
    """O autor vem do papel de quem chama, nunca do corpo da requisição.

    Escrever no chat é uma instrução ao agente, então só operadores para cima escrevem como
    "user". O agente escreve como "agent" e não pode forjar alerta do sistema nem tarefa.
    """
    if _is_agent(principal):
        author = "agent"
        if payload.kind not in ("message", "request", "report"):
            raise HTTPException(status_code=422, detail="o agente só envia message, request ou report")
    else:
        if not principal.can("portfolio.manage"):
            raise HTTPException(status_code=403, detail="só operadores ou administradores falam com o agente")
        author = "user"
        if payload.kind != "message":
            raise HTTPException(status_code=422, detail="o operador envia apenas mensagens")
    if author == "agent" and payload.kind == "request":
        again = _remind_open_request(session, payload)
        if again is not None:
            session.commit()
            return {**agent_chat.serialize(again), "deduplicated": True}
    try:
        message = agent_chat.post_message(session, author=author, text=payload.text, kind=payload.kind, meta=payload.meta)
    except agent_chat.ChatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return agent_chat.serialize(message)


def _remind_open_request(session: Session, payload: "ChatPost"):
    """Pedido repetido do mesmo recurso: em vez de criar outro cartão, renova o aberto.

    É a "cobrança diária" sem spam: o cartão volta a contar como não lido (o aviso do menu
    reaparece), acumula `reminders` e guarda a data da última cobrança.
    """
    resource = ((payload.meta or {}).get("resource") or "").strip().lower()
    if not resource:
        return None
    for message in session.scalars(select(agent_chat.AgentMessage).where(
            agent_chat.AgentMessage.kind == "request", agent_chat.AgentMessage.status == "open")):
        if ((message.meta or {}).get("resource") or "").strip().lower() == resource:
            message.meta = {**(message.meta or {}), **(payload.meta or {}),
                            "reminders": int((message.meta or {}).get("reminders", 0)) + 1,
                            "last_reminded_at": datetime.now(UTC).isoformat()}
            message.text = payload.text
            message.read_by_user = False
            session.flush()
            return message
    return None


@router.post("/chat/read", summary="Marcar como lido (para quem chama)")
def chat_mark_read(
    principal: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)
) -> dict:
    changed = agent_chat.mark_read(session, "agent" if _is_agent(principal) else "user")
    session.commit()
    return {"marked": changed, "counts": agent_chat.counts(session)}


@router.get("/chat/inbox", summary="Caixa de entrada do agente (marca como lido)")
def chat_inbox(
    principal: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)
) -> dict:
    inbox = agent_chat.agent_inbox(session)
    session.commit()
    return {
        "unread": [agent_chat.serialize(m) for m in inbox["unread"]],
        "open_tasks": [agent_chat.serialize(m) for m in inbox["open_tasks"]],
    }


@router.patch("/chat/{message_id}", summary="Resolver ou dispensar um pedido/tarefa")
def chat_set_status(
    message_id: int,
    payload: StatusUpdate,
    principal: Principal = Depends(require("operations.view")),
    session: Session = Depends(get_session),
) -> dict:
    """O operador resolve ou dispensa pedidos; o agente só conclui as próprias tarefas."""
    message = session.get(agent_chat.AgentMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail=f"mensagem {message_id} não encontrada")
    if _is_agent(principal):
        if message.kind != "task" or payload.status != "done":
            raise HTTPException(status_code=403, detail="o agente só pode concluir tarefas")
    elif not principal.can("portfolio.manage"):
        raise HTTPException(status_code=403, detail="sem permissão")
    try:
        updated = agent_chat.set_status(session, message_id, payload.status)
    except agent_chat.ChatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return agent_chat.serialize(updated)


# --- Capacidades, saúde e vendas ----------------------------------------------------------


@router.get("/capabilities", summary="O que está pronto, o que falta configurar e o que ainda não foi construído")
def get_capabilities(
    principal: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)
) -> dict:
    items = capabilities(session)
    return {
        "capabilities": items,
        "summary": {s: sum(1 for i in items if i["status"] == s) for s in ("pronto", "configurar", "nao_construido")},
    }


@router.get("/health", summary="Saúde do sistema")
def get_health(
    principal: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)
) -> dict:
    return health(session)


@router.post("/sales/sync", summary="Sincronizar vendas dos marketplaces e avisar as novas")
def sales_sync(
    since_days: int = 30,
    principal: Principal = Depends(require("portfolio.manage")),
    session: Session = Depends(get_session),
) -> dict:
    result = sync_sales(session, get_adapters(), since_days=max(1, min(since_days, 90)))
    record_action(
        session, principal, action="agent.sales_synced", resource_type="sale",
        detail=f"{result['new_sales']} venda(s) nova(s)",
    )
    session.commit()
    return result


# --- Calibragem e autonomia ----------------------------------------------------------------


@router.get("/calibration", summary="Relatório de calibragem do agente (só administrador)")
def get_calibration(
    principal: Principal = Depends(require("audit.view")), session: Session = Depends(get_session)
) -> dict:
    return calibration_report(session)


class AutonomyUpdate(BaseModel):
    level: str
    force: bool = False


@router.put("/autonomy", summary="Liberar o agente para trabalhar de forma independente (ou voltar a supervisionado)")
def put_autonomy(
    payload: AutonomyUpdate,
    principal: Principal = Depends(require("users.manage")),
    session: Session = Depends(get_session),
) -> dict:
    """`independent` só com a calibragem aprovada, a menos que o administrador force (fica registrado)."""
    if payload.level not in ("supervised", "independent"):
        raise HTTPException(status_code=422, detail="nível deve ser 'supervised' ou 'independent'")
    report = calibration_report(session)
    if payload.level == "independent" and not report["ready_for_independence"] and not payload.force:
        raise HTTPException(status_code=409, detail={
            "message": "o agente ainda não passou na calibragem: " + report["summary"], "stage": report["stage"]})
    level = set_agent_autonomy(session, level=payload.level, actor=principal.username)
    record_action(session, principal, action="agent.autonomy_changed", resource_type="setting",
                  resource_id="agent_autonomy",
                  detail=f"{level}" + (" (forçado, sem calibragem aprovada)" if payload.force and not report["ready_for_independence"] else ""))
    text = (
        "Agente LIBERADO para trabalhar de forma independente: roda as rotinas da manhã e da noite sozinho, cobra os "
        "recursos pendentes uma vez por dia e só interrompe você quando precisar de uma decisão ou de um acesso."
        if level == "independent"
        else "Agente voltou ao modo SUPERVISIONADO: explique cada decisão no chat e espere a sua aprovação antes de "
        "ações com efeito (vincular, mover estado, remover)."
    )
    agent_chat.post_message(session, author="system", kind="message", text=text)
    session.commit()
    return {"autonomy": level, "calibration": report}
