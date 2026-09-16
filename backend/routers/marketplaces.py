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

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.deps import get_adapters, get_session
from backend.security import require
from core.db.base import Marketplace
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
        {"name": "partner_id", "label": "Partner ID", "secret": False},
        {"name": "partner_key", "label": "Partner Key", "secret": True},
        {"name": "shop_id", "label": "Shop ID", "secret": False},
    ],
    "amazon": [
        {"name": "access_key", "label": "Access Key", "secret": False},
        {"name": "secret_key", "label": "Secret Key", "secret": True},
        {"name": "partner_tag", "label": "Partner Tag (Associate Tag)", "secret": False},
        {"name": "region", "label": "Região AWS (ex.: us-east-1)", "secret": False},
        {"name": "host", "label": "Host da API (ex.: webservices.amazon.com.br)", "secret": False},
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
    row.oauth_state = state
    session.commit()

    adapters = get_adapters()
    adapter = adapters.get("mercado_livre")
    if adapter is None:
        raise HTTPException(status_code=500, detail="adapter mercado_livre não registrado")
    url = adapter.build_authorization_url(state)
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
        adapter.exchange_code_for_token(code)
    except Exception as exc:  # noqa: BLE001 - reportar na página, não estourar 500 pro navegador
        logger.warning("troca de token da Mercado Livre falhou: %s", exc)
        return _oauth_page(f"Falha ao trocar o código por token: {exc}")

    row.oauth_state = None
    session.commit()
    return _oauth_page("Conectado com sucesso! Pode fechar esta aba e voltar ao painel.")
