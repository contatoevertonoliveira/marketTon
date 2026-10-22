"""Google Ads API (REST) — Planejador de Palavras-chave: volume, CPC e concorrência.

Não é um marketplace; não implementa `MarketplaceAdapter`. Usa a interface REST
(sem a biblioteca `google-ads`, que arrasta gRPC) com OAuth2 por refresh token.

Autorização: desde 9/9/2026 o Google não exige mais developer token; o acesso
(Teste, Exploração, Básico) é do projeto do Google Cloud das credenciais OAuth.
Recusa de projeto sem acesso de produção volta como `CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION`
(v25+) ou `ACTION_NOT_PERMITTED` (v24 e anteriores).

Validação: o **fluxo OAuth** (refresh token -> access token) segue o endpoint
padrão do Google e é testável sem developer token aprovado. A chamada
`generateKeywordHistoricalMetrics` segue a documentação pública, mas **ainda não
foi validada com conta real** — ajustar na primeira chamada de verdade, como foi
feito com a Shopee. A versão da API é configurável (o Google aposenta versões a
cada poucos meses).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_ROOT = "https://googleads.googleapis.com"
DEFAULT_API_VERSION = "v25"
BRAZIL_GEO = "geoTargetConstants/2076"
PORTUGUESE = "languageConstants/1014"

# O developer token foi desativado pelo Google em 9/9/2026: servidores o ignoram e o
# nível de acesso passou a ser do projeto do Google Cloud. Continua aceito como
# campo opcional (enviado só se preenchido) para contas/versões que ainda o usem.
REQUIRED = ("client_id", "client_secret", "refresh_token", "customer_id")


class GoogleAdsError(RuntimeError):
    """Falha ao falar com o Google (credencial, aprovação do token ou rede)."""


@dataclass
class GoogleAdsConfig:
    developer_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    customer_id: str = ""
    login_customer_id: str = ""  # conta administradora (MCC), se a conta alvo for gerenciada por ela
    api_version: str = DEFAULT_API_VERSION

    @classmethod
    def from_values(cls, values: dict[str, Any]) -> GoogleAdsConfig:
        clean = lambda key: str(values.get(key) or "").strip()  # noqa: E731
        return cls(
            developer_token=clean("developer_token"),
            client_id=clean("client_id"),
            client_secret=clean("client_secret"),
            refresh_token=clean("refresh_token"),
            customer_id=clean("customer_id").replace("-", ""),
            login_customer_id=clean("login_customer_id").replace("-", ""),
            api_version=clean("api_version") or DEFAULT_API_VERSION,
        )

    def is_complete(self) -> bool:
        return all(getattr(self, name) for name in REQUIRED)

    def missing(self) -> list[str]:
        return [name for name in REQUIRED if not getattr(self, name)]


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("status") or ""
        # Erros do Google Ads trazem o código útil (ex.: DEVELOPER_TOKEN_NOT_APPROVED)
        # dentro de `details[].errors[].errorCode`.
        codes: list[str] = []
        for detail in error.get("details") or []:
            for item in detail.get("errors") or []:
                for key, value in (item.get("errorCode") or {}).items():
                    codes.append(f"{key}={value}")
        suffix = f" [{', '.join(codes)}]" if codes else ""
        return f"HTTP {response.status_code}: {message}{suffix}"[:480]
    if isinstance(body, dict) and body.get("error_description"):  # erro do endpoint OAuth
        return f"HTTP {response.status_code}: {body.get('error')}: {body['error_description']}"[:480]
    return f"HTTP {response.status_code}"


class GoogleAdsClient:
    def __init__(self, config: GoogleAdsConfig, *, timeout: float = 30.0) -> None:
        self.cfg = config
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires = 0.0

    # -- OAuth -----------------------------------------------------------------

    def access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        try:
            response = requests.post(
                TOKEN_URL,
                data={
                    "client_id": self.cfg.client_id,
                    "client_secret": self.cfg.client_secret,
                    "refresh_token": self.cfg.refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise GoogleAdsError(f"sem conexão com o Google OAuth: {exc}") from exc
        if not response.ok:
            raise GoogleAdsError(f"OAuth recusou as credenciais — {_error_message(response)}")
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires = time.time() + float(payload.get("expires_in", 3600))
        return self._token

    # -- Chamadas à API --------------------------------------------------------

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.access_token()}",
            "Content-Type": "application/json",
        }
        if self.cfg.developer_token:
            headers["developer-token"] = self.cfg.developer_token
        if self.cfg.login_customer_id:
            headers["login-customer-id"] = self.cfg.login_customer_id
        url = f"{API_ROOT}/{self.cfg.api_version}/customers/{self.cfg.customer_id}{path}"
        try:
            response = requests.post(url, json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise GoogleAdsError(f"sem conexão com a Google Ads API: {exc}") from exc
        if not response.ok:
            raise GoogleAdsError(_error_message(response))
        return response.json()

    def customer_currency(self) -> str | None:
        """Moeda da conta (o CPC do Planejador vem nela). Também prova que o
        developer token, o OAuth e o Customer ID funcionam juntos."""
        data = self._post("/googleAds:search", {"query": "SELECT customer.currency_code FROM customer LIMIT 1"})
        results = data.get("results") or []
        return ((results[0].get("customer") or {}).get("currencyCode") if results else None) or None

    def check(self) -> str:
        """Teste de conexão: devolve uma mensagem de sucesso ou levanta `GoogleAdsError`."""
        if not self.cfg.is_complete():
            raise GoogleAdsError("campos faltando: " + ", ".join(self.cfg.missing()))
        self.access_token()  # separa "OAuth ok" de "token de desenvolvedor/conta com problema"
        currency = self.customer_currency()
        return f"conectado à conta {self.cfg.customer_id} (moeda {currency or 'não informada'})"

    def keyword_metrics(self, keywords: list[str]) -> tuple[dict[str, dict[str, Any]], str | None]:
        """Volume mensal, CPC e concorrência por palavra-chave (Brasil, português).

        Devolve `({palavra em minúsculas: métricas}, moeda da conta)`. O CPC é a
        média do lance de topo de página (`averageCpcMicros`, ou a média entre o
        lance baixo e o alto) — estimativa do Planejador, não custo garantido.
        """
        if not keywords:
            return {}, None
        data = self._post(
            ":generateKeywordHistoricalMetrics",
            {
                "keywords": keywords,
                "geoTargetConstants": [BRAZIL_GEO],
                "language": PORTUGUESE,
                "keywordPlanNetwork": "GOOGLE_SEARCH",
            },
        )
        currency = self.customer_currency()
        out: dict[str, dict[str, Any]] = {}
        for result in data.get("results") or []:
            metrics = result.get("keywordMetrics") or {}
            text = str(result.get("text") or "").lower()
            if not text:
                continue
            micros = metrics.get("averageCpcMicros")
            if micros is None:
                bids = [int(metrics[k]) for k in ("lowTopOfPageBidMicros", "highTopOfPageBidMicros") if metrics.get(k)]
                micros = sum(bids) / len(bids) if bids else None
            competition = metrics.get("competition")
            out[text] = {
                "search_volume": int(metrics["avgMonthlySearches"]) if metrics.get("avgMonthlySearches") else None,
                "competition": competition if competition in ("LOW", "MEDIUM", "HIGH") else None,
                "competition_index": int(metrics["competitionIndex"]) if metrics.get("competitionIndex") else None,
                "cpc": round(float(micros) / 1_000_000, 2) if micros is not None else None,
                "currency": currency,
            }
        return out, currency


__all__ = ["GoogleAdsClient", "GoogleAdsConfig", "GoogleAdsError"]
