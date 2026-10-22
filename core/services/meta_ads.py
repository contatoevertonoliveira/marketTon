"""Meta (Facebook, Instagram e Anúncios): conferência da conexão (somente leitura).

Esta etapa só **confere** se o token enxerga a conta de anúncios e a Página e se tem as permissões certas. Criar campanhas,
publicar posts e ler métricas vêm depois, em cima desta conexão, e sempre dentro do orçamento definido em "Orçamento de anúncios".
"""
from __future__ import annotations

import requests

GRAPH = "https://graph.facebook.com/v21.0"
TIMEOUT = 25
NEEDED_SCOPES = ("ads_management", "ads_read", "pages_read_engagement")
ACCOUNT_STATUS = {1: "ativa", 2: "desativada", 3: "com pendência de pagamento", 7: "em revisão de risco", 8: "em período de carência",
                  9: "em período de carência", 100: "em fechamento", 101: "fechada", 201: "qualquer", 202: "fechada"}


class MetaError(RuntimeError):
    """Falha da Meta. A mensagem é segura para exibir ao operador."""


def _get(path: str, token: str, **params) -> dict:
    try:
        response = requests.get(f"{GRAPH}/{path.lstrip('/')}", params={"access_token": token, **params}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise MetaError(f"sem conexão com a Meta: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        raise MetaError(f"Meta recusou ({err.get('code', response.status_code)}): {str(err.get('message') or 'erro desconhecido')[:200]}")
    return body


def normalize_account(value: str) -> str:
    value = (value or "").strip()
    return value if value.startswith("act_") else f"act_{value}"


def check(values: dict) -> str:
    """Confere token, permissões, conta de anúncios e Página. Devolve um resumo; levanta `MetaError` se algo estiver errado."""
    token = str(values.get("access_token") or "").strip()
    if not token:
        raise MetaError("falta o token de acesso")
    parts = []
    me = _get("me", token, fields="id,name")
    parts.append(f"token de “{me.get('name') or me.get('id')}”")

    app_id, app_secret = str(values.get("app_id") or "").strip(), str(values.get("app_secret") or "").strip()
    if app_id and app_secret:
        info = _get("debug_token", f"{app_id}|{app_secret}", input_token=token).get("data") or {}
        if info.get("is_valid") is False:
            raise MetaError("o token não é mais válido (expirou ou foi revogado): gere outro")
        scopes = set(info.get("scopes") or [])
        missing = [s for s in NEEDED_SCOPES if s not in scopes]
        if missing:
            raise MetaError("faltam permissões no token: " + ", ".join(missing))
        expires = info.get("expires_at")
        parts.append("permissões ok" + (" (token sem validade)" if not expires else ""))

    account = str(values.get("ad_account_id") or "").strip()
    if account:
        acc = _get(normalize_account(account), token, fields="name,account_status,currency")
        status = ACCOUNT_STATUS.get(acc.get("account_status"), f"status {acc.get('account_status')}")
        if acc.get("account_status") != 1:
            raise MetaError(f"a conta de anúncios “{acc.get('name')}” está {status}: resolva no Gerenciador de Anúncios")
        parts.append(f"conta de anúncios “{acc.get('name')}” ({acc.get('currency')}, {status})")

    page = str(values.get("page_id") or "").strip()
    if page:
        pg = _get(page, token, fields="name")
        parts.append(f"Página “{pg.get('name')}”")
    return "conectado: " + "; ".join(parts)
