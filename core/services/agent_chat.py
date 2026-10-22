"""Chat e fila do agente: regras de leitura, não-lido e status."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.db.agent_chat import AUTHORS, KINDS, STATUSES, AgentMessage

MAX_TEXT = 8000


class ChatError(ValueError):
    """Pedido inválido ao chat. A mensagem é segura para exibir."""


def post_message(
    session: Session,
    *,
    author: str,
    text: str,
    kind: str = "message",
    meta: dict | None = None,
) -> AgentMessage:
    if author not in AUTHORS:
        raise ChatError(f"autor inválido: {author}")
    if kind not in KINDS:
        raise ChatError(f"tipo inválido: {kind}")
    text = (text or "").strip()
    if not text:
        raise ChatError("a mensagem está vazia")
    if len(text) > MAX_TEXT:
        raise ChatError(f"a mensagem passa de {MAX_TEXT} caracteres")

    message = AgentMessage(
        author=author,
        kind=kind,
        text=text,
        meta=meta,
        status="open" if kind in ("request", "task") else None,
        # Quem escreve já leu a própria mensagem; o outro lado ainda não.
        read_by_user=author == "user",
        read_by_agent=author == "agent",
    )
    session.add(message)
    session.flush()
    return message


def list_messages(session: Session, *, after_id: int = 0, limit: int = 100) -> list[AgentMessage]:
    """Com `after_id`, só o que veio depois (para atualizar a tela). Sem ele, as últimas `limit`."""
    limit = max(1, min(limit, 500))
    if after_id:
        stmt = select(AgentMessage).where(AgentMessage.id > after_id).order_by(AgentMessage.id).limit(limit)
        return list(session.scalars(stmt))
    recent = list(session.scalars(select(AgentMessage).order_by(AgentMessage.id.desc()).limit(limit)))
    return list(reversed(recent))


def counts(session: Session) -> dict:
    def count(*where) -> int:
        return session.scalar(select(func.count()).select_from(AgentMessage).where(*where)) or 0

    return {
        "unread_for_user": count(AgentMessage.read_by_user.is_(False)),
        "unread_for_agent": count(AgentMessage.read_by_agent.is_(False)),
        "open_requests": count(AgentMessage.kind == "request", AgentMessage.status == "open"),
        "open_tasks": count(AgentMessage.kind == "task", AgentMessage.status == "open"),
    }


def mark_read(session: Session, reader: str) -> int:
    """Marca como lido para `user` ou `agent`. Devolve quantas mudaram."""
    column = {"user": AgentMessage.read_by_user, "agent": AgentMessage.read_by_agent}.get(reader)
    if column is None:
        raise ChatError(f"leitor inválido: {reader}")
    rows = list(session.scalars(select(AgentMessage).where(column.is_(False))))
    for row in rows:
        setattr(row, "read_by_user" if reader == "user" else "read_by_agent", True)
    session.flush()
    return len(rows)


def set_status(session: Session, message_id: int, status: str) -> AgentMessage:
    if status not in STATUSES:
        raise ChatError(f"status inválido: {status}")
    message = session.get(AgentMessage, message_id)
    if message is None:
        raise ChatError(f"mensagem {message_id} não encontrada")
    if message.kind not in ("request", "task"):
        raise ChatError("só pedidos e tarefas têm status")
    message.status = status
    session.flush()
    return message


def agent_inbox(session: Session) -> dict:
    """O que o agente precisa ler agora: mensagens novas do usuário/sistema e tarefas abertas.

    Ler marca como lido para o agente — por isso a ferramenta existe separada da listagem.
    """
    unread = list(session.scalars(
        select(AgentMessage).where(AgentMessage.read_by_agent.is_(False)).order_by(AgentMessage.id)
    ))
    open_tasks = list(session.scalars(
        select(AgentMessage).where(AgentMessage.kind == "task", AgentMessage.status == "open").order_by(AgentMessage.id)
    ))
    mark_read(session, "agent")
    return {"unread": unread, "open_tasks": open_tasks}


def serialize(message: AgentMessage) -> dict:
    return {
        "id": message.id,
        "author": message.author,
        "kind": message.kind,
        "text": message.text,
        "meta": message.meta,
        "status": message.status,
        "read_by_user": message.read_by_user,
        "read_by_agent": message.read_by_agent,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


ACTIVATION_TASK = "activation_routine"

ACTIVATION_TEXT = (
    "Modo agente ATIVADO. Execute agora a rotina de ativação, nesta ordem:\n"
    "1) `system_health`, `marketton_status` e `marketton_checklist`: o sistema está saudável e atualizado?\n"
    "2) `sync_sales` para trazer as vendas mais recentes e `apply_observed_commissions` se houver comissão a aprender.\n"
    "3) Análise completa do catálogo e do portfólio: use `list_products`, `product_funnel` nos melhores candidatos "
    "(demanda, concorrência, comissão por venda, vendedor, logística) e `trending_abroad` / `search_opportunities`.\n"
    "4) Escolha os produtos com maior chance de venda; explique cada escolha com os dados e vincule os aprovados "
    "(`add_to_portfolio`).\n"
    "5) Poste aqui um relatório (`chat_send` com kind=report) e, para cada recurso que falta, um pedido "
    "(`request_resource`). Use `capabilities` para saber o que está pronto, o que precisa de configuração e o que ainda "
    "não foi construído.\n"
    "Leia `agent_playbook` antes de começar."
)


def post_activation_task(session: Session) -> AgentMessage | None:
    """Cria a tarefa de ativação, se ainda não houver uma aberta."""
    exists = session.scalar(
        select(AgentMessage.id).where(
            AgentMessage.kind == "task", AgentMessage.status == "open", AgentMessage.meta["task"].as_string() == ACTIVATION_TASK
        )
    )
    if exists:
        return None
    return post_message(session, author="system", kind="task", text=ACTIVATION_TEXT, meta={"task": ACTIVATION_TASK})


def upsert_open_request(session: Session, *, text: str, meta: dict, author: str = "system") -> tuple[AgentMessage, bool]:
    """Cria o pedido ou, se já há um aberto para o mesmo recurso, renova em vez de duplicar.

    Devolve `(mensagem, renovada)`. Renovar volta o cartão a não lido e conta a cobrança.
    """
    from datetime import UTC, datetime

    resource = str(meta.get("resource") or "").strip().lower()
    if resource:
        for message in session.scalars(select(AgentMessage).where(AgentMessage.kind == "request", AgentMessage.status == "open")):
            if str((message.meta or {}).get("resource") or "").strip().lower() == resource:
                message.meta = {**(message.meta or {}), **meta,
                                "reminders": int((message.meta or {}).get("reminders", 0)) + 1,
                                "last_reminded_at": datetime.now(UTC).isoformat()}
                message.text = text
                message.read_by_user = False
                session.flush()
                return message, True
    return post_message(session, author=author, kind="request", text=text, meta=meta), False
