"""Rótulo de venda por anúncio na Shopee: o sub-ID do link volta no relatório de conversões e o anúncio direto o usa.

O que os testes travam:

* `short_link` monta a mutation com os sub-IDs limpos (sem hífen, no máximo 5) e só aceita https;
* o rótulo (`utmContent`, sub-IDs separados por "-") vira o canal da venda; vazio ("----") fica sem canal;
* o anúncio direto usa o link com rótulo (`ad<id>`) como destino do link rastreado e, se o rótulo falhar, cai no link genérico.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from integrations.marketplaces.shopee import ShopeeAdapter, ShopeeConfig, ShopeeError


def _adapter(monkeypatch, answer):
    ad = ShopeeAdapter(cfg=ShopeeConfig(app_id="a", secret="s"))
    sent = []
    monkeypatch.setattr(ad, "_graphql", lambda query, variables: sent.append(query) or answer)
    return ad, sent


def test_short_link_sends_clean_sub_ids_and_returns_the_short_link(monkeypatch):
    ad, sent = _adapter(monkeypatch, {"generateShortLink": {"shortLink": "https://s.shopee.com.br/abc"}})
    assert ad.short_link("https://shopee.com.br/product/1/2", ["ad-16", "x y"]) == "https://s.shopee.com.br/abc"
    assert 'originUrl: "https://shopee.com.br/product/1/2"' in sent[0] and 'subIds: ["ad16", "xy"]' in sent[0]
    with pytest.raises(ShopeeError, match="https"):
        ad.short_link("http://shopee.com.br/x")
    ad2, _ = _adapter(monkeypatch, {"generateShortLink": {"shortLink": ""}})
    with pytest.raises(ShopeeError, match="não devolveu"):
        ad2.short_link("https://shopee.com.br/product/1/2")


def test_conversion_label_becomes_the_sale_channel():
    node = {"conversionStatus": "PENDING", "purchaseTime": 1793564539, "utmContent": "ad16----",
            "orders": [{"orderId": "O1", "items": [{"itemId": 9, "itemName": "Lanterna", "qty": 1, "actualAmount": "46.00", "itemTotalCommission": "2.76"}]}]}
    [rec] = ShopeeAdapter._sales_from_conversion(node)
    assert rec.channel == "ad16" and rec.commission_estimated == 2.76
    node["utmContent"] = "----"
    assert ShopeeAdapter._sales_from_conversion(node)[0].channel is None
    node.pop("utmContent")
    assert ShopeeAdapter._sales_from_conversion(node)[0].channel is None
