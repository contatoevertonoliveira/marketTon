"""Adapter do AliExpress — Portals Affiliate API (open.aliexpress.com / openservice.aliexpress.com).

O programa de afiliados do AliExpress (portals.aliexpress.com) tem API oficial com busca de produtos, link de afiliado e relatório de pedidos:

* `aliexpress.affiliate.product.query`   busca por palavra-chave (devolve preço, comissão, fotos, link de afiliado);
* `aliexpress.affiliate.hotproduct.query` produtos em alta;
* `aliexpress.affiliate.link.generate`    link de afiliado para um endereço qualquer;
* `aliexpress.affiliate.order.list`       pedidos e comissão (pode exigir liberação à parte pelo AliExpress).

Credenciais: App Key + App Secret (app criado em openservice.aliexpress.com com a permissão "Affiliate API") e o Tracking ID do portal de afiliados.
Cada requisição é assinada com HMAC-SHA256 dos parâmetros ordenados (nome+valor, em letras maiúsculas na saída).

Notas de honestidade dos dados:

* Comissão, link de afiliado e várias fotos por produto vêm prontos da API (a Shopee entrega só uma foto, aqui o slideshow ganha mais).
* Preço sai na moeda pedida (`target_currency`, BRL por padrão). A comissão é paga em dólar, então `currency` do produto é a do preço mostrado.
* O formato de resposta foi montado a partir da documentação pública e de guias de terceiros; a primeira chamada real (botão Testar em Integrações) é
  quem confirma. Qualquer campo ausente vira `None`, nunca zero.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from config.settings import get_settings
from integrations.marketplaces.base import (
    ConnectorBatch,
    ConnectorProduct,
    MarketplaceAdapter,
    SalesRecord,
)

logger = logging.getLogger(__name__)

API_URL = "https://api-sg.aliexpress.com/sync"
PRODUCT_FIELDS = (
    "product_id,product_title,product_main_image_url,product_small_image_urls,target_sale_price,target_original_price,"
    "target_app_sale_price,discount,promotion_link,product_detail_url,evaluate_rate,lastest_volume,commission_rate,"
    "hot_commission_rate,first_level_category_id,first_level_category_name,second_level_category_name,shop_id,shop_url,"
    "target_sale_price_currency"
)


class AliExpressError(RuntimeError):
    """Falha ao falar com o AliExpress."""


class AliExpressNotConfigured(AliExpressError):
    """Credenciais ausentes. Erro de configuração, não de rede."""


@dataclass
class AliExpressConfig:
    app_key: str = ""
    app_secret: str = ""
    tracking_id: str = ""
    api_url: str = API_URL
    currency: str = "BRL"
    language: str = "PT"
    ship_to: str = "BR"
    timeout: float = 20.0


@dataclass
class AliExpressAdapterOptions:
    keywords: list[str] = field(default_factory=list)
    max_items: int = 50
    page_size: int = 50
    warnings: list[str] = field(default_factory=list)


def sign(params: dict[str, str], secret: str) -> str:
    """HMAC-SHA256 dos pares ordenados `nome+valor`, em hexadecimal maiúsculo (assinatura do gateway /sync)."""
    base = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign" and params[key] is not None)
    return hmac.new(secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest().upper()


class AliExpressAdapter(MarketplaceAdapter):
    name = "aliexpress"
    reliability = 0.85  # API oficial de afiliado; formato validado só na primeira chamada real

    def __init__(self, cfg: AliExpressConfig | None = None):
        self.cfg = cfg or self._load_config()

    @staticmethod
    def _load_config() -> AliExpressConfig:
        settings = get_settings()
        return AliExpressConfig(
            app_key=getattr(settings, "aliexpress_app_key", ""),
            app_secret=getattr(settings, "aliexpress_app_secret", ""),
            tracking_id=getattr(settings, "aliexpress_tracking_id", ""),
            timeout=settings.connector_timeout_seconds,
        )

    def is_configured(self) -> bool:
        return bool(self.cfg.app_key and self.cfg.app_secret and self.cfg.tracking_id)

    def get_status(self) -> dict[str, Any]:
        return {
            "connector": self.name,
            "configured": self.is_configured(),
            "has_credentials": bool(self.cfg.app_key and self.cfg.app_secret),
            "reliability": self.reliability,
            "note": (
                "Exige conta no Portals (portals.aliexpress.com) e um app com a permissão Affiliate API "
                "(openservice.aliexpress.com). Sem o Tracking ID não há link de afiliado."
            ),
        }

    # --- Chamada assinada ---------------------------------------------------------

    def _call(self, method: str, **params: Any) -> dict[str, Any]:
        if not self.is_configured():
            raise AliExpressNotConfigured(
                "Credenciais do AliExpress incompletas. São necessários App Key, App Secret e Tracking ID (salvos em Integrações)."
            )
        body: dict[str, str] = {
            "app_key": self.cfg.app_key,
            "timestamp": str(int(time.time() * 1000)),
            "sign_method": "sha256",
            "method": method,
        }
        body.update({k: str(v) for k, v in params.items() if v is not None and v != ""})
        body["sign"] = sign(body, self.cfg.app_secret)
        try:
            response = requests.post(self.cfg.api_url, data=body, timeout=self.cfg.timeout)
        except requests.RequestException as exc:
            raise AliExpressError(f"falha de rede em {self.cfg.api_url}: {exc}") from exc
        if response.status_code != 200:
            raise AliExpressError(f"HTTP {response.status_code}: {response.text[:400]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise AliExpressError(f"resposta não é JSON: {response.text[:200]}") from exc

        error = data.get("error_response")
        if error or ("code" in data and str(data.get("code")) not in ("0", "200") and not _find_result(data)):
            err = error or data
            raise AliExpressError(f"{err.get('code', '?')}: {err.get('msg') or err.get('message') or err}"[:400])
        return data

    def check(self) -> str:
        """Teste de ponta a ponta: uma busca mínima prova assinatura, permissão e Tracking ID."""
        data = self._call(
            "aliexpress.affiliate.product.query", keywords="garrafa", page_no=1, page_size=1, fields="product_id",
            tracking_id=self.cfg.tracking_id, target_currency=self.cfg.currency, target_language=self.cfg.language,
            ship_to_country=self.cfg.ship_to,
        )
        result = _find_result(data)
        total = _to_int((result or {}).get("total_record_count"))
        return f"autenticação aceita pela Portals Affiliate API ({total} produtos na busca de teste)" if total is not None else "autenticação aceita"

    # --- Coleta -------------------------------------------------------------------

    def fetch_products(
        self, *, limit: int | None = None, options: AliExpressAdapterOptions | None = None
    ) -> ConnectorBatch:
        options = options or AliExpressAdapterOptions()
        if limit is not None:
            options.max_items = limit
        if not self.is_configured():
            raise AliExpressNotConfigured(
                "Credenciais do AliExpress incompletas. São necessários App Key, App Secret e Tracking ID (salvos em Integrações)."
            )
        if not options.keywords:
            raise AliExpressError("informe ao menos uma palavra-chave em AliExpressAdapterOptions.keywords")

        warnings = list(options.warnings)
        products: list[ConnectorProduct] = []
        seen: set[str] = set()
        budget = max(1, options.max_items // max(1, len(options.keywords)))

        for keyword in options.keywords:
            if len(products) >= options.max_items:
                break
            got, page = 0, 1
            batch: list[ConnectorProduct] = []
            while got < budget and len(products) + len(batch) < options.max_items:
                size = max(1, min(options.page_size, 50, budget - got))
                try:
                    data = self._call(
                        "aliexpress.affiliate.product.query", keywords=keyword, page_no=page, page_size=size,
                        fields=PRODUCT_FIELDS, tracking_id=self.cfg.tracking_id, target_currency=self.cfg.currency,
                        target_language=self.cfg.language, ship_to_country=self.cfg.ship_to, sort="LAST_VOLUME_DESC",
                    )
                except AliExpressError as exc:
                    warnings.append(f"busca por '{keyword}' interrompida na página {page}: {exc}")
                    break
                result = _find_result(data) or {}
                nodes = _listing(result.get("products"), "product")
                if not nodes:
                    break
                for node in nodes:
                    pid = str(node.get("product_id") or "")
                    if pid and pid not in seen:
                        seen.add(pid)
                        batch.append(self._normalize(node))
                        got += 1
                if len(nodes) < size:
                    break
                page += 1
            self._attach_similar(batch)
            products.extend(batch)

        if len(products) >= options.max_items:
            warnings.append(f"coleta limitada a {options.max_items} ofertas; pode haver mais resultados")
        return ConnectorBatch(
            connector=self.name,
            products=products[: options.max_items],
            collected_at=datetime.now(UTC),
            endpoint=f"{self.cfg.api_url} (aliexpress.affiliate.product.query, keywords: {', '.join(options.keywords)})",
            reliability=self.reliability,
            warnings=warnings,
            raw={"keywords": options.keywords},
        )

    def _normalize(self, node: dict[str, Any]) -> ConnectorProduct:
        price = _to_float(node.get("target_app_sale_price")) or _to_float(node.get("target_sale_price"))
        original = _to_float(node.get("target_original_price"))
        if original is not None and price is not None and original <= price:
            original = None
        images = []
        for url in [node.get("product_main_image_url"), *_listing(node.get("product_small_image_urls"), "string")]:
            if isinstance(url, str) and url and url not in images:
                images.append(url)
        commission = _pct(node.get("commission_rate"))
        hot = _pct(node.get("hot_commission_rate"))
        category = node.get("first_level_category_id")
        return ConnectorProduct(
            external_id=str(node.get("product_id")),
            title=str(node.get("product_title") or "").strip(),
            category_id=str(category) if category is not None else None,
            category_path=[c for c in (node.get("first_level_category_name"), node.get("second_level_category_name")) if c] or None,
            seller_external_id=str(node["shop_id"]) if node.get("shop_id") is not None else None,
            currency=node.get("target_sale_price_currency") or self.cfg.currency,
            price=price,
            original_price=original,
            discount_pct=_pct(node.get("discount")),
            affiliate_commission_pct=commission,
            sold_quantity=_to_int(node.get("lastest_volume")),
            # evaluate_rate é a avaliação positiva em % (ex.: "96.2%"); a nota 0–5 equivalente é o que o resto do sistema usa.
            rating=round(_pct(node.get("evaluate_rate")) / 20, 2) if _pct(node.get("evaluate_rate")) is not None else None,
            affiliate_url=node.get("promotion_link"),
            product_url=(node.get("product_detail_url") or "").split("?")[0] or None,  # sem os parâmetros de rastreio da busca
            images=images or None,
            attributes={"commission_api_pct": commission, "hot_commission_pct": hot, "shop_url": node.get("shop_url")},
        )

    @staticmethod
    def _attach_similar(batch: list[ConnectorProduct]) -> None:
        priced = sorted(p.price for p in batch if p.price is not None)
        if len(priced) < 2:
            return
        for product in batch:
            if product.price is not None:
                product.attributes = {**(product.attributes or {}), "similar_offers": len(priced),
                                      "similar_price_min": priced[0], "similar_price_max": priced[-1]}

    def affiliate_link(self, url: str) -> str | None:
        """Link de afiliado (com o Tracking ID) para um endereço do AliExpress."""
        data = self._call("aliexpress.affiliate.link.generate", promotion_link_type=0, source_values=url, tracking_id=self.cfg.tracking_id)
        links = _listing((_find_result(data) or {}).get("promotion_links"), "promotion_link")
        return (links[0].get("promotion_link") if links else None) or None

    # --- Vendas -------------------------------------------------------------------

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        """Pedidos e comissão via `aliexpress.affiliate.order.list` (pode exigir liberação à parte; sem ela devolve vazio)."""
        if not self.is_configured():
            raise AliExpressNotConfigured("Credenciais do AliExpress incompletas.")
        start = (since or (datetime.now(UTC) - timedelta(days=30))).astimezone(UTC)
        end = datetime.now(UTC)
        records: list[SalesRecord] = []
        page = 1
        for _ in range(50):
            try:
                data = self._call(
                    "aliexpress.affiliate.order.list", start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
                    end_time=end.strftime("%Y-%m-%d %H:%M:%S"), page_no=page, page_size=50,
                    fields="order_id,order_number,paid_amount,estimated_paid_commission,estimated_finished_commission,finished_status,"
                           "order_status,paid_time,product_id,product_title,product_count,sub_order_id,order_type",
                )
            except AliExpressError as exc:
                logger.warning("order.list interrompido: %s", exc)
                break
            result = _find_result(data) or {}
            nodes = _listing(result.get("orders"), "order")
            records.extend(r for r in (self._sale(n) for n in nodes) if r)
            if len(nodes) < 50:
                break
            page += 1
        return records

    @staticmethod
    def _sale(node: dict[str, Any]) -> SalesRecord | None:
        order = node.get("order_id") or node.get("order_number")
        if not order:
            return None
        status = str(node.get("order_status") or node.get("finished_status") or "").upper() or None
        finished = status in ("FINISHED", "SETTLED", "PAYMENT_COMPLETED_AND_SETTLED") or "FINISH" in (status or "")
        estimated = _to_float(node.get("estimated_paid_commission"))
        confirmed = _to_float(node.get("estimated_finished_commission")) if finished else None
        paid = node.get("paid_time")
        try:
            when = datetime.strptime(str(paid), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC) if paid else datetime.now(UTC)
        except ValueError:
            when = datetime.now(UTC)
        cancelled = bool(status and ("CANCEL" in status or "REFUND" in status or "INVALID" in status))
        return SalesRecord(
            external_order_id=f"{order}:{node.get('sub_order_id') or node.get('product_id') or ''}",
            occurred_at=when,
            quantity=_to_int(node.get("product_count")) or 1,
            currency="USD",  # a comissão do AliExpress é paga em dólar
            gross_amount=_to_float(node.get("paid_amount")),
            product_external_id=str(node["product_id"]) if node.get("product_id") is not None else None,
            product_title=node.get("product_title"),
            status=status,
            commission_estimated=None if (cancelled or finished) else estimated,
            commission_confirmed=None if cancelled else confirmed,
        )

    def search_competitor(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        try:
            batch = self.fetch_products(limit=limit, options=AliExpressAdapterOptions(keywords=[query], max_items=limit))
        except AliExpressError:
            return []
        return [
            {
                "platform": self.name, "query": query, "external_id": p.external_id, "title": p.title, "price": p.price,
                "currency": p.currency, "commission_pct": p.affiliate_commission_pct, "permalink": p.affiliate_url,
                "seller_external_id": p.seller_external_id,
            }
            for p in batch.products
        ]


def _find_result(data: dict[str, Any]) -> dict[str, Any] | None:
    """Acha `resp_result.result` dentro do envelope `<método>_response` (o nome muda por método)."""
    for key, value in data.items():
        if key.endswith("_response") and isinstance(value, dict):
            inner = value.get("resp_result", value)
            if isinstance(inner, dict):
                result = inner.get("result", inner)
                return result if isinstance(result, dict) else None
    return None


def _listing(container: Any, key: str) -> list[Any]:
    """A API embrulha listas como `{"product": [...]}`; aceita também a lista direta."""
    if isinstance(container, dict):
        container = container.get(key)
    if isinstance(container, list):
        return container
    return [container] if isinstance(container, dict) else []


def _pct(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip().rstrip("%").replace(",", ".")
    return _to_float(value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


__all__ = ["AliExpressAdapter", "AliExpressAdapterOptions", "AliExpressConfig", "AliExpressError", "AliExpressNotConfigured", "sign"]
