"""Hotmart, Monetizze e Eduzz: plataformas de produtos digitais para afiliados.

Diferem dos marketplaces físicos (Shopee, Mercado Livre) em dois pontos que o
sistema respeita:

* **Não há catálogo público de produtos "para afiliar" pela API** (Hotmart e Eduzz
  listam só os produtos do próprio produtor; a Monetizze lista os que o usuário já
  é afiliado ativo). Por isso `fetch_products` devolve vazio com um aviso honesto,
  e os produtos aparecem no sistema pelas **vendas** — que é onde a API entrega dado
  de afiliado (valor, status e comissão).
* **Comissão vem por venda**, não como taxa anunciada do produto. A taxa observada
  alimenta `core/services/commission_learning.py` como em qualquer outro marketplace.

Documentação oficial consultada (21/10/2026):

* Hotmart — https://developers.hotmart.com/docs/en/start/app-auth/ ,
  `/docs/en/v1/sales/sales-history/`, `/docs/en/v1/sales/sales-commissions/`,
  `/docs/en/start/sandbox/`.
* Monetizze — https://api.monetizze.com.br/2.1/apidoc/ (`/token`, `/myproducts`, `/transactions`).
* Eduzz — https://developers.eduzz.com/ (`/docs/api/app-token`, OpenAPI em `/api/openapi`).

**Validação:** o fluxo de autenticação segue a documentação à risca. Já os formatos
exatos das respostas de vendas (principalmente Monetizze e Eduzz, cuja documentação é
menos precisa sobre o papel de afiliado) foram escritos de forma defensiva e **ainda não
foram validados contra uma conta real** — ajustar na primeira coleta de verdade, como foi
feito com a Shopee. A confiabilidade fica abaixo de 1.0 por isso.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from config.settings import get_settings
from integrations.marketplaces.base import ConnectorBatch, MarketplaceAdapter, SalesRecord

logger = logging.getLogger(__name__)

MAX_PAGES = 50  # teto de segurança: nunca fica em loop infinito


class PlatformError(RuntimeError):
    """Falha ao falar com a plataforma (credencial recusada, limite de requisições, rede)."""


class PlatformNotConfigured(PlatformError):
    """Credenciais ausentes. Erro de configuração, não de rede."""


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bps(commission: float | None, gross: float | None) -> int | None:
    if commission is None or not gross or gross <= 0:
        return None
    return round(commission / gross * 10000)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "sim", "yes", "s", "y"}


def _error_text(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:160]}"
    if isinstance(body, dict):
        for key in ("error_description", "message", "error", "Error", "mensagem"):
            if body.get(key):
                return f"HTTP {response.status_code}: {str(body[key])[:200]}"
    return f"HTTP {response.status_code}"


class _TokenCache:
    """Token em memória do processo, com validade. Thread-safe."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires = 0.0
        self._lock = threading.Lock()

    def get(self) -> str | None:
        with self._lock:
            return self._token if self._token and time.time() < self._expires - 30 else None

    def set(self, token: str, ttl_seconds: float) -> None:
        with self._lock:
            self._token, self._expires = token, time.time() + ttl_seconds

    def clear(self) -> None:
        with self._lock:
            self._token, self._expires = None, 0.0


