"""Credenciais de serviços de dados (Google Ads) — a tela de Integrações.

Mesmas regras de `marketplaces.py`: segredo nunca volta pela API (só "está
preenchido ou não"), string vazia no PUT mantém o valor salvo, e o semáforo
vem de uma chamada de teste *real*, não de "os campos estão preenchidos".
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import require
from core.db.service_credentials import ServiceCredential
from core.services import ads_budget, link_shortener, meta_ads, storefront
from integrations.google_ads import DEFAULT_API_VERSION, GoogleAdsClient, GoogleAdsConfig, GoogleAdsError

router = APIRouter(
    prefix="/integrations/services",
    tags=["serviços de dados"],
    dependencies=[Depends(require("connectors.manage"))],
)

SERVICES: dict[str, dict] = {
    "google_ads": {
        "icon": "🔎",
        "required": ["client_id", "client_secret", "refresh_token", "customer_id"],
        "name": "Google Ads (Planejador de Palavras-chave)",
        "description": "Volume de busca mensal, CPC e concorrência no Google. O Trends não passa por aqui.",
        "fields": [
            {"name": "developer_token", "label": "Developer Token (opcional — o Google desativou em 09/09/2026)", "secret": True},
            {"name": "client_id", "label": "Client ID (OAuth)", "secret": False},
            {"name": "client_secret", "label": "Client Secret (OAuth)", "secret": True},
            {"name": "refresh_token", "label": "Refresh Token", "secret": True},
            {"name": "customer_id", "label": "Customer ID da conta (10 dígitos, sem traços)", "secret": False},
            {"name": "login_customer_id", "label": "ID da conta MCC (opcional — só se a conta for gerenciada por ela)", "secret": False},
            {"name": "api_version", "label": f"Versão da API (padrão {DEFAULT_API_VERSION})", "secret": False},
        ],
    },
    "meta_ads": {
        "icon": "📣",
        "required": ["access_token", "ad_account_id", "page_id"],
        "name": "Meta (Facebook, Instagram e Anúncios)",
        "description": "Conecta o agente à Página do Mural na Web e à conta de anúncios para publicar, testar criativos e ler as métricas.",
        "help": "Como pegar: (1) no Gerenciador de Negócios, crie um Usuário do sistema e dê a ele a Página e a conta de anúncios; "
                "(2) gere o token com as permissões ads_management, ads_read e pages_read_engagement (escolha \"sem validade\"); "
                "(3) cole o token aqui. O ID da conta de anúncios (act_…) fica no Gerenciador de Anúncios e o ID da Página em Sobre. "
                "App ID e App Secret (opcionais) deixam o teste conferir as permissões. O teste só LÊ: nada é publicado nem gasto. "
                "Criar campanhas e publicar posts vêm na próxima etapa, sempre dentro do orçamento definido em \"Orçamento de anúncios\".",
        "fields": [
            {"name": "access_token", "label": "Token de acesso do usuário do sistema", "secret": True},
            {"name": "ad_account_id", "label": "ID da conta de anúncios (act_123… ou só os números)", "secret": False},
            {"name": "page_id", "label": "ID da Página do Facebook (Mural na Web)", "secret": False},
            {"name": "instagram_business_id", "label": "ID da conta profissional do Instagram (opcional)", "secret": False},
            {"name": "app_id", "label": "ID do app da Meta (opcional, para conferir permissões)", "secret": False},
            {"name": "app_secret", "label": "Chave secreta do app da Meta (opcional)", "secret": True},
        ],
    },
    "ads_budget": {
        "icon": "💰",
        "required": ["weekly_brl", "daily_cap_brl"],
        "name": "Orçamento de anúncios (travas de gasto)",
        "description": "Quanto o agente pode gastar testando anúncios. Só você altera estes valores: o agente não tem acesso a este cartão.",
        "help": "O agente propõe o plano da semana dentro destes limites e precisa da sua aprovação no chat antes de gastar. "
                "Campanha nova sempre nasce pausada. O teto por dia não pode passar do valor da semana. \"Testar\" só confere os números.",
        "fields": [
            {"name": "weekly_brl", "label": "Valor por semana em R$ (ex.: 150)", "secret": False},
            {"name": "daily_cap_brl", "label": "Teto por dia em R$ (ex.: 30)", "secret": False},
            {"name": "max_products", "label": "Produtos testados por semana (padrão 3)", "secret": False},
            {"name": "creatives_per_product", "label": "Criativos por produto (padrão 2)", "secret": False},
        ],
    },
    "storefront": {
        "icon": "🛍️",
        "required": ["base_url", "admin_token"],
        "name": "Vitrine pública (loja online)",
        "help": "O teste confere o endereço e o token da vitrine. Depois de conectado, a página Vitrine do marketTon publica os produtos na loja.",
        "description": "A loja pública Mural na Web. O marketTon envia a ela a lista de "
                       "produtos escolhidos; ela fica no ar mesmo com o computador desligado.",
        "fields": [
            {"name": "base_url", "label": "Endereço do site onde estão as funções da loja (https://seudominio.com.br)", "secret": False},
            {"name": "admin_token", "label": "Token administrativo da vitrine", "secret": True},
            {"name": "public_url", "label": "Endereço público da loja (opcional; padrão: endereço do site + /loja)", "secret": False},
        ],
    },
    "link_shortener": {
        "icon": "🔗",
        "required": ["base_url", "admin_token"],
        "name": "Encurtador de links (contador de cliques)",
        "help": "O teste confere o endereço e o token junto ao redirecionador. Os links curtos ficam em endereço/r/código; cada clique de pessoa (não de robô) é contado sem guardar IP nem cookie.",
        "description": "Links curtos no seu domínio que contam os cliques das divulgações. O redirecionador roda no Netlify "
                       "(felixsystems.com.br/r/…), então conta mesmo com o computador desligado.",
        "fields": [
            {"name": "base_url", "label": "Endereço público do redirecionador (https://seudominio.com.br)", "secret": False},
            {"name": "admin_token", "label": "Token administrativo do redirecionador", "secret": True},
        ],
    },
}


class ServiceUpdate(BaseModel):
    enabled: bool = True
    values: dict[str, str] = Field(default_factory=dict)


class ServiceStatusOut(BaseModel):
    service: str
    name: str
    description: str
    icon: str = "🔌"
    help: str = ""
    enabled: bool
    fields: list[dict[str, str | bool]]
    values_set: dict[str, bool]
    configured: bool
    last_check_status: str | None = None
    last_check_message: str | None = None
    last_check_at: str | None = None


def _row(session: Session, service: str) -> ServiceCredential:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == service))
    if row is None:
        row = ServiceCredential(service=service, enabled=True, values={})
        session.add(row)
        session.flush()
    return row


def _status(service: str, row: ServiceCredential) -> ServiceStatusOut:
    meta = SERVICES[service]
    configured = all(bool((row.values or {}).get(f)) for f in meta["required"])
    return ServiceStatusOut(
        service=service,
        icon=meta["icon"],
        help=meta.get("help", ""),
        name=meta["name"],
        description=meta["description"],
        enabled=row.enabled,
        fields=meta["fields"],
        values_set={f["name"]: bool(row.values.get(f["name"])) for f in meta["fields"]},
        configured=configured,
        last_check_status=row.last_check_status,
        last_check_message=row.last_check_message,
        last_check_at=row.last_check_at.isoformat() if row.last_check_at else None,
    )


def _known(service: str) -> dict:
    if service not in SERVICES:
        raise HTTPException(status_code=404, detail=f"serviço '{service}' desconhecido")
    return SERVICES[service]


@router.get("", response_model=list[ServiceStatusOut])
def list_services(session: Session = Depends(get_session)) -> list[ServiceStatusOut]:
    rows = {r.service: r for r in session.scalars(select(ServiceCredential))}
    return [
        _status(slug, rows.get(slug) or ServiceCredential(service=slug, enabled=False, values={}))
        for slug in SERVICES
    ]


@router.put("/{service}", response_model=ServiceStatusOut)
def update_service(service: str, payload: ServiceUpdate, session: Session = Depends(get_session)) -> ServiceStatusOut:
    meta = _known(service)
    row = _row(session, service)
    row.enabled = payload.enabled
    known = {f["name"] for f in meta["fields"]}
    merged = dict(row.values)
    changed = False
    for key, value in payload.values.items():
        if key in known and value.strip():
            merged[key] = value.strip()
            changed = True
    row.values = merged
    if changed:
        # Credencial mudou: o teste anterior não vale mais.
        row.last_check_status = row.last_check_message = row.last_check_at = None
    session.commit()
    session.refresh(row)
    return _status(service, row)


@router.post("/{service}/test", response_model=ServiceStatusOut)
def test_service(service: str, session: Session = Depends(get_session)) -> ServiceStatusOut:
    _known(service)
    row = _row(session, service)
    try:
        if service == "google_ads":
            message = GoogleAdsClient(GoogleAdsConfig.from_values(row.values)).check()
        elif service == "meta_ads":
            message = meta_ads.check(row.values or {})
        elif service == "ads_budget":
            message = ads_budget.check(row.values or {})
        elif service == "storefront":
            values = row.values or {}
            message = storefront.check(storefront.StoreConfig(
                str(values.get("base_url") or "").strip().rstrip("/"), str(values.get("admin_token") or "").strip(),
                str(values.get("public_url") or "").strip().rstrip("/")))
        else:
            values = row.values or {}
            message = link_shortener.check(link_shortener.ShortenerConfig(
                str(values.get("base_url") or "").strip().rstrip("/"), str(values.get("admin_token") or "").strip()))
        status = "ok"
    except (GoogleAdsError, link_shortener.ShortenerError, storefront.StorefrontError, meta_ads.MetaError,
            ads_budget.BudgetError) as exc:
        status, message = "error", str(exc)[:480]
    row.last_check_status = status
    row.last_check_message = message
    row.last_check_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return _status(service, row)
