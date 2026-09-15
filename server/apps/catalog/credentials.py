"""Declarative credential schemas per marketplace (Fase 2).

Each marketplace has its own auth scheme ("de acordo com o critério de cada
um"): OAuth2 for Mercado Livre, a signed partner key for Shopee, AWS keys for
Amazon. This module is the single place that knows the field list for each —
both the API (to build `credential_status` without ever echoing a secret
back) and the frontend (to render the right form) read from here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    secret: bool = False


CREDENTIAL_SCHEMAS: dict[str, list[CredentialField]] = {
    "mercado_livre": [
        CredentialField("client_id", "Client ID"),
        CredentialField("client_secret", "Client Secret", secret=True),
        CredentialField("redirect_uri", "Redirect URI"),
        CredentialField("access_token", "Access Token", secret=True),
        CredentialField("refresh_token", "Refresh Token", secret=True),
        CredentialField("country", "País"),
    ],
    "shopee": [
        CredentialField("app_id", "App ID"),
        CredentialField("secret", "Secret", secret=True),
        CredentialField("region", "Região (ex.: BR)"),
    ],
    "amazon": [
        CredentialField("access_key", "Access Key"),
        CredentialField("secret_key", "Secret Key", secret=True),
        CredentialField("associate_tag", "Associate Tag"),
        CredentialField("region", "Região AWS (ex.: us-east-1)"),
        CredentialField("host", "Host da API (ex.: webservices.amazon.com.br)"),
        CredentialField("marketplace_domain", "Domínio da marketplace (ex.: www.amazon.com.br)"),
    ],
}


def schema_for(slug: str) -> list[CredentialField]:
    return CREDENTIAL_SCHEMAS.get(slug, [])


def status_for(slug: str, values: dict) -> dict[str, bool]:
    return {f.name: bool(values.get(f.name)) for f in schema_for(slug)}


def schema_as_dicts(slug: str) -> list[dict]:
    return [{"name": f.name, "label": f.label, "secret": f.secret} for f in schema_for(slug)]
