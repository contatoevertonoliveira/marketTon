"""Assinatura de requisições das APIs de marketplace.

Cada plataforma assina de um jeito, e é a parte fácil de errar em silêncio: uma
assinatura inválida vira um 401/403 genérico sem indicar o que está errado. Por
isso a lógica fica isolada aqui, testável sem credencial nem rede.

Referência: Shopee Affiliate Open API (GraphQL) — `SHA256(app_id + timestamp +
payload + secret)`, diferente do HMAC da Shopee Open Platform (API de vendedor,
substituída por não servir a afiliação — ver `shopee.py`).

A assinatura AWS SigV4 da Amazon PA-API 5.0 foi removida daqui: a Amazon
aposentou a PA-API (confirmado ao vivo — retorna 403 "deprecated" desde
abril/maio de 2026) e a substituta, Creators API, usa OAuth2 Bearer token, sem
assinatura de requisição.
"""
from __future__ import annotations

import hashlib


class SignatureError(RuntimeError):
    """Credencial ausente ou malformada para assinar a requisição."""


def _require(value: str, name: str) -> str:
    if not value:
        raise SignatureError(f"credencial ausente: {name}")
    return value


# --- Shopee Affiliate Open API -------------------------------------------------


def shopee_affiliate_sign(app_id: str, secret: str, timestamp: int, payload: str) -> str:
    """Assinatura da Shopee Affiliate Open API (GraphQL).

    Diferente da Open Platform: aqui não é HMAC — é um hash SHA256 comum sobre
    `app_id + timestamp + payload + secret` concatenados nessa ordem, com o
    `secret` dentro da string em vez de como chave do HMAC.
    """
    base = f"{_require(app_id, 'app_id')}{timestamp}{payload}{_require(secret, 'secret')}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def shopee_affiliate_auth_header(app_id: str, secret: str, timestamp: int, payload: str) -> str:
    """Header `Authorization` completo da Shopee Affiliate Open API."""
    signature = shopee_affiliate_sign(app_id, secret, timestamp, payload)
    return f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"


__all__ = [
    "SignatureError",
    "shopee_affiliate_auth_header",
    "shopee_affiliate_sign",
]
