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
from integrations.google_ads import DEFAULT_API_VERSION, GoogleAdsClient, GoogleAdsConfig, GoogleAdsError

router = APIRouter(
    prefix="/integrations/services",
    tags=["serviços de dados"],
    dependencies=[Depends(require("connectors.manage"))],
)

SERVICES: dict[str, dict] = {
    "google_ads": {
        "name": "Google Ads (Planejador de Palavras-chave)",
        "description": "Volume de busca mensal, CPC e concorrência no Google. O Trends não passa por aqui.",
        "fields": [
            {"name": "developer_token", "label": "Developer Token (Central de API da conta MCC)", "secret": True},
            {"name": "client_id", "label": "Client ID (OAuth)", "secret": False},
            {"name": "client_secret", "label": "Client Secret (OAuth)", "secret": True},
            {"name": "refresh_token", "label": "Refresh Token", "secret": True},
            {"name": "customer_id", "label": "Customer ID da conta (10 dígitos, sem traços)", "secret": False},
            {"name": "login_customer_id", "label": "ID da conta MCC (opcional — só se a conta for gerenciada por ela)", "secret": False},
            {"name": "api_version", "label": f"Versão da API (padrão {DEFAULT_API_VERSION})", "secret": False},
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
    configured = GoogleAdsConfig.from_values(row.values).is_complete() if service == "google_ads" else False
    return ServiceStatusOut(
        service=service,
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
        message = GoogleAdsClient(GoogleAdsConfig.from_values(row.values)).check()
        status = "ok"
    except GoogleAdsError as exc:
        status, message = "error", str(exc)[:480]
    row.last_check_status = status
    row.last_check_message = message
    row.last_check_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return _status(service, row)
