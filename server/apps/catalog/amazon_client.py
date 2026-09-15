"""Minimal client for Amazon's Product Advertising API 5.0 (SearchItems),
signed with AWS Signature Version 4.

SigV4 is a stable, well-documented AWS protocol (implemented here with high
confidence). What is NOT guaranteed: PA-API only grants access once the
Associates account has 3 qualifying sales in the last 180 days — with
correct keys but no qualifying sales, Amazon still rejects every call. That
is an account-eligibility requirement on Amazon's side, not something this
client can work around.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json

import requests

SERVICE = "ProductAdvertisingAPI"
TARGET = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
CANONICAL_URI = "/paapi5/searchitems"


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
    k_date = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, SERVICE)
    return _hmac(k_service, "aws4_request")


def search_items(
    *,
    access_key: str,
    secret_key: str,
    associate_tag: str,
    region: str,
    host: str,
    keywords: str,
    item_count: int = 10,
    timeout: int = 20,
) -> list[dict]:
    """Returns raw `SearchResult.Items` entries, or [] if not configured / the
    call fails or is rejected (e.g. account not yet eligible). Never raises."""
    if not access_key or not secret_key or not associate_tag or not host:
        return []

    payload_dict = {
        "Keywords": keywords,
        "Resources": [
            "Images.Primary.Medium",
            "ItemInfo.Title",
            "Offers.Listings.Price",
            "CustomerReviews.StarRating",
            "CustomerReviews.Count",
        ],
        "PartnerTag": associate_tag,
        "PartnerType": "Associates",
        "ItemCount": item_count,
    }
    payload = json.dumps(payload_dict)

    amz_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date_stamp = amz_date[:8]
    content_type = "application/json; charset=utf-8"
    content_encoding = "amz-1.0"

    canonical_headers = (
        f"content-encoding:{content_encoding}\n"
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-target:{TARGET}\n"
    )
    signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "\n".join([
        "POST", CANONICAL_URI, "", canonical_headers, signed_headers, payload_hash,
    ])

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signature = hmac.new(
        _signing_key(secret_key, date_stamp, region), string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "content-encoding": content_encoding,
        "content-type": content_type,
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-target": TARGET,
        "Authorization": authorization,
    }

    url = f"https://{host}{CANONICAL_URI}"
    try:
        resp = requests.post(url, data=payload, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return ((data.get("SearchResult") or {}).get("Items")) or []
    except requests.RequestException:
        return []


def build_affiliate_url(asin: str, associate_tag: str, marketplace_domain: str) -> str:
    """Amazon's own documented affiliate link format — deterministic
    construction, not fetched/fabricated data."""
    domain = marketplace_domain or "www.amazon.com"
    return f"https://{domain}/dp/{asin}?tag={associate_tag}"
