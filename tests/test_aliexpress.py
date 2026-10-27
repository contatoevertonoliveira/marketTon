"""Adapter do AliExpress (Portals Affiliate API). A rede é simulada.

Travam: assinatura HMAC-SHA256 estável; busca vira produto com várias fotos, comissão e link de afiliado; faltou campo vira None;
falta de credencial é erro de configuração; pedidos separam comissão estimada de confirmada e ignoram cancelados.
"""
from __future__ import annotations

import hashlib
import hmac

import pytest

from integrations.marketplaces import aliexpress as ae


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body, self.text = body, str(body)

    def json(self):
        return self._body


def _adapter():
    return ae.AliExpressAdapter(ae.AliExpressConfig(app_key="k", app_secret="s", tracking_id="trk"))


def _query_body(products, total=2):
    return {"aliexpress_affiliate_product_query_response": {"resp_result": {"resp_code": 200, "result": {
        "total_record_count": total, "products": {"product": products}}}}}


PRODUCT = {
    "product_id": 1005001, "product_title": " Garrafa Térmica 1L ", "product_main_image_url": "https://ae01.alicdn.com/a.jpg",
    "product_small_image_urls": {"string": ["https://ae01.alicdn.com/b.jpg", "https://ae01.alicdn.com/a.jpg", "https://ae01.alicdn.com/c.jpg"]},
    "target_sale_price": "39.90", "target_original_price": "79.80", "discount": "50%", "commission_rate": "7.0%",
    "evaluate_rate": "96.0%", "lastest_volume": "1234", "promotion_link": "https://s.click.aliexpress.com/e/abc",
    "product_detail_url": "https://www.aliexpress.com/item/1005001.html", "first_level_category_id": 66, "shop_id": 77,
}


def test_signature_is_hmac_sha256_over_sorted_pairs_and_ignores_sign():
    params = {"b": "2", "a": "1", "sign": "x"}
    expected = hmac.new(b"sec", b"a1b2", hashlib.sha256).hexdigest().upper()
    assert ae.sign(params, "sec") == expected


def test_not_configured_is_a_configuration_error():
    a = ae.AliExpressAdapter(ae.AliExpressConfig(app_key="k"))
    assert not a.is_configured()
    with pytest.raises(ae.AliExpressNotConfigured):
        a.fetch_products(options=ae.AliExpressAdapterOptions(keywords=["x"]))


def test_search_normalizes_photos_commission_and_affiliate_link(monkeypatch):
    sent = []

    def post(url, data=None, timeout=None):
        sent.append(data)
        return _Resp(_query_body([PRODUCT, dict(PRODUCT, product_id=1005002, target_sale_price="59.90")]))

    monkeypatch.setattr(ae.requests, "post", post)
    batch = _adapter().fetch_products(options=ae.AliExpressAdapterOptions(keywords=["garrafa"], max_items=2, page_size=2))
    assert sent[0]["method"] == "aliexpress.affiliate.product.query" and sent[0]["tracking_id"] == "trk"
    assert sent[0]["sign"] == ae.sign(sent[0], "s")
    p = batch.products[0]
    assert (p.external_id, p.title, p.price, p.original_price, p.affiliate_commission_pct) == ("1005001", "Garrafa Térmica 1L", 39.9, 79.8, 7.0)
    assert p.images == ["https://ae01.alicdn.com/a.jpg", "https://ae01.alicdn.com/b.jpg", "https://ae01.alicdn.com/c.jpg"]
    assert p.affiliate_url.startswith("https://s.click.aliexpress.com") and p.rating == 4.8 and p.sold_quantity == 1234
    assert p.attributes["similar_offers"] == 2


def test_missing_fields_stay_none(monkeypatch):
    monkeypatch.setattr(ae.requests, "post", lambda *a, **k: _Resp(_query_body([{"product_id": 9, "product_title": "Nu"}], 1)))
    p = _adapter().fetch_products(options=ae.AliExpressAdapterOptions(keywords=["x"], max_items=1, page_size=1)).products[0]
    assert (p.price, p.original_price, p.affiliate_commission_pct, p.rating, p.images) == (None, None, None, None, None)


def test_api_error_becomes_a_warning_not_a_crash(monkeypatch):
    monkeypatch.setattr(ae.requests, "post", lambda *a, **k: _Resp({"error_response": {"code": 29, "msg": "Invalid app Key"}}))
    batch = _adapter().fetch_products(options=ae.AliExpressAdapterOptions(keywords=["x"]))
    assert batch.is_empty and "Invalid app Key" in batch.warnings[0]


def test_check_reports_the_total(monkeypatch):
    monkeypatch.setattr(ae.requests, "post", lambda *a, **k: _Resp(_query_body([], 321)))
    assert "321" in _adapter().check()


def test_orders_split_estimated_and_confirmed_and_drop_cancelled(monkeypatch):
    orders = [
        {"order_id": 1, "product_id": 5, "paid_amount": "20.0", "estimated_paid_commission": "1.4", "order_status": "Payment Completed",
         "paid_time": "2026-10-20 10:00:00"},
        {"order_id": 2, "product_id": 6, "paid_amount": "30.0", "estimated_paid_commission": "2.1", "estimated_finished_commission": "2.0",
         "order_status": "Finished", "paid_time": "2026-10-21 10:00:00"},
        {"order_id": 3, "product_id": 7, "paid_amount": "10.0", "estimated_paid_commission": "0.7", "order_status": "Cancelled"},
    ]
    body = {"aliexpress_affiliate_order_list_response": {"resp_result": {"result": {"orders": {"order": orders}}}}}
    monkeypatch.setattr(ae.requests, "post", lambda *a, **k: _Resp(body))
    s = {r.external_order_id.split(":")[0]: r for r in _adapter().fetch_sales()}
    assert (s["1"].commission_estimated, s["1"].commission_confirmed) == (1.4, None)
    assert (s["2"].commission_estimated, s["2"].commission_confirmed) == (None, 2.0)
    assert (s["3"].commission_estimated, s["3"].commission_confirmed) == (None, None)
    assert s["1"].currency == "USD"
