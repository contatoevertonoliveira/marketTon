"""Minimal client for Shopee's Affiliate Open API (GraphQL).

Endpoint and auth scheme per Shopee's public Affiliate Open API docs:
  POST https://open-api.affiliate.shopee.com/graphql
  Authorization: SHA256 Credential=<AppId>, Timestamp=<ts>, Signature=<sig>
  sig = sha256(AppId + Timestamp + Payload + Secret).hexdigest()

Confidence note (see Fase 2 plan): this is the documented public API shape,
but Shopee can change field names over time. If a real AppId/Secret is
configured and this still returns nothing, check the response body via
`search_products(..., debug=True)` — Shopee usually returns a GraphQL
`errors` array explaining what changed.
"""
from __future__ import annotations

import hashlib
import json
import time

import requests

GRAPHQL_URL = "https://open-api.affiliate.shopee.com/graphql"

PRODUCT_OFFER_QUERY = """
query productOfferV2($keyword: String, $limit: Int) {
  productOfferV2(keyword: $keyword, limit: $limit) {
    nodes {
      itemId
      productName
      price
      commissionRate
      offerLink
      imageUrl
      shopName
      ratingStar
      sales
    }
  }
}
"""


def sign(app_id: str, timestamp: int, payload: str, secret: str) -> str:
    base = f"{app_id}{timestamp}{payload}{secret}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _headers(app_id: str, secret: str, payload: str) -> dict:
    timestamp = int(time.time())
    signature = sign(app_id, timestamp, payload, secret)
    return {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}",
    }


def search_products(app_id: str, secret: str, keyword: str, *, limit: int = 20, timeout: int = 20) -> list[dict]:
    """Returns raw `productOfferV2` nodes, or [] if not configured / the call fails.
    Never raises — callers treat an empty list as "no data", per the platform's
    "never fabricate" rule, not as a hard error."""
    if not app_id or not secret:
        return []
    body = {"query": PRODUCT_OFFER_QUERY, "variables": {"keyword": keyword, "limit": limit}}
    payload = json.dumps(body, separators=(",", ":"))
    headers = _headers(app_id, secret, payload)
    try:
        resp = requests.post(GRAPHQL_URL, data=payload, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if data.get("errors"):
            return []
        nodes = (((data.get("data") or {}).get("productOfferV2") or {}).get("nodes")) or []
        return nodes
    except requests.RequestException:
        return []
