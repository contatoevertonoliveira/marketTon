"""Testes dos conectores de marketplace.

O que estes testes cobrem, e por quê:

1. **Assinatura HMAC** — a parte mais fácil de errar em silêncio. Uma assinatura
   inválida produz um 401 genérico sem dizer o que está errado, então a lógica de
   assinatura é testada contra valores calculados independentemente.
2. **Falha explícita sem credencial** — um adapter mal configurado deve levantar
   erro nomeado, não devolver lista vazia. Lista vazia é indistinguível de
   "o vendedor não tem produtos", e foi assim que o projeto anterior passou a
   exibir dados fabricados sem que ninguém percebesse.
3. **Honestidade sobre dado ausente** — comissão e vendas ficam `None`/vazio com
   justificativa, nunca estimados.
"""
from __future__ import annotations

import hashlib
import hmac

import pytest

from integrations.marketplaces.amazon import (
    AmazonAdapter,
    AmazonAdapterOptions,
    AmazonConfig,
    AmazonError,
    AmazonNotConfigured,
)
from integrations.marketplaces.base import ConnectorBatch, ConnectorProduct, MarketplaceAdapter
from integrations.marketplaces.mercado_livre import (
    MercadoLivreAdapter,
    MercadoLivreNotConfigured,
)
from integrations.marketplaces.shopee import (
    ShopeeAdapter,
    ShopeeConfig,
    ShopeeNotConfigured,
)
from integrations.marketplaces.signing import (
    SignatureError,
    shopee_affiliate_auth_header,
    shopee_affiliate_sign,
)
from integrations.marketplaces.tiktok_shop import (
    TikTokShopAdapter,
    TikTokShopConfig,
    TikTokShopNotConfigured,
    tiktok_shop_sign,
)


class TestShopeeAffiliateSignature:
    def test_signature_is_plain_sha256_of_the_declared_base(self) -> None:
        """Reproduz o cálculo de forma independente e compara.

        Diferente da Open Platform (HMAC), a Affiliate Open API usa um hash
        SHA256 comum com o `secret` dentro da string, não como chave.
        """
        app_id, secret, timestamp, payload = "1234", "secret", 1700000000, '{"query":"{}"}'

        expected = hashlib.sha256(f"{app_id}{timestamp}{payload}{secret}".encode()).hexdigest()

        assert shopee_affiliate_sign(app_id, secret, timestamp, payload) == expected

    def test_signature_changes_with_timestamp(self) -> None:
        assert shopee_affiliate_sign("1", "s", 100, "{}") != shopee_affiliate_sign("1", "s", 101, "{}")

    def test_signature_changes_with_payload(self) -> None:
        assert shopee_affiliate_sign("1", "s", 100, '{"a":1}') != shopee_affiliate_sign("1", "s", 100, '{"a":2}')

    def test_missing_credentials_fail_loudly(self) -> None:
        with pytest.raises(SignatureError, match="app_id"):
            shopee_affiliate_sign("", "s", 100, "{}")
        with pytest.raises(SignatureError, match="secret"):
            shopee_affiliate_sign("1", "", 100, "{}")

    def test_auth_header_shape(self) -> None:
        header = shopee_affiliate_auth_header("1234", "secret", 1700000000, "{}")
        assert header.startswith("SHA256 Credential=1234, Timestamp=1700000000, Signature=")


class TestTikTokShopSignature:
    def test_secret_wraps_the_base_string(self) -> None:
        """Detalhe específico desta API: o segredo envolve a string, não só assina."""
        app_key, secret, path, timestamp = "key", "sec", "/product/search", 1700000000
        expected_base = f"{secret}{path}{timestamp}{secret}"
        expected = hmac.new(secret.encode(), expected_base.encode(), hashlib.sha256).hexdigest()
        assert tiktok_shop_sign(app_key, secret, path, timestamp) == expected

    def test_query_and_body_change_the_signature(self) -> None:
        base = tiktok_shop_sign("k", "s", "/p", 1)
        assert tiktok_shop_sign("k", "s", "/p", 1, query="app_keyk") != base
        assert tiktok_shop_sign("k", "s", "/p", 1, body='{"a":1}') != base


class TestUnconfiguredAdaptersFailLoudly:
    """Um adapter sem credencial deve nomear o erro, não devolver vazio."""

    def test_mercado_livre_without_token(self) -> None:
        adapter = MercadoLivreAdapter()
        assert not adapter.is_configured()
        with pytest.raises(MercadoLivreNotConfigured, match="access_token"):
            adapter.fetch_products()

    def test_shopee_without_credentials(self) -> None:
        adapter = ShopeeAdapter(cfg=ShopeeConfig())
        assert not adapter.is_configured()
        with pytest.raises(ShopeeNotConfigured, match="Credenciais"):
            adapter.fetch_products()

    def test_amazon_without_credentials(self) -> None:
        adapter = AmazonAdapter(cfg=AmazonConfig())
        assert not adapter.is_configured()
        with pytest.raises(AmazonNotConfigured, match="Credenciais"):
            adapter.fetch_products(options=AmazonAdapterOptions(keyword="fone"))

    def test_amazon_requires_a_search_keyword(self) -> None:
        """A Creators API não lista o catálogo do associado: sem termo não há coleta."""
        adapter = AmazonAdapter(cfg=AmazonConfig(client_id="a", client_secret="s", partner_tag="t"))
        assert adapter.is_configured()
        with pytest.raises(AmazonError, match="termo de busca"):
            adapter.fetch_products(options=AmazonAdapterOptions(keyword=""))

    def test_tiktok_shop_without_credentials(self) -> None:
        adapter = TikTokShopAdapter(cfg=TikTokShopConfig())
        assert not adapter.is_configured()
        with pytest.raises(TikTokShopNotConfigured, match="(?i)access token|credenciais"):
            adapter.fetch_products()

    def test_status_never_raises(self) -> None:
        """Páginas de configuração precisam de diagnóstico sem exceção."""
        for adapter in (
            MercadoLivreAdapter(),
            ShopeeAdapter(cfg=ShopeeConfig()),
            AmazonAdapter(cfg=AmazonConfig()),
            TikTokShopAdapter(cfg=TikTokShopConfig()),
        ):
            status = adapter.get_status()
            assert status["configured"] is False
            assert "reliability" in status


