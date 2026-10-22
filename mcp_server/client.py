"""Cliente HTTP do servidor MCP para a API do marketTon.

O agente entra como um usuário comum de papel `bot` e passa por **todas** as regras
da API: permissões, trava do modo agente e trilha de auditoria. Nada aqui fala com
o banco ou com os marketplaces diretamente — se uma ação não existe na API, o agente
não a tem.
"""
from __future__ import annotations

import os
import threading
from typing import Any

import requests

DEFAULT_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 150  # o funil consulta Google Trends e Google Ads ao vivo


class ApiError(RuntimeError):
    """Resposta de erro da API. `agent_mode_off` marca a recusa por modo manual."""

    def __init__(self, status: int, message: str, *, agent_mode_off: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.agent_mode_off = agent_mode_off


class MarkettonClient:
    def __init__(self, base_url: str | None = None, username: str | None = None, password: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("MARKETTON_API_URL") or DEFAULT_URL).rstrip("/")
        self.username = username or os.environ.get("MARKETTON_AGENT_USER", "")
        self.password = password or os.environ.get("MARKETTON_AGENT_PASSWORD", "")
        # Rodando em segundo plano, o backend entrega um token já emitido (sem senha). Sem refresh:
        # a rodada é curta e, se o token vencer, o erro é claro e a próxima rodada recebe outro.
        self._access: str | None = os.environ.get("MARKETTON_AGENT_ACCESS_TOKEN") or None
        self._token_only = bool(self._access)
        self._refresh: str | None = None
        self._lock = threading.Lock()

    # -- sessão ------------------------------------------------------------------

    def _login(self) -> None:
        if not (self.username and self.password):
            raise ApiError(
                401,
                "credenciais do agente ausentes: defina MARKETTON_AGENT_USER e MARKETTON_AGENT_PASSWORD "
                "(gere o acesso em marketTon > Agente Claude).",
            )
        try:
            response = requests.post(
                f"{self.base_url}/auth/login",
                json={"username": self.username, "password": self.password},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise ApiError(0, f"não consegui falar com o marketTon em {self.base_url}. O backend está no ar?") from exc
        if not response.ok:
            raise ApiError(response.status_code, f"login do agente recusado: {_message(response)}")
        data = response.json()
        self._access, self._refresh = data["access_token"], data["refresh_token"]

    def _refresh_tokens(self) -> bool:
        if not self._refresh:
            return False
        try:
            response = requests.post(f"{self.base_url}/auth/refresh", json={"refresh_token": self._refresh}, timeout=30)
        except requests.RequestException:
            return False
        if not response.ok:
            return False
        data = response.json()
        self._access, self._refresh = data["access_token"], data["refresh_token"]
        return True

    # -- chamadas ----------------------------------------------------------------

    def request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> Any:
        with self._lock:
            if not self._access:
                self._login()
            response = self._send(method, path, params, json)
            if response.status_code == 401:
                if self._token_only:
                    raise ApiError(401, "a sessão do agente venceu; a próxima rodada recebe uma nova")
                if not self._refresh_tokens():
                    self._login()
                response = self._send(method, path, params, json)
        if not response.ok:
            detail = _detail(response)
            raise ApiError(response.status_code, _message(response), agent_mode_off=detail.get("agent_mode") is False)
        return response.json()

    def _send(self, method: str, path: str, params: dict | None, json: dict | None) -> requests.Response:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            return requests.request(
                method,
                f"{self.base_url}{path}",
                params=clean or None,
                json=json,
                headers={"Authorization": f"Bearer {self._access}"},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise ApiError(0, f"não consegui falar com o marketTon em {self.base_url}. O backend está no ar?") from exc

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None, **params: Any) -> Any:
        return self.request("POST", path, params=params, json=json or {})

    def put(self, path: str, json: dict | None = None) -> Any:
        return self.request("PUT", path, json=json or {})


def _detail(response: requests.Response) -> dict:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return {}
    return detail if isinstance(detail, dict) else {"message": detail}


def _message(response: requests.Response) -> str:
    detail = _detail(response)
    message = detail.get("message") or response.reason or f"HTTP {response.status_code}"
    extra = detail.get("allowed_transitions")
    return f"{message} (transições permitidas: {extra})" if extra else str(message)
