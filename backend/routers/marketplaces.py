"""Credenciais de marketplace, editáveis em tempo de execução (briefing §2).

A permissão `connectors.manage` já existia em `core/roles.py` mas não tinha
endpoint nenhum atrás dela — esta é a peça que faltava. Cada marketplace tem
seu próprio esquema de autenticação (`CREDENTIAL_FIELDS`), e os nomes de campo
aqui correspondem exatamente aos atributos dos dataclasses `MLConfig` /
`ShopeeConfig` / `AmazonConfig` / `TikTokShopConfig` em
`integrations/marketplaces/*.py`, porque é nesses objetos que
`backend/deps.py::get_adapters()` aplica o valor salvo.

Um valor secreto nunca é devolvido pela API — só se o campo está preenchido ou
não (`values_set`). Enviar uma string vazia no PUT não apaga o valor salvo: é
assim que a tela consegue reenviar o formulário inteiro sem precisar saber o
segredo atual.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.deps import get_adapters, get_session
from backend.security import require
from core.db.base import Marketplace
from core.db.commission_rates import CommissionRate
from core.db.marketplace_credentials import MarketplaceCredential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/marketplaces", tags=["marketplaces"])

CREDENTIAL_FIELDS: dict[str, list[dict[str, str | bool]]] = {
    "mercado_livre": [
        {"name": "client_id", "label": "Client ID", "secret": False},
        {"name": "client_secret", "label": "Client Secret", "secret": True},
        {"name": "redirect_uri", "label": "Redirect URI", "secret": False},
    ],
    "shopee": [
        {"name": "app_id", "label": "App ID", "secret": False},
        {"name": "secret", "label": "Secret", "secret": True},
    ],
    "amazon": [
        {"name": "client_id", "label": "Client ID", "secret": False},
        {"name": "client_secret", "label": "Client Secret", "secret": True},
        {"name": "partner_tag", "label": "Partner Tag (Associate Tag)", "secret": False},
        {"name": "marketplace", "label": "Domínio da loja (ex.: www.amazon.com.br)", "secret": False},
    ],
    "tiktok_shop": [
        {"name": "app_key", "label": "App Key", "secret": False},
        {"name": "app_secret", "label": "App Secret", "secret": True},
        {"name": "shop_cipher", "label": "Shop Cipher", "secret": False},
    ],
}


class CredentialUpdate(BaseModel):
    enabled: bool = True
    values: dict[str, str] = Field(default_factory=dict)


class CredentialStatusOut(BaseModel):
    marketplace: str
    enabled: bool
    fields: list[dict[str, str | bool]]
    values_set: dict[str, bool]
    configured: bool | None = None
    reliability: float | None = None


def _get_or_create(session: Session, marketplace: Marketplace) -> MarketplaceCredential:
    row = session.scalar(select(MarketplaceCredential).where(MarketplaceCredential.marketplace == marketplace))
    if row is None:
        row = MarketplaceCredential(marketplace=marketplace, enabled=True, values={})
        session.add(row)
        session.flush()
    return row


@router.get("/credentials", response_model=list[CredentialStatusOut], dependencies=[Depends(require("connectors.manage"))])
def list_credentials(session: Session = Depends(get_session)) -> list[CredentialStatusOut]:
    rows = {row.marketplace.value: row for row in session.scalars(select(MarketplaceCredential))}
    adapters = get_adapters()
    out: list[CredentialStatusOut] = []
    for slug, fields in CREDENTIAL_FIELDS.items():
        row = rows.get(slug)
        values = row.values if row else {}
        adapter = adapters.get(slug)
        configured = None
        reliability = None
        if adapter is not None:
            try:
                configured = adapter.is_configured()
                reliability = adapter.reliability
            except Exception as exc:  # noqa: BLE001 - status nunca deve derrubar a tela
                logger.warning("falha ao consultar status de %s: %s", slug, exc)
        out.append(
            CredentialStatusOut(
                marketplace=slug,
                enabled=row.enabled if row else False,
                fields=fields,
                values_set={f["name"]: bool(values.get(f["name"])) for f in fields},
                configured=configured,
                reliability=reliability,
            )
        )
    return out


@router.put(
    "/{marketplace}/credentials",
    response_model=CredentialStatusOut,
    dependencies=[Depends(require("connectors.manage"))],
)
def update_credentials(
    marketplace: Marketplace, payload: CredentialUpdate, session: Session = Depends(get_session)
) -> CredentialStatusOut:
    fields = CREDENTIAL_FIELDS.get(marketplace.value)
    if fields is None:
        raise HTTPException(status_code=404, detail=f"'{marketplace.value}' não tem esquema de credenciais")

    row = _get_or_create(session, marketplace)
    row.enabled = payload.enabled
    merged = dict(row.values)
    known_names = {f["name"] for f in fields}
    for key, value in payload.values.items():
        if key in known_names and value:
            merged[key] = value
    row.values = merged
    session.commit()
    session.refresh(row)

    return CredentialStatusOut(
        marketplace=marketplace.value,
        enabled=row.enabled,
        fields=fields,
        values_set={f["name"]: bool(row.values.get(f["name"])) for f in fields},
    )


# --- Mercado Livre: fluxo OAuth ------------------------------------------------


@router.post("/mercado_livre/oauth/start", dependencies=[Depends(require("connectors.manage"))])
def start_mercado_livre_oauth(session: Session = Depends(get_session)) -> dict:
    row = _get_or_create(session, Marketplace.MERCADO_LIVRE)
    if not row.values.get("client_id") or not row.values.get("redirect_uri"):
        raise HTTPException(
            status_code=400, detail="configure client_id e redirect_uri antes de conectar"
        )
    state = secrets.token_urlsafe(16)
    # PKCE (RFC 7636): alguns apps da Mercado Livre exigem `code_verifier` na
    # troca do código por token. Gerado aqui, guardado até o callback, nunca
    # exposto ao navegador — só o hash (`code_challenge`) vai na URL.
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    row.oauth_state = state
    row.oauth_code_verifier = code_verifier
    session.commit()

    adapters = get_adapters()
    adapter = adapters.get("mercado_livre")
    if adapter is None:
        raise HTTPException(status_code=500, detail="adapter mercado_livre não registrado")
    url = adapter.build_authorization_url(state, code_challenge=code_challenge)
    return {"ok": True, "url": url, "redirect_uri": row.values.get("redirect_uri")}


def _oauth_page(message: str) -> Response:
    html = f"<html><body style='font-family:sans-serif;padding:40px;max-width:480px'><h3>{message}</h3></body></html>"
    return Response(content=html, media_type="text/html")


@router.get("/mercado_livre/oauth/callback", include_in_schema=False)
def mercado_livre_oauth_callback(
    code: str | None = None, state: str | None = None, session: Session = Depends(get_session)
) -> Response:
    """Alvo do redirect da própria Mercado Livre — sem `require(...)`, pois quem
    bate aqui é o navegador do operador voltando do login da ML, não o SPA com
    um Bearer token. A defesa contra forjar essa chamada é o `state` assinado."""
    row = session.scalar(
        select(MarketplaceCredential).where(MarketplaceCredential.marketplace == Marketplace.MERCADO_LIVRE)
    )
    if not code or row is None:
        return _oauth_page("Falha: código ausente ou Mercado Livre ainda não configurado.")
    if not state or state != row.oauth_state:
        return _oauth_page("Falha: state inválido (link expirado ou reutilizado).")

    adapters = get_adapters()
    adapter = adapters.get("mercado_livre")
    if adapter is None:
        return _oauth_page("Falha: adapter mercado_livre não registrado.")

    try:
        adapter.exchange_code_for_token(code, code_verifier=row.oauth_code_verifier)
    except Exception as exc:  # noqa: BLE001 - reportar na página, não estourar 500 pro navegador
        logger.warning("troca de token da Mercado Livre falhou: %s", exc)
        return _oauth_page(f"Falha ao trocar o código por token: {exc}")

    row.oauth_state = None
    row.oauth_code_verifier = None
    session.commit()
    return _oauth_page("Conectado com sucesso! Pode fechar esta aba e voltar ao painel.")


# --- Comissão por categoria (informada pelo operador) ---------------------------


class CommissionRow(BaseModel):
    category_id: str
    name: str
    rate_pct: float | None = None


class CommissionUpdate(BaseModel):
    # `None` remove a taxa daquela categoria.
    rates: dict[str, float | None]


@router.get(
    "/mercado_livre/commissions",
    response_model=list[CommissionRow],
    dependencies=[Depends(require("connectors.manage"))],
)
def list_mercado_livre_commissions(session: Session = Depends(get_session)) -> list[CommissionRow]:
    """Categorias de topo da ML + a taxa que o operador cadastrou (se houver)."""
    adapter = get_adapters().get("mercado_livre")
    if adapter is None:
        raise HTTPException(status_code=500, detail="adapter mercado_livre não registrado")
    try:
        categories = adapter._api_get(f"/sites/{adapter.cfg.site_id}/categories") or []
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"não foi possível listar categorias: {exc}") from exc
    saved = {
        row.category_id: row.rate_pct
        for row in session.scalars(
            select(CommissionRate).where(CommissionRate.marketplace == Marketplace.MERCADO_LIVRE)
        )
    }
    return [
        CommissionRow(category_id=str(c["id"]), name=c.get("name", ""), rate_pct=saved.get(str(c["id"])))
        for c in categories
        if c.get("id")
    ]


@router.put("/mercado_livre/commissions", dependencies=[Depends(require("connectors.manage"))])
def update_mercado_livre_commissions(payload: CommissionUpdate, session: Session = Depends(get_session)) -> dict:
    for category_id, rate in payload.rates.items():
        if rate is not None and not 0 <= rate <= 100:
            raise HTTPException(status_code=422, detail=f"taxa inválida para {category_id}: {rate}")
    existing = {
        row.category_id: row
        for row in session.scalars(
            select(CommissionRate).where(CommissionRate.marketplace == Marketplace.MERCADO_LIVRE)
        )
    }
    for category_id, rate in payload.rates.items():
        row = existing.get(category_id)
        if rate is None:
            if row is not None:
                session.delete(row)
        elif row is None:
            session.add(CommissionRate(marketplace=Marketplace.MERCADO_LIVRE, category_id=category_id, rate_pct=rate))
        else:
            row.rate_pct = rate
    session.commit()
    return {"ok": True, "updated": len(payload.rates)}
