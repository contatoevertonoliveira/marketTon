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
    aws_authorization_header,
    aws_canonical_request,
    aws_signing_key,
    encode_uri_component,
    shopee_sign,
)
from integrations.marketplaces.tiktok_shop import (
    TikTokShopAdapter,
    TikTokShopConfig,
    TikTokShopNotConfigured,
    tiktok_shop_sign,
)


def headers_signed_list(canonical: str) -> list[str]:
    """Extrai a lista de headers assinados de uma requisição canônica SigV4.

    Estrutura: método, URI, query, headers canônicos, lista de headers, hash.
    A lista de headers é a penúltima linha.
    """
    return canonical.split("\n")[-2].split(";")


class TestShopeeSignature:
    def test_signature_is_hmac_sha256_of_the_declared_base(self) -> None:
        """Reproduz o cálculo de forma independente e compara."""
        partner_id, partner_key, path, timestamp = "1234", "secret", "/api/v2/product/get_item_list", 1700000000

        expected_base = f"{partner_id}{path}{timestamp}"
        expected = hmac.new(
            partner_key.encode(), expected_base.encode(), hashlib.sha256
        ).hexdigest()

        assert shopee_sign(partner_id, partner_key, path, timestamp) == expected

    def test_access_token_and_shop_id_enter_the_base(self) -> None:
        """A ordem de concatenação é parte do contrato da API."""
        partner_id, partner_key, path, timestamp = "1", "k", "/p", 100
        token, shop = "tok", "999"
        expected = hmac.new(
            partner_key.encode(),
            f"{partner_id}{path}{timestamp}{token}{shop}".encode(),
            hashlib.sha256,
        ).hexdigest()
        assert shopee_sign(partner_id, partner_key, path, timestamp, token, shop) == expected

    def test_signature_changes_with_timestamp(self) -> None:
        """Sem timestamp variável a assinatura seria reutilizável e expiraria."""
        assert shopee_sign("1", "k", "/p", 100) != shopee_sign("1", "k", "/p", 101)

    def test_missing_credentials_fail_loudly(self) -> None:
        with pytest.raises(SignatureError, match="partner_id"):
            shopee_sign("", "k", "/p", 100)
        with pytest.raises(SignatureError, match="partner_key"):
            shopee_sign("1", "", "/p", 100)


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


class TestAwsSigV4:
    def test_signing_key_is_deterministic_and_key_dependent(self) -> None:
        a = aws_signing_key("secret", "20260101", "us-east-1")
        b = aws_signing_key("secret", "20260101", "us-east-1")
        c = aws_signing_key("outro", "20260101", "us-east-1")
        d = aws_signing_key("secret", "20260102", "us-east-1")
        e = aws_signing_key("secret", "20260101", "eu-west-1")
        assert a == b
        assert len({a, c, d, e}) == 4, "chave deve variar com segredo, data e região"

    def test_missing_secret_fails_loudly(self) -> None:
        with pytest.raises(SignatureError, match="secret_key"):
            aws_signing_key("", "20260101", "us-east-1")

    def test_canonical_request_has_sorted_headers(self) -> None:
        canonical, headers = aws_canonical_request(
            host="webservices.amazon.com.br", path="/paapi5/searchitems", payload='{"a":1}'
        )
        lines = canonical.split("\n")
        assert lines[0] == "POST"
        assert lines[1] == "/paapi5/searchitems"
        # A query string vai no corpo, então a linha dela é vazia — é uma linha
        # própria na requisição canônica, e esquecê-la desloca tudo.
        assert lines[2] == ""

        # Headers em ordem alfabética é exigência da SigV4.
        signed_headers = headers_signed_list(canonical)
        assert signed_headers == sorted(signed_headers)
        assert signed_headers == sorted(headers)
        assert len(headers) == 4

    def test_authorization_header_shape(self) -> None:
        canonical, headers = aws_canonical_request(
            host="h", path="/p", payload="{}"
        )
        header = aws_authorization_header(
            access_key="AKIA",
            secret_key="s",
            region="us-east-1",
            host="h",
            canonical_request=canonical,
            signed_headers=";".join(sorted(headers)),
        )
        assert header.startswith("AWS4-HMAC-SHA256 Credential=AKIA/")
        assert "SignedHeaders=" in header
        assert "Signature=" in header
        assert "us-east-1/ProductAdvertisingAPI/aws4_request" in header

    def test_uri_encoding_follows_sigv4(self) -> None:
        """A SigV4 exige `%20` para espaço; `+` seria rejeitado."""
        assert encode_uri_component("fone bluetooth") == "fone%20bluetooth"
        assert encode_uri_component("a/b") == "a%2Fb"


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
        """A PA-API não lista o catálogo do associado: sem termo não há coleta."""
        adapter = AmazonAdapter(cfg=AmazonConfig(access_key="a", secret_key="s", partner_tag="t"))
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
