"""Mercado Livre adapter com OAuth 2.0 (Server Side)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from integrations.marketplaces.base import MarketplaceAdapter


@dataclass
class MLConfig:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    access_token: str = ""
    refresh_token: str = ""
    country: str = "BR"
    api_url: str = "https://api.mercadolibre.com"
    auth_url: str = "https://auth.mercadolivre.com.br/authorization"
    token_url: str = "https://api.mercadolivre.com.br/oauth/token"


class MercadoLivreAdapter(MarketplaceAdapter):
    name = "mercado_livre"

    def __init__(self, cfg: MLConfig | None = None):
        self.cfg = cfg or self._load_env()

    @staticmethod
    def _load_env() -> MLConfig:
        return MLConfig(
            client_id=os.getenv("MARKETPLACE_MERCADOLIVRE_CLIENT_ID", ""),
            client_secret=os.getenv("MARKETPLACE_MERCADOLIVRE_CLIENT_SECRET", ""),
            redirect_uri=os.getenv("MARKETPLACE_MERCADOLIVRE_REDIRECT_URI", ""),
            access_token=os.getenv("MARKETPLACE_MERCADOLIVRE_ACCESS_TOKEN", ""),
            refresh_token=os.getenv("MARKETPLACE_MERCADOLIVRE_REFRESH_TOKEN", ""),
            country=os.getenv("MARKETPLACE_MERCADOLIVRE_COUNTRY", "BR"),
            api_url=os.getenv("MARKETPLACE_MERCADOLIVRE_API_URL", "https://api.mercadolibre.com"),
            auth_url="https://auth.mercadolivre.com.br/authorization",
            token_url="https://api.mercadolivre.com.br/oauth/token",
        )

    def _headers(self) -> dict[str, str]:
        if not self.cfg.access_token:
            return {}
        return {"Authorization": f"Bearer {self.cfg.access_token}"}

    def _refresh_access_token(self) -> bool:
        if not self.cfg.refresh_token or not self.cfg.client_id or not self.cfg.client_secret:
            return False
        try:
            resp = requests.post(
                self.cfg.token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.cfg.refresh_token,
                    "client_id": self.cfg.client_id,
                    "client_secret": self.cfg.client_secret,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            self.cfg.access_token = data.get("access_token", self.cfg.access_token)
            self.cfg.refresh_token = data.get("refresh_token", self.cfg.refresh_token)
            return True
        except Exception:
            return False

    def _api_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        url = f"{self.cfg.api_url}{path}"
        for _ in range(2):
            r = requests.get(url, headers=self._headers(), params=params, timeout=20)
            if r.status_code == 401 and self._refresh_access_token():
                continue
            if r.status_code == 200:
                return r.json()
            return None
        return None

    def fetch_products(self) -> pd.DataFrame:
        if not self.cfg.access_token:
            return pd.DataFrame()

        me = self._api_get("/users/me")
        if not me:
            return pd.DataFrame()

        user_id = me.get("id")
        if not user_id:
            return pd.DataFrame()

        items = self._api_get(f"/users/{user_id}/items/search", {"status": "active", "limit": 50})
        if not items or not items.get("results"):
            return pd.DataFrame()

        rows = []
        for item_id in items["results"]:
            detail = self._api_get(f"/items/{item_id}")
            if not detail:
                continue
            title = detail.get("title")
            price = detail.get("price")
            available = detail.get("available_quantity")
            category_id = detail.get("category_id")
            permalink = detail.get("permalink")
            rows.append(
                {
                    "id": str(item_id),
                    "title": title,
                    "price": price,
                    "stock": available,
                    "category": category_id,
                    "marketplace": self.name,
                    "url": permalink,
                    "orders": None,
                    "commission_pct": None,
                    "collected_at": None,
                }
            )
        return pd.DataFrame(rows)

    def fetch_sales(self) -> pd.DataFrame:
        return pd.DataFrame()

    def search_competitor(self, query: str) -> list[dict]:
        data = self._api_get("/sites/MLB/search", {"q": query, "limit": 10})
        if not data or not data.get("results"):
            return []
        results = []
        for item in data["results"]:
            results.append(
                {
                    "platform": self.name,
                    "query": query,
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "price": item.get("price"),
                    "seller_id": item.get("seller", {}).get("id"),
                    "permalink": item.get("permalink"),
                }
            )
        return results

    def build_authorization_url(self, state: str) -> str:
        base = self.cfg.auth_url
        return (
            f"{base}?response_type=code&client_id={self.cfg.client_id}"
            f"&redirect_uri={self.cfg.redirect_uri}&state={state}"
        )

    def exchange_code_for_token(self, code: str) -> dict[str, Any] | None:
        try:
            resp = requests.post(
                self.cfg.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.cfg.client_id,
                    "client_secret": self.cfg.client_secret,
                    "redirect_uri": self.cfg.redirect_uri,
                },
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None
