"""Assinatura de requisições das APIs de marketplace.

Cada plataforma assina de um jeito, e é a parte fácil de errar em silêncio: uma
assinatura inválida vira um 401 genérico sem indicar o que está errado. Por isso a
lógica fica isolada aqui, testável sem credencial nem rede.

Referências:
* Shopee Open Platform — HMAC-SHA256 sobre `partner_id + path + timestamp + ...`
* Amazon PA-API 5.0 — AWS Signature Version 4
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote


class SignatureError(RuntimeError):
    """Credencial ausente ou malformada para assinar a requisição."""


def _require(value: str, name: str) -> str:
    if not value:
        raise SignatureError(f"credencial ausente: {name}")
    return value


# --- Shopee -------------------------------------------------------------------


def shopee_sign(
    partner_id: str,
    partner_key: str,
    path: str,
    timestamp: int,
    access_token: str = "",
    shop_id: str = "",
) -> str:
    """Assinatura da Shopee Open Platform.

    A base é `partner_id + path + timestamp` e, quando aplicável,
    `access_token + shop_id`. O HMAC é calculado com a `partner_key`.
    """
    base = f"{_require(partner_id, 'partner_id')}{path}{timestamp}"
    if access_token:
        base += access_token
    if shop_id:
        base += str(shop_id)
    return hmac.new(
        _require(partner_key, "partner_key").encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def shopee_public_params(partner_id: str, partner_key: str, path: str, timestamp: int) -> dict[str, Any]:
    """Parâmetros comuns de uma chamada pública (sem token de loja)."""
    return {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "sign": shopee_sign(partner_id, partner_key, path, timestamp),
    }


def shopee_shop_params(
    partner_id: str,
    partner_key: str,
    path: str,
    timestamp: int,
    access_token: str,
    shop_id: str,
) -> dict[str, Any]:
    """Parâmetros de uma chamada autenticada em nome de uma loja."""
    return {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "access_token": access_token,
        "shop_id": shop_id,
        "sign": shopee_sign(partner_id, partner_key, path, timestamp, access_token, shop_id),
    }


# --- Amazon PA-API 5.0 (AWS Signature V4) -------------------------------------

ALGORITHM = "AWS4-HMAC-SHA256"
SERVICE = "ProductAdvertisingAPI"
AMAZON_TARGET = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1"


def _sha256_hex(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def aws_signing_key(secret_key: str, date_stamp: str, region: str, service: str = SERVICE) -> bytes:
    """Deriva a chave de assinatura em quatro passos, como a SigV4 exige."""
    k_date = _hmac(f"AWS4{_require(secret_key, 'secret_key')}".encode("utf-8"), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, "aws4_request")


def aws_canonical_request(
    *,
    host: str,
    path: str,
    payload: str,
    target: str = AMAZON_TARGET,
    content_encoding: str = "amz-1.0",
) -> tuple[str, dict[str, str]]:
    """Monta a requisição canônica da SigV4 e devolve também os headers assinados.

    Os headers precisam estar na ordem alfabética e em minúsculas, e é isso que
    torna a implementação manual sujeita a erro — daí existir um teste.
    """
    headers = {
        "content-encoding": content_encoding,
        "content-type": "application/json; charset=utf-8",
        "host": host,
        "x-amz-target": target,
    }
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
    canonical = "\n".join(
        [
            "POST",
            path,
            "",  # query string vazia: tudo vai no corpo
            canonical_headers,
            signed_headers,
            _sha256_hex(payload),
        ]
    )
    return canonical, headers


def aws_authorization_header(
    *,
    access_key: str,
    secret_key: str,
    region: str,
    host: str,
    canonical_request: str,
    signed_headers: str,
    timestamp: datetime | None = None,
) -> str:
    """Header `Authorization` completo da SigV4."""
    timestamp = timestamp or datetime.now(UTC)
    amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = timestamp.strftime("%Y%m%d")

    scope = f"{date_stamp}/{region}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        [ALGORITHM, amz_date, scope, _sha256_hex(canonical_request)]
    )
    signature = hmac.new(
        aws_signing_key(secret_key, date_stamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return (
        f"{ALGORITHM} Credential={_require(access_key, 'access_key')}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


def encode_uri_component(value: str) -> str:
    """Percent-encoding no formato que a SigV4 exige (espaço como `%20`)."""
    return quote(value, safe="-_.~")


__all__ = [
    "ALGORITHM",
    "AMAZON_TARGET",
    "SERVICE",
    "SignatureError",
    "aws_authorization_header",
    "aws_canonical_request",
    "aws_signing_key",
    "encode_uri_component",
    "shopee_public_params",
    "shopee_shop_params",
    "shopee_sign",
]
