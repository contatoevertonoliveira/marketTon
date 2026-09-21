"""Adapter do Mercado Livre (API oficial).

Documentação: https://developers.mercadolivre.com.br/

Notas de honestidade dos dados, que definem o que este adapter **não** devolve:

* **Comissão de afiliado** não é exposta pela API de itens. O programa de afiliados
  tem painel próprio e não oferece endpoint público de comissão por item. O campo
  fica `None` e o Opportunity Score trata o fator como indisponível, reduzindo a
  `confidence` — em vez de estimar um percentual.
* **Vendas** não são acessíveis pela API pública de itens. `fetch_sales` devolve
  vazio e registra o motivo, porque uma lista vazia é honesta e um número inventado
  não é.
* **Avaliações** exigem uma chamada extra por item. São buscadas de forma opcional
  e limitada, e a falha é registrada como aviso em vez de silenciada.
"""
from __future__ import annotations

import logging
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
from integrations.marketplaces.token_store import TokenSet, TokenStore

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.mercadolibre.com"
AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


class MercadoLivreError(RuntimeError):
    """Falha ao falar com o Mercado Livre."""


class MercadoLivreNotConfigured(MercadoLivreError):
    """Credenciais ausentes. Erro de configuração, não de rede."""


@dataclass
class MLConfig:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    access_token: str = ""
    refresh_token: str = ""
    site_id: str = "MLB"
    country: str = "BR"
    api_url: str = DEFAULT_API_URL
    auth_url: str = AUTH_URL
    token_url: str = TOKEN_URL
    timeout: float = 20.0

    token_expires_at: datetime | None = None


@dataclass
class MLAdapterOptions:
    """Opções de coleta. Padrões conservadores para respeitar rate limit."""

    # Categorias cujos mais vendidos serão coletados. Vazio = todas as
    # categorias de topo do site (`/sites/{site}/categories`).
    category_ids: list[str] = field(default_factory=list)
    max_items: int = 50
    # Buscar avaliação de cada item custa uma chamada por item.
    fetch_reviews: bool = True
    max_review_lookups: int = 20
    fetch_seller_profile: bool = True
    # O perfil do vendedor também custa uma chamada por vendedor distinto.
    max_seller_lookups: int = 20
    page_size: int = 50
    warnings: list[str] = field(default_factory=list)