class _PlatformAdapter(MarketplaceAdapter):
    """Base comum: sem catálogo público, sem busca de concorrentes."""

    reliability = 0.7  # API oficial, mas formato de venda ainda não validado em conta real
    catalog_note = "Esta plataforma não expõe catálogo de produtos para afiliar pela API; os produtos aparecem pelas vendas."

    def fetch_products(self, *, limit: int | None = None) -> ConnectorBatch:
        return ConnectorBatch(
            connector=self.name, products=[], collected_at=datetime.now(UTC),
            reliability=self.reliability, warnings=[self.catalog_note],
        )

    def search_competitor(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return []

    def check(self) -> str:  # pragma: no cover - cada plataforma implementa
        raise NotImplementedError


# =================================================================== Hotmart ==========

HOTMART_TOKEN_URL = "https://api-sec-vlc.hotmart.com/security/oauth/token"
HOTMART_PROD = "https://developers.hotmart.com"
HOTMART_SANDBOX = "https://sandbox.hotmart.com"

# Sem filtro de `transaction_status` a API devolve só APPROVED e COMPLETE (doc oficial).
HOTMART_CANCELLED = ("CANCELLED", "REFUNDED", "CHARGEBACK")


@dataclass
class HotmartConfig:
    client_id: str = ""
    client_secret: str = ""
    basic_token: str = ""
    sandbox: str = ""  # vazio = produção; "sim"/"true" = sandbox
    timeout: float = 25.0


class HotmartAdapter(_PlatformAdapter):
    name = "hotmart"
    catalog_note = (
        "A Hotmart só lista produtos do próprio produtor pela API; os produtos que você divulga aparecem pelas vendas."
    )

    def __init__(self, cfg: HotmartConfig | None = None) -> None:
        self.cfg = cfg or self._load_config()
        self._token = _TokenCache()

    @staticmethod
    def _load_config() -> HotmartConfig:
        s = get_settings()
        return HotmartConfig(
            client_id=s.hotmart_client_id, client_secret=s.hotmart_client_secret,
            basic_token=s.hotmart_basic_token, sandbox=s.hotmart_sandbox, timeout=s.connector_timeout_seconds,
        )

    def is_configured(self) -> bool:
        return bool(self.cfg.client_id and self.cfg.client_secret and self.cfg.basic_token)

    @property
    def base_url(self) -> str:
        return HOTMART_SANDBOX if _truthy(self.cfg.sandbox) else HOTMART_PROD

    def _access_token(self, *, force: bool = False) -> str:
        if not self.is_configured():
            raise PlatformNotConfigured("Credenciais da Hotmart incompletas: client_id, client_secret e token Basic.")
        cached = None if force else self._token.get()
        if cached:
            return cached
        basic = self.cfg.basic_token.strip()
        if basic.lower().startswith("basic "):
            basic = basic[6:].strip()
        try:
            response = requests.post(
                HOTMART_TOKEN_URL,
                params={"grant_type": "client_credentials", "client_id": self.cfg.client_id, "client_secret": self.cfg.client_secret},
                headers={"Content-Type": "application/json", "Authorization": f"Basic {basic}"},
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as exc:
            raise PlatformError(f"sem conexão com a Hotmart: {exc}") from exc
        if not response.ok:
            raise PlatformError(f"Hotmart recusou as credenciais — {_error_text(response)}")
        data = response.json()
        # Só o access_token expira; as credenciais seguem valendo (doc oficial).
        self._token.set(data["access_token"], float(data.get("expires_in", 3600)))
        return data["access_token"]

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in (0, 1):
            token = self._access_token(force=attempt == 1)
            try:
                response = requests.get(
                    f"{self.base_url}{path}", params={k: v for k, v in params.items() if v is not None},
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                    timeout=self.cfg.timeout,
                )
            except requests.RequestException as exc:
                raise PlatformError(f"sem conexão com a Hotmart: {exc}") from exc
            if response.status_code == 401 and attempt == 0:
                self._token.clear()  # token expirado: gera outro e tenta uma vez
                continue
            if response.status_code == 429:
                raise PlatformError("Hotmart: limite de requisições atingido (HTTP 429); tente mais tarde")
            if not response.ok:
                raise PlatformError(f"Hotmart — {_error_text(response)}")
            return response.json()
        raise PlatformError("Hotmart: não foi possível autenticar")

    def check(self) -> str:
        self._access_token(force=True)
        return f"token OAuth obtido ({'sandbox' if _truthy(self.cfg.sandbox) else 'produção'})"

    def _paged(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token: str | None = None
        for _ in range(MAX_PAGES):
            data = self._get(path, {**params, "max_results": 100, "page_token": token})
            items.extend(data.get("items") or [])
            token = (data.get("page_info") or {}).get("next_page_token")
            if not token:
                break
        return items

    @staticmethod
    def _ms(value: Any) -> datetime | None:
        number = _to_float(value)
        return datetime.fromtimestamp(number / 1000, tz=UTC) if number else None

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        """Vendas como afiliado: histórico + comissão do afiliado por transação.

        APPROVED = paga, ainda dentro da garantia (comissão estimada); COMPLETE = garantia
        encerrada (confirmada). Cancelada/reembolsada/chargeback vira CANCELLED, sem comissão.
        """
        start = since or (datetime.now(UTC) - timedelta(days=30))
        window = {
            "start_date": int(start.timestamp() * 1000),
            "end_date": int(datetime.now(UTC).timestamp() * 1000),
            "commission_as": "AFFILIATE",
        }
        sales = self._paged("/payments/api/v1/sales/history", window)
        for status in HOTMART_CANCELLED:
            sales += self._paged("/payments/api/v1/sales/history", {**window, "transaction_status": status})

        commission_by_tx: dict[str, float] = {}
        for entry in self._paged("/payments/api/v1/sales/commissions", window):
            for part in entry.get("commissions") or []:
                if part.get("source") == "AFFILIATE" and _to_float((part.get("commission") or {}).get("value")) is not None:
                    commission_by_tx[entry.get("transaction")] = float(part["commission"]["value"])

        records: list[SalesRecord] = []
        seen: set[str] = set()
        for item in sales:
            purchase = item.get("purchase") or {}
            transaction = purchase.get("transaction")
            if not transaction or transaction in seen:
                continue
            seen.add(transaction)
            status = (purchase.get("status") or "").upper()
            price = purchase.get("price") or {}
            gross = _to_float(price.get("value"))
            commission = commission_by_tx.get(transaction)
            cancelled = status in HOTMART_CANCELLED
            product = item.get("product") or {}
            records.append(SalesRecord(
                external_order_id=transaction,
                occurred_at=self._ms(purchase.get("approved_date")) or self._ms(purchase.get("order_date")) or datetime.now(UTC),
                quantity=1,
                currency=price.get("currency_code"),
                gross_amount=gross,
                product_external_id=str(product["id"]) if product.get("id") is not None else None,
                product_title=product.get("name"),
                status="CANCELLED" if cancelled else status,
                commission_estimated=commission if status == "APPROVED" else None,
                commission_confirmed=commission if status == "COMPLETE" else None,
                commission_rate_basis_points=None if cancelled else _bps(commission, gross),
            ))
        return records


# ================================================================== Monetizze =========

MONETIZZE_API = "https://api.monetizze.com.br/2.1"
MONETIZZE_TOKEN_TTL = 14 * 60  # o token vive 15 min e renova a cada uso (doc oficial)
# Status da venda (texto, doc oficial): Aguardando pagamento · Finalizada · Cancelada · Devolvida · Bloqueada · Completa
MONETIZZE_CANCELLED = {"cancelada", "devolvida", "bloqueada"}


@dataclass
class MonetizzeConfig:
    consumer_key: str = ""
    timeout: float = 25.0


class MonetizzeAdapter(_PlatformAdapter):
    name = "monetizze"

    def __init__(self, cfg: MonetizzeConfig | None = None) -> None:
        self.cfg = cfg or self._load_config()
        self._token = _TokenCache()

    @staticmethod
    def _load_config() -> MonetizzeConfig:
        s = get_settings()
        return MonetizzeConfig(consumer_key=s.monetizze_consumer_key, timeout=s.connector_timeout_seconds)

    def is_configured(self) -> bool:
        return bool(self.cfg.consumer_key)

    def _access_token(self, *, force: bool = False) -> str:
        if not self.is_configured():
            raise PlatformNotConfigured("Chave de API (consumer key) da Monetizze ausente.")
        cached = None if force else self._token.get()
        if cached:
            return cached
        try:
            response = requests.get(f"{MONETIZZE_API}/token", headers={"X_CONSUMER_KEY": self.cfg.consumer_key}, timeout=self.cfg.timeout)
        except requests.RequestException as exc:
            raise PlatformError(f"sem conexão com a Monetizze: {exc}") from exc
        if not response.ok:
            raise PlatformError(f"Monetizze recusou a chave — {_error_text(response)}")
        body = response.json() or {}
        # A API devolve `token` em minúsculas (a doc antiga mostrava TOKEN): aceita as duas grafias.
        token = next((v for k, v in body.items() if str(k).lower() == "token" and isinstance(v, str) and v), None)             if isinstance(body, dict) else None
        if not token:
            raise PlatformError("Monetizze não devolveu o token de acesso")
        self._token.set(token, MONETIZZE_TOKEN_TTL)
        return token

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        for attempt in (0, 1):
            token = self._access_token(force=attempt == 1)
            try:
                response = requests.get(
                    f"{MONETIZZE_API}{path}", params=params, headers={"TOKEN": token}, timeout=self.cfg.timeout)
            except requests.RequestException as exc:
                raise PlatformError(f"sem conexão com a Monetizze: {exc}") from exc
            # Token inválido/expirado volta 403 (InvalidToken); gera outro e tenta uma vez.
            if response.status_code in (401, 403) and attempt == 0:
                self._token.clear()
                continue
            if not response.ok:
                raise PlatformError(f"Monetizze — {_error_text(response)}")
            return response.json()
        raise PlatformError("Monetizze: não foi possível autenticar")

    def check(self) -> str:
        self._access_token(force=True)
        return "token obtido com a chave de API (vale 15 min e renova a cada uso)"

    def fetch_products(self, *, limit: int | None = None) -> ConnectorBatch:
        """`/myproducts`: por padrão, os produtos em que você é afiliado ativo."""
        from integrations.marketplaces.base import ConnectorProduct

        data = self._get("/myproducts", {"retorno_produtor": 0})
        rows = data.get("dados") if isinstance(data, dict) else None
        products: list[ConnectorProduct] = []
        for row in rows or []:
            plans = [p for p in (row.get("planos") or []) if str(p.get("status")) == "1"]
            prices = [v for v in (_to_float(p.get("valor")) for p in plans) if v is not None]
            products.append(ConnectorProduct(
                external_id=str(row.get("codigo")),
                title=row.get("nome") or f"Produto {row.get('codigo')}",
                currency="BRL",
                price=min(prices) if prices else None,
                is_available=str(row.get("status")) == "2",
                images=[row["foto"]] if row.get("foto") else None,
                # A API não informa a comissão do afiliado no produto: fica `None`, e a
                # taxa observada nas vendas preenche depois.
                affiliate_commission_pct=None,
                attributes={"platform": "monetizze", "plans": [
                    {"codigo": p.get("codigo"), "nome": p.get("nome"), "valor": p.get("valor"), "status": p.get("status")}
                    for p in (row.get("planos") or [])]},
            ))
            if limit and len(products) >= limit:
                break
        return ConnectorBatch(
            connector=self.name, products=products, collected_at=datetime.now(UTC),
            endpoint=f"{MONETIZZE_API}/myproducts", reliability=self.reliability,
            warnings=["Comissão do afiliado não vem no produto; é aprendida nas vendas."],
        )

    @staticmethod
    def _my_commission(sale: dict[str, Any]) -> tuple[float | None, float | None]:
        """(valor, %) da comissão do afiliado. A doc não diz qual item de `comissoes` é o do afiliado
        que consulta; só aceita quando há um único candidato (item com `refAfiliado`, ou lista de 1)."""
        entries = sale.get("comissoes") or []
        candidates = [c for c in entries if c.get("refAfiliado")] or (entries if len(entries) == 1 else [])
        if len(candidates) != 1:
            return None, None
        return _to_float(candidates[0].get("valor")), _to_float(candidates[0].get("porcentagem"))

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value), fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
        return None

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        start = since or (datetime.now(UTC) - timedelta(days=30))
        records: list[SalesRecord] = []
        for page in range(1, MAX_PAGES + 1):
            data = self._get("/transactions", {
                "date_min": start.strftime("%Y-%m-%d %H:%M:%S"),
                "date_max": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                "page": page,
            })
            rows = (data[0] if isinstance(data, list) and data else data or {}).get("dados") or []
            for row in rows:
                sale = row.get("venda") or row
                code = sale.get("codigo")
                if not code:
                    continue
                product = row.get("produto") or sale.get("produto") or {}
                status_text = str(sale.get("status") or "").strip().lower()
                value, pct = self._my_commission({**sale, **({"comissoes": row["comissoes"]} if row.get("comissoes") else {})})
                gross = _to_float(sale.get("valor"))
                cancelled = status_text in MONETIZZE_CANCELLED
                confirmed = status_text == "completa"
                records.append(SalesRecord(
                    external_order_id=str(code),
                    occurred_at=self._dt(sale.get("dataInicio")) or datetime.now(UTC),
                    quantity=int(_to_float(sale.get("quantidade")) or 1),
                    currency=sale.get("moeda") or "BRL",
                    gross_amount=gross,
                    product_external_id=str(product["codigo"]) if product.get("codigo") is not None else None,
                    product_title=product.get("nome"),
                    status="CANCELLED" if cancelled else sale.get("status"),
                    # "Finalizada" = paga, ainda na garantia (estimada); "Completa" = garantia encerrada (confirmada).
                    commission_estimated=None if cancelled or confirmed or status_text.startswith("aguardando") else value,
                    commission_confirmed=value if confirmed else None,
                    commission_rate_basis_points=round(pct * 100) if (pct is not None and not cancelled) else _bps(value, gross),
                ))
            if len(rows) < 100:  # a API pagina de 100 em 100
                break
        return records


# ================================================================== Eduzz ============

EDUZZ_TOKEN_URL = "https://accounts-api.eduzz.com/oauth/token"
EDUZZ_API = "https://api.eduzz.com"
EDUZZ_CONFIRMED = {"paid", "finished", "completed", "complete", "approved"}
EDUZZ_CANCELLED = {"canceled", "cancelled", "refunded", "chargeback", "expired", "rejected", "blocked"}


@dataclass
class EduzzConfig:
    client_id: str = ""
    client_secret: str = ""
    timeout: float = 25.0


class EduzzAdapter(_PlatformAdapter):
    name = "eduzz"
    catalog_note = (
        "A API da Eduzz lista só os produtos do produtor; os produtos que você divulga aparecem pelas vendas."
    )

    def __init__(self, cfg: EduzzConfig | None = None) -> None:
        self.cfg = cfg or self._load_config()
        self._token = _TokenCache()

    @staticmethod
    def _load_config() -> EduzzConfig:
        s = get_settings()
        return EduzzConfig(client_id=s.eduzz_client_id, client_secret=s.eduzz_client_secret, timeout=s.connector_timeout_seconds)

    def is_configured(self) -> bool:
        return bool(self.cfg.client_id and self.cfg.client_secret)

    def _access_token(self, *, force: bool = False) -> str:
        if not self.is_configured():
            raise PlatformNotConfigured("Credenciais da Eduzz incompletas: client_id e client_secret.")
        cached = None if force else self._token.get()
        if cached:
            return cached
        try:
            response = requests.post(
                EDUZZ_TOKEN_URL, headers={"content-type": "application/json"},
                json={"grant_type": "client_credentials", "client_id": self.cfg.client_id, "client_secret": self.cfg.client_secret},
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as exc:
            raise PlatformError(f"sem conexão com a Eduzz: {exc}") from exc
        if not response.ok:
            raise PlatformError(f"Eduzz recusou as credenciais — {_error_text(response)}")
        token = (response.json() or {}).get("access_token")
        if not token:
            raise PlatformError("Eduzz não devolveu o access_token")
        # A doc não informa validade e diz que gerar um token novo invalida os anteriores: guarda por
        # 50 min e, se a API devolver 401, gera outro (uma vez) em vez de renovar a cada chamada.
        self._token.set(token, 50 * 60)
        return token

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in (0, 1):
            token = self._access_token(force=attempt == 1)
            try:
                response = requests.get(
                    f"{EDUZZ_API}{path}", params=params,
                    headers={"accept": "application/json", "authorization": f"bearer {token}"}, timeout=self.cfg.timeout)
            except requests.RequestException as exc:
                raise PlatformError(f"sem conexão com a Eduzz: {exc}") from exc
            if response.status_code == 401 and attempt == 0:
                self._token.clear()
                continue
            if not response.ok:
                raise PlatformError(f"Eduzz — {_error_text(response)}")
            return response.json()
        raise PlatformError("Eduzz: não foi possível autenticar")

    def check(self) -> str:
        self._access_token(force=True)
        me = self._get("/accounts/v1/me", {})
        who = (me.get("data") or me).get("name") or (me.get("data") or me).get("email") or "conta vinculada ao app"
        return f"conectado como {who}"

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        start = since or (datetime.now(UTC) - timedelta(days=30))
        records: list[SalesRecord] = []
        for page in range(1, MAX_PAGES + 1):
            data = self._get("/myeduzz/v1/sales", {
                "page": page, "itemsPerPage": 100,
                "startDate": start.strftime("%Y-%m-%d"), "endDate": datetime.now(UTC).strftime("%Y-%m-%d"),
            })
            for item in data.get("items") or []:
                sale_id = item.get("id")
                if sale_id is None:
                    continue
                status_text = str(item.get("status") or "").strip().lower()
                cancelled = status_text in EDUZZ_CANCELLED
                confirmed = status_text in EDUZZ_CONFIRMED
                gross = _to_float((item.get("total") or {}).get("value"))
                # `netGain` é o ganho líquido de quem consulta (a listagem é da conta autenticada).
                gain = _to_float((item.get("netGain") or {}).get("value"))
                product = item.get("product") or {}
                records.append(SalesRecord(
                    external_order_id=str(sale_id),
                    occurred_at=self._dt(item.get("paidAt")) or self._dt(item.get("createdAt")) or datetime.now(UTC),
                    quantity=1,
                    currency=item.get("currency") or (item.get("total") or {}).get("currency"),
                    gross_amount=gross,
                    product_external_id=str(product["id"]) if product.get("id") is not None else None,
                    product_title=product.get("name"),
                    status="CANCELLED" if cancelled else (item.get("status") or "PENDING"),
                    commission_estimated=None if cancelled or confirmed else gain,
                    commission_confirmed=gain if confirmed else None,
                    commission_rate_basis_points=None if cancelled else _bps(gain, gross),
                ))
            if page >= int(data.get("pages") or 1):
                break
        return records


__all__ = [
    "EduzzAdapter", "EduzzConfig", "HotmartAdapter", "HotmartConfig", "MonetizzeAdapter", "MonetizzeConfig",
    "PlatformError", "PlatformNotConfigured",
]