class TestHonestAboutMissingData:
    """Comissão e vendas não são estimadas; são declaradas ausentes."""

    def test_mercado_livre_does_not_invent_commission(self) -> None:
        adapter = MercadoLivreAdapter()
        assert adapter.fetch_sales() == []

    def test_shopee_does_not_invent_sales_or_competitors(self) -> None:
        adapter = ShopeeAdapter(cfg=ShopeeConfig())
        assert adapter.fetch_sales() == []
        assert adapter.search_competitor("fone") == []

    def test_amazon_does_not_invent_sales(self) -> None:
        adapter = AmazonAdapter(cfg=AmazonConfig())
        assert adapter.fetch_sales() == []

    def test_tiktok_shop_does_not_invent_sales(self) -> None:
        adapter = TikTokShopAdapter(cfg=TikTokShopConfig())
        assert adapter.fetch_sales() == []
        assert adapter.search_competitor("fone") == []

    def test_mercado_livre_normalization_leaves_commission_none(self) -> None:
        """A API de itens do ML não expõe comissão de afiliado."""
        adapter = MercadoLivreAdapter()
        detail = {
            "id": "MLB1",
            "title": "Fone Bluetooth",
            "price": 99.9,
            "original_price": 149.9,
            "currency_id": "BRL",
            "available_quantity": 12,
            "sold_quantity": 40,
            "status": "active",
            "permalink": "https://produto.mercadolivre.com.br/MLB-1",
            "pictures": [{"secure_url": "https://img/1.jpg"}],
            "attributes": [{"id": "BRAND", "value_name": "Acme"}],
            "seller_id": 999,
        }
        product = adapter._normalize_item(
            detail,
            site_id="MLB",
            options=type("O", (), {"fetch_seller_profile": False, "warnings": [], "max_seller_lookups": 0})(),
            warnings=[],
            seller_cache={},
        )
        assert product.affiliate_commission_pct is None
        assert product.affiliate_commission_fixed is None
        assert product.brand == "Acme"
        assert product.external_id == "MLB1"
        assert product.discount_pct == pytest.approx(33.36, abs=0.01)
        assert product.images == ["https://img/1.jpg"]

    def test_mercado_livre_condition_is_translated(self) -> None:
        adapter = MercadoLivreAdapter()

        def normalize(condition):
            return adapter._normalize_item(
                {"id": "X", "title": "t", "condition": condition, "price": 1},
                site_id="MLB",
                options=type("O", (), {"fetch_seller_profile": False, "warnings": [], "max_seller_lookups": 0})(),
                warnings=[],
                seller_cache={},
            ).condition

        assert normalize("new") == "novo"
        assert normalize("used") == "usado"
        assert normalize("not_specified") is None


class TestContractCompliance:
    @pytest.mark.parametrize(
        "adapter",
        [
            MercadoLivreAdapter(),
            ShopeeAdapter(cfg=ShopeeConfig()),
            AmazonAdapter(cfg=AmazonConfig()),
            TikTokShopAdapter(cfg=TikTokShopConfig()),
        ],
    )
    def test_implements_the_marketplace_contract(self, adapter) -> None:
        assert isinstance(adapter, MarketplaceAdapter)
        assert adapter.name
        assert 0.0 <= adapter.reliability <= 1.0
        for method in ("fetch_products", "fetch_sales", "search_competitor", "is_configured", "get_status"):
            assert callable(getattr(adapter, method))

    def test_connector_product_without_signals_is_detectable(self) -> None:
        """Sem preço nem demanda, o produto não é analisável — e isso é detectável."""
        assert not ConnectorProduct(external_id="X", title="sem dado").has_any_market_signal()
        assert ConnectorProduct(external_id="X", title="com preço", price=1.0).has_any_market_signal()

    def test_batch_reports_emptiness(self) -> None:
        assert ConnectorBatch(connector="x").is_empty
        assert not ConnectorBatch(connector="x", products=[ConnectorProduct("1", "t", price=1.0)]).is_empty


class TestMercadoLivreCommissionTable:
    """A API não informa comissão: só há valor se o operador cadastrou a categoria."""

    def _adapter(self, rates):
        adapter = MercadoLivreAdapter()
        adapter.commission_rates = rates

        def fake_get(path, params=None):
            if path.endswith("/items"):
                return {"results": [{"item_id": "MLB9", "price": 50, "seller_id": 7, "condition": "new"}]}
            return {"name": "Produto", "pictures": [], "attributes": []}

        adapter._api_get = fake_get
        return adapter

    def _product(self, adapter):
        options = type("O", (), {"fetch_seller_profile": False, "warnings": [], "max_seller_lookups": 0})()
        return adapter._product_from_catalog("MLB1", 1, "MLB1000", options, [], {})

    def test_rate_comes_only_from_the_operator_table(self) -> None:
        product = self._product(self._adapter({"MLB1000": 7.5}))
        assert product.affiliate_commission_pct == 7.5
        assert product.attributes["commission_source"] == "operator_table"

    def test_no_row_means_no_estimate(self) -> None:
        product = self._product(self._adapter({}))
        assert product.affiliate_commission_pct is None
        assert "commission_source" not in product.attributes
        assert product.ranking_position == 1