class MercadoLivreAdapter(MarketplaceAdapter):
    name = "mercado_livre"
    reliability = 1.0  # API oficial

    def __init__(self, cfg: MLConfig | None = None, token_store: TokenStore | None = None):
        self.cfg = cfg or self._load_config()
        self.tokens = token_store or TokenStore()
        self._load_persisted_tokens()

    # --- Credenciais ----------------------------------------------------------

    @staticmethod
    def _load_config() -> MLConfig:
        settings = get_settings()
        return MLConfig(
            client_id=settings.mercadolivre_client_id,
            client_secret=settings.mercadolivre_client_secret,
            redirect_uri=settings.mercadolivre_redirect_uri,
            access_token=settings.mercadolivre_access_token,
            refresh_token=settings.mercadolivre_refresh_token,
            site_id=settings.mercadolivre_site_id,
            country=settings.mercadolivre_country,
            timeout=settings.connector_timeout_seconds,
        )

    def _load_persisted_tokens(self) -> None:
        """Token persistido tem precedência sobre o `.env`: ele é mais recente."""
        stored = self.tokens.load(self.name)
        if stored is None:
            return
        if stored.access_token:
            self.cfg.access_token = stored.access_token
        if stored.refresh_token:
            self.cfg.refresh_token = stored.refresh_token
        self.cfg.token_expires_at = stored.expires_at

    def is_configured(self) -> bool:
        return bool(self.cfg.access_token or (self.cfg.client_id and self.cfg.client_secret))

    def _persist_tokens(self) -> None:
        self.tokens.save(
            self.name,
            TokenSet(
                access_token=self.cfg.access_token,
                refresh_token=self.cfg.refresh_token,
                expires_at=self.cfg.token_expires_at,
            ),
        )

    def get_status(self) -> dict[str, Any]:
        """Diagnóstico para páginas de configuração. Nunca levanta exceção."""
        return {
            "connector": self.name,
            "configured": self.is_configured(),
            "has_access_token": bool(self.cfg.access_token),
            "has_refresh_token": bool(self.cfg.refresh_token),
            "has_client_credentials": bool(self.cfg.client_id and self.cfg.client_secret),
            "token_expires_at": self.cfg.token_expires_at.isoformat() if self.cfg.token_expires_at else None,
            "reliability": self.reliability,
        }

    # --- HTTP -----------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.access_token}"} if self.cfg.access_token else {}

    def _api_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """GET com uma tentativa de renovação de token em caso de 401."""
        url = path if path.startswith("http") else f"{self.cfg.api_url}{path}"
        for attempt in range(2):
            try:
                response = requests.get(
                    url, headers=self._headers(), params=params, timeout=self.cfg.timeout
                )
            except requests.RequestException as exc:
                raise MercadoLivreError(f"falha de rede em {url}: {exc}") from exc

            if response.status_code == 200:
                return response.json()
            if response.status_code == 401 and attempt == 0 and self._refresh_access_token():
                continue
            if response.status_code == 404:
                return None
            raise MercadoLivreError(
                f"HTTP {response.status_code} em {url}: {response.text[:300]}"
            )
        return None

    def _refresh_access_token(self) -> bool:
        if not (self.cfg.refresh_token and self.cfg.client_id and self.cfg.client_secret):
            return False
        try:
            response = requests.post(
                self.cfg.token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.cfg.refresh_token,
                    "client_id": self.cfg.client_id,
                    "client_secret": self.cfg.client_secret,
                },
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as exc:
            logger.warning("renovação de token falhou: %s", exc)
            return False

        if response.status_code != 200:
            logger.warning(
                "renovação de token falhou: HTTP %s — %s", response.status_code, response.text[:500]
            )
            return False

        data = response.json()
        self.cfg.access_token = data.get("access_token", self.cfg.access_token)
        self.cfg.refresh_token = data.get("refresh_token", self.cfg.refresh_token)
        expires_in = data.get("expires_in")
        if expires_in:
            self.cfg.token_expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))
        # Persistir é o ponto: sem isto o token novo se perdia no restart.
        self._persist_tokens()
        return True

    # --- OAuth ----------------------------------------------------------------

    def build_authorization_url(self, state: str, *, code_challenge: str | None = None) -> str:
        if not self.cfg.client_id:
            raise MercadoLivreNotConfigured("MARKETPLACE_MERCADOLIVRE_CLIENT_ID não configurado.")
        url = (
            f"{self.cfg.auth_url}?response_type=code&client_id={self.cfg.client_id}"
            f"&redirect_uri={self.cfg.redirect_uri}&state={state}"
        )
        if code_challenge:
            # PKCE (RFC 7636): alguns apps da Mercado Livre exigem isso — descoberto
            # ao vivo pela troca de token falhando com "code_verifier is a required
            # parameter" quando a autorização não carregava o challenge.
            url += f"&code_challenge={code_challenge}&code_challenge_method=S256"
        return url

    def exchange_code_for_token(self, code: str, *, code_verifier: str | None = None) -> TokenSet:
        if not (self.cfg.client_id and self.cfg.client_secret):
            raise MercadoLivreNotConfigured("client_id e client_secret são obrigatórios.")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.cfg.client_id,
            "client_secret": self.cfg.client_secret,
            "redirect_uri": self.cfg.redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        try:
            response = requests.post(
                self.cfg.token_url,
                data=data,
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as exc:
            raise MercadoLivreError(f"troca de código por token falhou: {exc}") from exc

        if response.status_code != 200:
            # `raise_for_status()` descarta o corpo da resposta — e é nele que a ML
            # explica o motivo real (`invalid_grant`, redirect_uri divergente, etc.).
            raise MercadoLivreError(
                f"troca de código por token falhou: HTTP {response.status_code} — {response.text[:500]}"
            )

        data = response.json()
        expires_in = data.get("expires_in")
        expires_at = None
        if expires_in:
            expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))

        tokens = TokenSet(
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            expires_at=expires_at,
        )
        self.cfg.access_token = tokens.access_token
        self.cfg.refresh_token = tokens.refresh_token
        self.cfg.token_expires_at = tokens.expires_at
        self._persist_tokens()
        return tokens

    # --- Coleta ---------------------------------------------------------------

    def fetch_products(
        self, *, limit: int | None = None, options: MLAdapterOptions | None = None
    ) -> ConnectorBatch:
        """Descoberta pelos mais vendidos de cada categoria (`/highlights`).

        A busca pública `/sites/{site}/search` devolve 403 para apps comuns
        (bloqueio da própria ML, sem aviso oficial), e o catálogo da conta
        conectada (`/users/{id}/items/search`) não serve à afiliação. Os
        `highlights` respondem com o mesmo token, já vêm ranqueados por venda
        (a `position` vira `ranking_position`) e cobrem qualquer vendedor.
        Os IDs são de produto de catálogo: nome/fotos/marca vêm de
        `/products/{id}` e preço/vendedor da oferta mais barata em
        `/products/{id}/items`.
        """
        options = options or MLAdapterOptions()
        if limit is not None:
            options.max_items = limit

        collected_at = datetime.now(UTC)
        if not self.cfg.access_token:
            raise MercadoLivreNotConfigured(
                "Sem access_token do Mercado Livre. Autorize o app em /marketplaces/mercadolivre/auth "
                "ou preencha MARKETPLACE_MERCADOLIVRE_ACCESS_TOKEN no .env."
            )

        site_id = self.cfg.site_id
        category_ids = options.category_ids or self._top_level_categories(site_id)
        warnings = list(options.warnings)
        if not category_ids:
            warnings.append("nenhuma categoria disponível para consultar os mais vendidos")

        budget = max(1, options.max_items // max(1, len(category_ids)))
        products: list[ConnectorProduct] = []
        seen: set[str] = set()
        seller_cache: dict[str, dict[str, Any]] = {}

        for category_id in category_ids:
            if len(products) >= options.max_items:
                break
            try:
                highlights = self._api_get(f"/highlights/{site_id}/category/{category_id}")
            except MercadoLivreError as exc:
                warnings.append(f"mais vendidos de {category_id} indisponíveis: {exc}")
                continue
            entries = [e for e in (highlights or {}).get("content", []) if e.get("type") == "PRODUCT"]

            taken = 0
            for entry in entries:
                if taken >= budget or len(products) >= options.max_items:
                    break
                product_id = str(entry.get("id"))
                if product_id in seen:
                    continue
                try:
                    product = self._product_from_catalog(
                        product_id, entry.get("position"), category_id, options, warnings, seller_cache
                    )
                except MercadoLivreError as exc:
                    warnings.append(f"produto {product_id} ignorado: {exc}")
                    continue
                if product is None:
                    continue
                seen.add(product_id)
                products.append(product)
                taken += 1

        return ConnectorBatch(
            connector=self.name,
            products=products,
            collected_at=collected_at,
            endpoint=f"{self.cfg.api_url}/highlights/{site_id}/category/{{id}} (BEST_SELLER)",
            reliability=self.reliability,
            warnings=warnings,
            raw={"site_id": site_id, "category_ids": category_ids, "product_ids": sorted(seen)[:200]},
        )

    def _top_level_categories(self, site_id: str) -> list[str]:
        try:
            categories = self._api_get(f"/sites/{site_id}/categories")
        except MercadoLivreError as exc:
            logger.warning("categorias de %s indisponíveis: %s", site_id, exc)
            return []
        return [str(c["id"]) for c in (categories or []) if c.get("id")]

    def _product_from_catalog(
        self,
        product_id: str,
        position: int | None,
        category_id: str,
        options: MLAdapterOptions,
        warnings: list[str],
        seller_cache: dict[str, dict[str, Any]],
    ) -> ConnectorProduct | None:
        detail = self._api_get(f"/products/{product_id}")
        if not detail:
            return None
        listings = (self._api_get(f"/products/{product_id}/items") or {}).get("results") or []
        priced = [l for l in listings if l.get("price") is not None]
        offer = min(priced, key=lambda l: l["price"]) if priced else {}

        attributes = {
            attr.get("id"): attr.get("value_name")
            for attr in (detail.get("attributes") or [])
            if attr.get("id")
        }
        seller_id = str(offer.get("seller_id") or "") or None
        profile = self._seller_profile(seller_id, options, warnings, seller_cache)
        price = offer.get("price")
        original_price = offer.get("original_price")
        discount_pct = None
        if price and original_price and float(original_price) > 0:
            discount_pct = round((1 - float(price) / float(original_price)) * 100, 2)

        images = [p.get("url") for p in (detail.get("pictures") or []) if p.get("url")]
        item_id = offer.get("item_id")
        return ConnectorProduct(
            external_id=product_id,
            title=str(detail.get("name") or "").strip(),
            category_id=offer.get("category_id") or category_id,
            brand=attributes.get("BRAND"),
            model=attributes.get("MODEL"),
            condition={"new": "novo", "used": "usado"}.get(offer.get("condition"), None),
            seller_external_id=seller_id,
            seller_nickname=profile.get("nickname"),
            seller_reputation_level=profile.get("reputation_level"),
            seller_reputation_score=profile.get("reputation_score"),
            seller_total_sales=profile.get("total_sales"),
            seller_positive_rating_pct=profile.get("positive_rating_pct"),
            seller_feedback_count=profile.get("feedback_count"),
            seller_is_official_store=bool(offer.get("official_store_id")) if offer else None,
            seller_power_seller_status=profile.get("power_seller_status"),
            currency=offer.get("currency_id"),
            price=float(price) if price is not None else None,
            original_price=float(original_price) if original_price is not None else None,
            discount_pct=discount_pct,
            # A API não expõe comissão. Só há valor quando o operador cadastrou a
            # taxa da categoria — estimativa declarada em `commission_source`.
            affiliate_commission_pct=self.commission_rates.get(category_id),
            is_available=bool(offer) or None,
            # Posição no ranking de mais vendidos: sinal de demanda comparável.
            ranking_position=position,
            has_promotion=bool(discount_pct) or None,
            product_url=f"https://www.mercadolivre.com.br/p/{product_id}",
            images=images or None,
            attributes={
                "catalog_product_id": product_id,
                "item_id": item_id,
                **({"commission_source": "operator_table"} if category_id in self.commission_rates else {}),
                **attributes,
            },
        )

    def _normalize_item(
        self,
        detail: dict[str, Any],
        *,
        site_id: str,
        options: MLAdapterOptions,
        warnings: list[str],
        seller_cache: dict[str, dict[str, Any]],
    ) -> ConnectorProduct:
        seller_id = str(detail.get("seller_id") or "") or None
        seller_profile = self._seller_profile(seller_id, options, warnings, seller_cache)

        price = detail.get("price")
        original_price = detail.get("original_price")
        discount_pct = None
        if price and original_price and float(original_price) > 0:
            discount_pct = round((1 - float(price) / float(original_price)) * 100, 2)

        pictures = detail.get("pictures") or []
        images = [pic.get("secure_url") or pic.get("url") for pic in pictures if pic]

        attributes = {
            attr.get("id"): attr.get("value_name")
            for attr in (detail.get("attributes") or [])
            if attr.get("id")
        }
        brand = attributes.get("BRAND")
        model = attributes.get("MODEL")

        shipping = detail.get("shipping") or {}
        raw_condition = detail.get("condition")
        condition = {"new": "novo", "used": "usado", "not_specified": None}.get(raw_condition, raw_condition)

        return ConnectorProduct(
            external_id=str(detail.get("id")),
            title=str(detail.get("title") or "").strip(),
            category_id=detail.get("category_id"),
            brand=brand,
            model=model,
            condition=condition,
            seller_external_id=seller_id,
            seller_nickname=seller_profile.get("nickname"),
            seller_reputation_level=seller_profile.get("reputation_level"),
            seller_reputation_score=seller_profile.get("reputation_score"),
            seller_total_sales=seller_profile.get("total_sales"),
            seller_positive_rating_pct=seller_profile.get("positive_rating_pct"),
            seller_feedback_count=seller_profile.get("feedback_count"),
            seller_is_official_store=seller_profile.get("is_official_store"),
            seller_power_seller_status=seller_profile.get("power_seller_status"),
            seller_active_listings=seller_profile.get("active_listings"),
            seller_active_promotions=seller_profile.get("active_promotions"),
            currency=detail.get("currency_id"),
            price=float(price) if price is not None else None,
            original_price=float(original_price) if original_price is not None else None,
            discount_pct=discount_pct,
            # A API de itens não expõe comissão de afiliado. `None` é a resposta
            # correta; estimar seria fabricar dado (briefing seção 2).
            affiliate_commission_pct=None,
            affiliate_commission_fixed=None,
            available_quantity=detail.get("available_quantity"),
            sold_quantity=detail.get("sold_quantity"),
            is_available=detail.get("status") == "active" if detail.get("status") else None,
            # Preenchidos por `_attach_reviews`.
            rating=None,
            review_count=None,
            has_promotion=bool(discount_pct) or None,
            coupons=None,
            product_url=detail.get("permalink"),
            affiliate_url=None,
            images=images or None,
            attributes=attributes or None,
            # `sold_quantity` é acumulado, não do período; não serve como métrica
            # temporal. Fica em `Product.sold_quantity`.
            sold_last_period=None,
            views=None,
            visits=None,
            wishlist_count=None,
        )

    def _seller_profile(
        self,
        seller_id: str | None,
        options: MLAdapterOptions,
        warnings: list[str],
        cache: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Perfil do vendedor, insumo do Producer Momentum Score.

        Chamadas são limitadas por `max_seller_lookups`: sem isso, um catálogo com
        muitos vendedores distintos geraria uma chamada por item e bateria no rate
        limit do Mercado Livre.
        """
        if not seller_id or not options.fetch_seller_profile:
            return {}
        if seller_id in cache:
            return cache[seller_id]

        if len(cache) >= options.max_seller_lookups:
            warnings.append(
                f"limite de {options.max_seller_lookups} consultas de perfil de vendedor "
                "atingido; alguns produtores ficaram sem sinais de momentum"
            )
            cache[seller_id] = {}
            return {}

        try:
            user = self._api_get(f"/users/{seller_id}")
        except MercadoLivreError as exc:
            warnings.append(f"perfil do vendedor {seller_id} indisponível: {exc}")
            cache[seller_id] = {}
            return {}

        if not user:
            cache[seller_id] = {}
            return {}

        reputation = user.get("seller_reputation") or {}
        transactions = reputation.get("transactions") or {}
        ratings = transactions.get("ratings") or {}
        metrics = reputation.get("metrics") or {}
        sales_metrics = metrics.get("sales") or {}
        claims_metrics = metrics.get("claims") or {}

        tags = user.get("tags") or []
        profile: dict[str, Any] = {
            "nickname": user.get("nickname"),
            "reputation_level": reputation.get("level_id"),
            # `reputation_score` como nota sintética: usamos o percentual de
            # avaliações positivas, que é o sinal comparável entre marketplaces.
            "reputation_score": _to_float(ratings.get("positive")),
            "total_sales": _to_int(transactions.get("completed") or transactions.get("total")),
            "positive_rating_pct": _to_float(ratings.get("positive")),
            "feedback_count": _to_int(ratings.get("total")),
            "is_official_store": "official_store" in tags if tags else None,
            "power_seller_status": reputation.get("power_seller_status"),
            "active_listings": _to_int(sales_metrics.get("completed")),
            # A API não expõe contagem de promoções ativas por vendedor.
            "active_promotions": None,
            "claims_rate": _to_float(claims_metrics.get("rate")),
        }

        cache[seller_id] = profile
        return profile

    def _attach_reviews(
        self, product: ConnectorProduct, item_id: str, warnings: list[str]
    ) -> None:
        """Busca nota e volume de avaliações. Chamada extra, falha é registrada."""
        try:
            data = self._api_get(f"/reviews/item/{item_id}")
        except MercadoLivreError as exc:
            warnings.append(f"avaliações de {item_id} indisponíveis: {exc}")
            return
        if not data:
            return
        rating_average = data.get("rating_average")
        paging = data.get("paging") or {}
        product.rating = _to_float(rating_average)
        product.review_count = paging.get("total")

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        """A API pública de itens não expõe vendas de afiliado.

        O programa de afiliados do Mercado Livre tem painel próprio e não publica
        endpoint de comissão por venda. Devolver vazio é a resposta correta: um
        número estimado aqui contaminaria receita e comissão do briefing §9–§10.
        """
        logger.info(
            "fetch_sales do Mercado Livre não implementado: a API de itens não expõe "
            "vendas nem comissão de afiliado"
        )
        return []

    def search_competitor(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Busca anúncios concorrentes. Insumo do Creative Saturation Score."""
        data = self._api_get(
            f"/sites/{self.cfg.site_id}/search", {"q": query, "limit": min(limit, 50)}
        )
        if not data or not data.get("results"):
            return []
        results = []
        for item in data["results"]:
            results.append(
                {
                    "platform": self.name,
                    "query": query,
                    "external_id": item.get("id"),
                    "title": item.get("title"),
                    "price": item.get("price"),
                    "currency": item.get("currency_id"),
                    "seller_external_id": str((item.get("seller") or {}).get("id") or "") or None,
                    "condition": item.get("condition"),
                    "permalink": item.get("permalink"),
                    "sold_quantity": item.get("sold_quantity"),
                    "available_quantity": item.get("available_quantity"),
                    "listing_type_id": item.get("listing_type_id"),
                }
            )
        return results


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
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "MLAdapterOptions",
    "MLConfig",
    "MercadoLivreAdapter",
    "MercadoLivreError",
    "MercadoLivreNotConfigured",
]
