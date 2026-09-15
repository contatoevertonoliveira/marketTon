import hashlib
import json
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import amazon_client, shopee_client
from .ingestion import AmazonDiscoveryAdapter, CredentialsMissing, ShopeeDiscoveryAdapter
from .models import Marketplace, MarketplaceCredential, Product


def make_product(**overrides) -> Product:
    marketplace, _ = Marketplace.objects.get_or_create(
        slug="mercado_livre", defaults={"name": "Mercado Livre", "integration_status": "live"}
    )
    defaults = dict(
        marketplace=marketplace,
        external_id="MLB123",
        title="Fone Bluetooth Teste",
        source="mercado_livre_search",
        collected_at=timezone.now(),
    )
    defaults.update(overrides)
    return Product.objects.create(**defaults)


class ProductModelTests(TestCase):
    def test_unique_product_per_marketplace(self):
        make_product(external_id="A1")
        with self.assertRaises(Exception):
            make_product(external_id="A1")


class MarketplaceCredentialApiTests(TestCase):
    def test_put_credentials_never_echoes_secrets_back(self):
        Marketplace.objects.get_or_create(slug="shopee", defaults={"name": "Shopee"})
        client = APIClient()
        resp = client.put(
            "/api/marketplaces/shopee/credentials/",
            {"enabled": True, "mode": "affiliate", "scope": "national", "values": {"app_id": "abc", "secret": "topsecret"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertNotIn("topsecret", json.dumps(body))
        self.assertEqual(body["credential_status"], {"app_id": True, "secret": True, "region": False})

    def test_blank_value_does_not_erase_existing_secret(self):
        marketplace, _ = Marketplace.objects.get_or_create(slug="shopee", defaults={"name": "Shopee"})
        MarketplaceCredential.objects.create(marketplace=marketplace, values={"app_id": "abc", "secret": "topsecret"})
        client = APIClient()
        resp = client.put(
            "/api/marketplaces/shopee/credentials/",
            {"values": {"app_id": "abc", "secret": ""}},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        marketplace.refresh_from_db()
        self.assertEqual(marketplace.credential.values["secret"], "topsecret")


class ShopeeSigningTests(TestCase):
    def test_sign_matches_hand_computed_sha256(self):
        expected = hashlib.sha256(b"app1231700000000{}secretxyz").hexdigest()
        actual = shopee_client.sign("app123", 1700000000, "{}", "secretxyz")
        self.assertEqual(actual, expected)

    def test_search_products_without_credentials_returns_empty(self):
        self.assertEqual(shopee_client.search_products("", "", "fone"), [])


class ShopeeDiscoveryAdapterTests(TestCase):
    def test_raises_credentials_missing_when_unconfigured(self):
        with self.assertRaises(CredentialsMissing):
            ShopeeDiscoveryAdapter().discover(keywords=["fone"])


class AmazonSigningTests(TestCase):
    def test_search_items_without_credentials_returns_empty(self):
        self.assertEqual(amazon_client.search_items(access_key="", secret_key="", associate_tag="", region="us-east-1", host="", keywords="x"), [])

    @patch("apps.catalog.amazon_client.requests.post")
    def test_search_items_sends_well_formed_sigv4_headers(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"SearchResult": {"Items": []}}

        amazon_client.search_items(
            access_key="AKIDEXAMPLE",
            secret_key="secretkey",
            associate_tag="mytag-20",
            region="us-east-1",
            host="webservices.amazon.com",
            keywords="fone bluetooth",
        )

        self.assertTrue(mock_post.called)
        _args, kwargs = mock_post.call_args
        headers = kwargs["headers"]
        self.assertTrue(headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/"))
        self.assertIn("SignedHeaders=content-encoding;content-type;host;x-amz-date;x-amz-target", headers["Authorization"])
        self.assertIn("Signature=", headers["Authorization"])
        self.assertEqual(headers["host"], "webservices.amazon.com")
        self.assertEqual(headers["x-amz-target"], amazon_client.TARGET)

    def test_build_affiliate_url_is_deterministic(self):
        url = amazon_client.build_affiliate_url("B000123", "mytag-20", "www.amazon.com.br")
        self.assertEqual(url, "https://www.amazon.com.br/dp/B000123?tag=mytag-20")


class AmazonDiscoveryAdapterTests(TestCase):
    def test_raises_credentials_missing_when_unconfigured(self):
        with self.assertRaises(CredentialsMissing):
            AmazonDiscoveryAdapter().discover(keywords=["fone"])


class MercadoLivreOAuthFlowTests(TestCase):
    def test_start_requires_client_id_and_redirect_uri(self):
        client = APIClient()
        resp = client.post("/api/marketplaces/mercado_livre/oauth/start/")
        self.assertEqual(resp.status_code, 400)

    def test_full_flow_persists_tokens_from_callback(self):
        marketplace, _ = Marketplace.objects.get_or_create(slug="mercado_livre", defaults={"name": "Mercado Livre"})
        MarketplaceCredential.objects.create(
            marketplace=marketplace,
            values={"client_id": "cid", "client_secret": "csecret", "redirect_uri": "http://localhost:8001/cb"},
        )
        client = APIClient()
        start_resp = client.post("/api/marketplaces/mercado_livre/oauth/start/")
        self.assertEqual(start_resp.status_code, 200)
        self.assertIn("auth.mercadolivre.com.br", start_resp.json()["url"])

        marketplace.refresh_from_db()
        state = marketplace.credential.values["_oauth_state"]

        with patch(
            "integrations.marketplaces.mercado_livre.MercadoLivreAdapter.exchange_code_for_token",
            return_value={"access_token": "AT123", "refresh_token": "RT456"},
        ):
            cb_resp = client.get(f"/api/marketplaces/mercado_livre/oauth/callback/?code=xyz&state={state}")
        self.assertEqual(cb_resp.status_code, 200)
        self.assertIn(b"Conectado com sucesso", cb_resp.content)

        marketplace.refresh_from_db()
        self.assertEqual(marketplace.credential.values["access_token"], "AT123")
        self.assertEqual(marketplace.credential.values["refresh_token"], "RT456")
        self.assertNotIn("_oauth_state", marketplace.credential.values)

    def test_callback_rejects_mismatched_state(self):
        marketplace, _ = Marketplace.objects.get_or_create(slug="mercado_livre", defaults={"name": "Mercado Livre"})
        MarketplaceCredential.objects.create(
            marketplace=marketplace, values={"client_id": "cid", "client_secret": "csecret", "_oauth_state": "real"}
        )
        client = APIClient()
        resp = client.get("/api/marketplaces/mercado_livre/oauth/callback/?code=xyz&state=forged")
        self.assertEqual(resp.status_code, 400)
