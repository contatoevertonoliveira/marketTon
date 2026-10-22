"""Comissão Extra do vendedor (Shopee): quanto é, até quando vale e se ainda dá para confiar nela.

A API de afiliados devolve a comissão extra paga pelo vendedor (`sellerCommissionRate`) e o período da oferta
(`periodStartTime`/`periodEndTime`). Comissão extra é de campanha: quando acaba, a taxa cai. O coletor guarda os dois;
aqui se decide o que dizer ao operador e ao agente — sem inventar prazo que a API não deu.
"""
from __future__ import annotations

from datetime import UTC, datetime

SOON_DAYS = 3  # faltando pouco, vale avisar antes de investir conteúdo


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def offer_info(attributes: dict | None, now: datetime | None = None) -> dict | None:
    """Resumo da comissão extra de um produto, ou `None` se ele não tem comissão extra do vendedor.

    `sem_oferta`: a Shopee deixou de devolver o item como oferta de afiliado (ver `offer_not_found_at`).
    `status`: `ativa` (dentro do prazo), `acabando` (poucos dias), `expirada`, `futura`, `sem_fim` (começou e a API não
    marca data de término — o vendedor pode encerrar quando quiser) ou `sem_prazo` (a API não informou o período: o
    catálogo precisa ser recoletado, não se chuta).
    """
    attributes = attributes or {}
    extra = attributes.get("seller_commission_pct")
    if not extra or extra <= 0:
        return None
    now = now or datetime.now(UTC)
    if attributes.get("offer_not_found_at"):  # a consulta por ID não devolveu oferta de afiliado para o item
        return {"extra_pct": round(float(extra), 2), "starts_at": None, "ends_at": None, "status": "sem_oferta", "days_left": None}
    starts, ends = _parse(attributes.get("offer_starts_at")), _parse(attributes.get("offer_ends_at"))
    days_left = None
    if ends is None and starts is None:
        status = "sem_prazo"
    elif starts is not None and now < starts:
        status = "futura"
    elif ends is None:
        status = "sem_fim"
    elif ends is not None and now > ends:
        status = "expirada"
    else:
        status = "ativa"
        if ends is not None:
            days_left = max(0, (ends - now).days)
            if days_left <= SOON_DAYS:
                status = "acabando"
    return {
        "extra_pct": round(float(extra), 2),
        "starts_at": starts.isoformat() if starts else None,
        "ends_at": ends.isoformat() if ends else None,
        "status": status,
        "days_left": days_left,
    }


def offer_note(info: dict | None) -> str | None:
    """Aviso em português quando a comissão anunciada não é segura para planejar conteúdo; `None` se está tudo certo."""
    if info is None:
        return None
    ends = (info["ends_at"] or "")[:10]
    br = "/".join(reversed(ends.split("-"))) if ends else ""
    return {
        "expirada": f"A comissão extra de {info['extra_pct']:g}% acabou em {br}: a taxa real pode ter caído. "
                    "Confira no portal de afiliados antes de investir conteúdo.",
        "acabando": f"A comissão extra de {info['extra_pct']:g}% acaba em {br} ({info['days_left']} dia(s)). "
                    "Conteúdo novo pode sair depois do fim da oferta.",
        "futura": f"A comissão extra de {info['extra_pct']:g}% só começa em {br or 'data futura'}.",
        "sem_oferta": f"A Shopee não devolveu oferta de afiliado para este item na última verificação: a comissão de "
                      f"{info['extra_pct']:g}% pode não valer mais. Confira no portal antes de investir conteúdo.",
        "sem_prazo": f"Comissão extra de {info['extra_pct']:g}% sem prazo informado: recolha o catálogo para saber até quando vale "
                     "e confira a taxa no portal antes de investir conteúdo.",
    }.get(info["status"])
