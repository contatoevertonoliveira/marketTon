"""Hotmart, Monetizze e Eduzz: autenticação, vendas e comissão (HTTP simulado).

As respostas simuladas seguem os exemplos da **documentação oficial** de cada plataforma.
O que os testes travam:

* o fluxo de autenticação exato de cada uma (endpoint, método, cabeçalhos, corpo);
* o token fica em cache e só é refeito quando a API devolve 401/403;
* o status da venda vira comissão **confirmada** x **estimada** x nenhuma (cancelada);
* dado ambíguo ou ausente vira `None`, nunca um número inventado.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.db.base import Marketplace
from core.services.sales_ingestion import ingest_sales
from integrations.marketplaces import digital_platforms as dp
from integrations.marketplaces.digital_platforms import (
    EduzzAdapter, EduzzConfig, HotmartAdapter, HotmartConfig, MonetizzeAdapter, MonetizzeConfig,
    PlatformError, PlatformNotConfigured,
)

SINCE = datetime(2026, 10, 1, tzinfo=UTC)


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else {}
        self.ok = status < 400
        self.text = str(self._body)

    def json(self):
        return self._body


class _Http:
    """Roteia `requests.get/post` para respostas fixas e guarda as chamadas."""

    def __init__(self, monkeypatch, routes):
        self.calls, self.routes = [], routes
        monkeypatch.setattr(dp.requests, "get", lambda url, **kw: self._handle("GET", url, kw))
        monkeypatch.setattr(dp.requests, "post", lambda url, **kw: self._handle("POST", url, kw))

    def _handle(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        for (m, fragment), response in self.routes.items():
            if m == method and fragment in url:
                result = response(kwargs) if callable(response) else response
                return result
        raise AssertionError(f"chamada inesperada: {method} {url}")

    def count(self, method, fragment):
        return sum(1 for m, u, _ in self.calls if m == method and fragment in u)


# =================================================================== Hotmart ==========

HOTMART_TOKEN = _Resp(200, {"access_token": "tok-1", "token_type": "bearer", "expires_in": 172799, "scope": "read write"})


def _hotmart(**kw):
    return HotmartAdapter(HotmartConfig(client_id="cid", client_secret="csec", basic_token="basic123", **kw))


def _hotmart_item(tx, status, value=100.0, product=("2125812", "Curso X"), approved=1622948400000):
    return {
        "product": {"id": int(product[0]), "name": product[1]},
        "purchase": {"transaction": tx, "approved_date": approved, "status": status, "commission_as": "AFFILIATE",
                     "price": {"value": value, "currency_code": "BRL"}},
    }


def test_hotmart_requires_all_three_credentials():
    assert not HotmartAdapter(HotmartConfig(client_id="a", client_secret="b")).is_configured()
    with pytest.raises(PlatformNotConfigured):
        HotmartAdapter(HotmartConfig()).check()


def test_hotmart_token_request_follows_the_official_flow_and_is_cached(monkeypatch):
    http = _Http(monkeypatch, {("POST", "security/oauth/token"): HOTMART_TOKEN})
    adapter = _hotmart()
    assert "produção" in adapter.check()

    method, url, kw = http.calls[0]
    assert url == "https://api-sec-vlc.hotmart.com/security/oauth/token"
    assert kw["params"] == {"grant_type": "client_credentials", "client_id": "cid", "client_secret": "csec"}
    assert kw["headers"]["Authorization"] == "Basic basic123"

    adapter._access_token()
    adapter._access_token()
    assert http.count("POST", "oauth/token") == 1  # o token vale 48 h: não se refaz a cada chamada


def test_hotmart_accepts_the_basic_token_pasted_with_its_prefix_and_uses_sandbox_on_request(monkeypatch):
    http = _Http(monkeypatch, {("POST", "oauth/token"): HOTMART_TOKEN, ("GET", "/payments/api/v1/sales/history"): _Resp(200, {"items": []}),
                               ("GET", "/payments/api/v1/sales/commissions"): _Resp(200, {"items": []})})
    adapter = HotmartAdapter(HotmartConfig(client_id="c", client_secret="s", basic_token="Basic abc", sandbox="sim"))
    adapter.fetch_sales(since=SINCE)
    assert http.calls[0][2]["headers"]["Authorization"] == "Basic abc"  # sem "Basic Basic"
    assert all(u.startswith("https://sandbox.hotmart.com") for m, u, _ in http.calls if m == "GET")
    assert "sandbox" in adapter.check()


def test_hotmart_sales_map_status_to_confirmed_estimated_or_cancelled(monkeypatch):
    def history(kw):
        status = kw["params"].get("transaction_status")
        if status == "CANCELLED":
            return _Resp(200, {"items": [_hotmart_item("HP-C", "CANCELLED", 80.0)]})
        if status:
            return _Resp(200, {"items": []})
        return _Resp(200, {"items": [_hotmart_item("HP-A", "APPROVED", 200.0), _hotmart_item("HP-B", "COMPLETE", 100.0, ("999", "Curso Y"))]})

    commissions = _Resp(200, {"items": [
        {"transaction": "HP-A", "commissions": [{"commission": {"currency_value": "BRL", "value": 100.0}, "source": "PRODUCER"},
                                                {"commission": {"currency_value": "BRL", "value": 60.0}, "source": "AFFILIATE"}]},
        {"transaction": "HP-B", "commissions": [{"commission": {"currency_value": "BRL", "value": 30.0}, "source": "AFFILIATE"}]},
    ]})
    http = _Http(monkeypatch, {("POST", "oauth/token"): HOTMART_TOKEN, ("GET", "sales/history"): history, ("GET", "sales/commissions"): commissions})

    records = {r.external_order_id: r for r in _hotmart().fetch_sales(since=SINCE)}

    a, b, c = records["HP-A"], records["HP-B"], records["HP-C"]
    assert (a.commission_estimated, a.commission_confirmed, a.status) == (60.0, None, "APPROVED")  # paga, ainda na garantia
    assert (b.commission_confirmed, b.commission_estimated) == (30.0, None)  # garantia encerrada
    assert (c.status, c.commission_estimated, c.commission_confirmed, c.commission_rate_basis_points) == ("CANCELLED", None, None, None)
    assert a.commission_rate_basis_points == 3000 and a.gross_amount == 200.0 and a.currency == "BRL"
    assert (a.product_external_id, a.product_title) == ("2125812", "Curso X")
    # Só vendas como afiliado, com janela em milissegundos (doc oficial).
    first = next(kw for m, u, kw in http.calls if "sales/history" in u)
    assert first["params"]["commission_as"] == "AFFILIATE" and first["params"]["start_date"] == int(SINCE.timestamp() * 1000)


def test_hotmart_follows_pagination_tokens(monkeypatch):
    pages = {None: {"items": [_hotmart_item("P1", "COMPLETE")], "page_info": {"next_page_token": "abc"}},
             "abc": {"items": [_hotmart_item("P2", "COMPLETE")], "page_info": {}}}
    _Http(monkeypatch, {("POST", "oauth/token"): HOTMART_TOKEN,
                        ("GET", "sales/history"): lambda kw: _Resp(200, pages[kw["params"].get("page_token")] if not kw["params"].get("transaction_status") else {"items": []}),
                        ("GET", "sales/commissions"): _Resp(200, {"items": []})})
    assert {r.external_order_id for r in _hotmart().fetch_sales(since=SINCE)} == {"P1", "P2"}


def test_hotmart_refreshes_the_token_once_on_401_and_reports_rate_limit(monkeypatch):
    state = {"n": 0}

    def data(kw):
        state["n"] += 1
        return _Resp(401, {"error": "expired"}) if state["n"] == 1 else _Resp(200, {"items": []})

    http = _Http(monkeypatch, {("POST", "oauth/token"): HOTMART_TOKEN, ("GET", "sales/"): data})
    _hotmart().fetch_sales(since=SINCE)
    assert http.count("POST", "oauth/token") == 2  # o de antes e o refeito depois do 401

    _Http(monkeypatch, {("POST", "oauth/token"): HOTMART_TOKEN, ("GET", "sales/"): _Resp(429, {})})
    with pytest.raises(PlatformError, match="limite de requisições"):
        _hotmart().fetch_sales(since=SINCE)


def test_hotmart_rejected_credentials_surface_the_reason(monkeypatch):
    _Http(monkeypatch, {("POST", "oauth/token"): _Resp(401, {"error_description": "Bad credentials"})})
    with pytest.raises(PlatformError, match="recusou as credenciais.*Bad credentials"):
        _hotmart().check()


def test_hotmart_has_no_public_catalog_and_says_so(monkeypatch):
    batch = _hotmart().fetch_products()
    assert batch.products == [] and "pelas vendas" in batch.warnings[0]


# ================================================================== Monetizze =========

MONETIZZE_TOKEN = _Resp(200, {"TOKEN": "mtok", "expire": "2026-10-22 12:39:24"})
MONETIZZE_PRODUCTS = _Resp(200, {"status": 200, "totalRegistros": 2, "dados": [
    {"codigo": "34348", "sku": "CURSO-PHP-01", "chave": "k", "status": "2", "nome": "Curso básico de php",
     "foto": "https://static.monetizze.com.br/img/fotos/34348/x.png",
     "planos": [{"codigo": "265839", "nome": "Plano Mensal", "status": "1", "valor": "99.00"},
                {"codigo": "1", "nome": "Plano Antigo", "status": "0", "valor": "79.00"},
                {"codigo": "2", "nome": "Plano Anual", "status": "1", "valor": "890.00"}]},
    {"codigo": "34336", "status": "3", "nome": "Curso On-line", "planos": []},
]})


def _monetizze():
    return MonetizzeAdapter(MonetizzeConfig(consumer_key="ckey"))


def test_monetizze_token_comes_from_the_consumer_key_header(monkeypatch):
    http = _Http(monkeypatch, {("GET", "/2.1/token"): MONETIZZE_TOKEN})
    assert "15 min" in _monetizze().check()
    method, url, kw = http.calls[0]
    assert url == "https://api.monetizze.com.br/2.1/token" and kw["headers"] == {"X_CONSUMER_KEY": "ckey"}
    with pytest.raises(PlatformNotConfigured):
        MonetizzeAdapter(MonetizzeConfig()).check()


def test_monetizze_products_use_the_active_plan_price_and_never_invent_commission(monkeypatch):
    http = _Http(monkeypatch, {("GET", "/2.1/token"): MONETIZZE_TOKEN, ("GET", "/2.1/myproducts"): MONETIZZE_PRODUCTS})
    batch = _monetizze().fetch_products()
    first, second = batch.products
    assert (first.external_id, first.title, first.price, first.is_available) == ("34348", "Curso básico de php", 99.0, True)  # plano inativo (79) fora
    assert first.images == ["https://static.monetizze.com.br/img/fotos/34348/x.png"]
    assert first.affiliate_commission_pct is None and second.price is None and second.is_available is False
    assert http.calls[1][2]["headers"] == {"TOKEN": "mtok"} and http.calls[1][2]["params"] == {"retorno_produtor": 0}


def _monetizze_row(code, status, value=100.0, comissoes=None):
    return {"produto": {"codigo": "12832", "nome": "Curso Teste"},
            "venda": {"codigo": code, "status": status, "valor": value, "quantidade": 1, "moeda": "BRL", "dataInicio": "2026-10-03 13:12:05"},
            "comissoes": comissoes if comissoes is not None else [{"refAfiliado": "ABC", "nome": "Eu", "valor": 25.0, "porcentagem": 25.0}]}


def test_monetizze_sales_status_decides_confirmed_estimated_or_none(monkeypatch):
    rows = [_monetizze_row("1", "Completa"), _monetizze_row("2", "Finalizada"), _monetizze_row("3", "Aguardando pagamento"),
            _monetizze_row("4", "Cancelada"), _monetizze_row("5", "Devolvida")]
    _Http(monkeypatch, {("GET", "/2.1/token"): MONETIZZE_TOKEN, ("GET", "/2.1/transactions"): _Resp(200, [{"status": 200, "dados": rows}])})
    r = {x.external_order_id: x for x in _monetizze().fetch_sales(since=SINCE)}

    assert (r["1"].commission_confirmed, r["1"].commission_estimated) == (25.0, None)
    assert (r["2"].commission_estimated, r["2"].commission_confirmed) == (25.0, None)
    assert (r["3"].commission_estimated, r["3"].commission_confirmed) == (None, None)  # ainda não pagou
    assert (r["4"].status, r["5"].status) == ("CANCELLED", "CANCELLED") and r["4"].commission_estimated is None
    assert r["1"].commission_rate_basis_points == 2500
    assert (r["1"].product_external_id, r["1"].product_title, r["1"].gross_amount) == ("12832", "Curso Teste", 100.0)


def test_monetizze_ambiguous_commission_entries_are_not_guessed(monkeypatch):
    two = [{"nome": "Produtor", "valor": 70.0, "porcentagem": 70.0}, {"nome": "Co", "valor": 5.0, "porcentagem": 5.0}]
    _Http(monkeypatch, {("GET", "/2.1/token"): MONETIZZE_TOKEN,
                        ("GET", "/2.1/transactions"): _Resp(200, [{"status": 200, "dados": [_monetizze_row("9", "Completa", comissoes=two)]}])})
    (record,) = _monetizze().fetch_sales(since=SINCE)
    assert record.commission_confirmed is None and record.commission_estimated is None  # sem saber qual é a sua, não chuta


def test_monetizze_regenerates_the_token_once_when_the_api_says_403(monkeypatch):
    state = {"n": 0}

    def products(kw):
        state["n"] += 1
        return _Resp(403, {"Error": "Token inválido"}) if state["n"] == 1 else MONETIZZE_PRODUCTS

    http = _Http(monkeypatch, {("GET", "/2.1/token"): MONETIZZE_TOKEN, ("GET", "/2.1/myproducts"): products})
    assert len(_monetizze().fetch_products().products) == 2
    assert http.count("GET", "/2.1/token") == 2


def test_monetizze_invalid_consumer_key(monkeypatch):
    _Http(monkeypatch, {("GET", "/2.1/token"): _Resp(403, {"status": 403, "Error": "Credenciais de API não fornecidas"})})
    with pytest.raises(PlatformError, match="recusou a chave"):
        _monetizze().check()


# ==================================================================== Eduzz ===========

EDUZZ_TOKEN = _Resp(200, {"access_token": "etok", "token_type": "bearer", "scope": "me", "user": {"id": "1"}})


def _eduzz():
    return EduzzAdapter(EduzzConfig(client_id="cid", client_secret="csec"))


def _eduzz_item(sale_id, status, total=100.0, gain=40.0):
    return {"id": sale_id, "status": status, "currency": "BRL", "total": {"currency": "BRL", "value": total},
            "netGain": {"currency": "BRL", "value": gain}, "paidAt": "2026-10-03T13:12:05Z", "createdAt": "2026-10-03T13:00:00Z",
            "product": {"id": "55", "name": "Mentoria Z"}, "affiliate": {"id": "9", "name": "Eu"}}


def test_eduzz_token_flow_and_connection_check(monkeypatch):
    http = _Http(monkeypatch, {("POST", "accounts-api.eduzz.com/oauth/token"): EDUZZ_TOKEN,
                               ("GET", "/accounts/v1/me"): _Resp(200, {"data": {"name": "Everton", "email": "e@x.com"}})})
    assert _eduzz().check() == "conectado como Everton"
    method, url, kw = http.calls[0]
    assert url == "https://accounts-api.eduzz.com/oauth/token"
    assert kw["json"] == {"grant_type": "client_credentials", "client_id": "cid", "client_secret": "csec"}
    me = http.calls[1]
    assert me[1] == "https://api.eduzz.com/accounts/v1/me" and me[2]["headers"]["authorization"] == "bearer etok"
    with pytest.raises(PlatformNotConfigured):
        EduzzAdapter(EduzzConfig(client_id="x")).check()


def test_eduzz_sales_map_status_and_use_net_gain_as_the_affiliate_commission(monkeypatch):
    pages = {1: {"pages": 2, "items": [_eduzz_item(1, "paid"), _eduzz_item(2, "waiting_payment", gain=10.0)]},
             2: {"pages": 2, "items": [_eduzz_item(3, "refunded"), _eduzz_item(4, "paid", total=0, gain=5.0)]}}
    http = _Http(monkeypatch, {("POST", "oauth/token"): EDUZZ_TOKEN,
                               ("GET", "/myeduzz/v1/sales"): lambda kw: _Resp(200, pages[kw["params"]["page"]])})
    r = {x.external_order_id: x for x in _eduzz().fetch_sales(since=SINCE)}

    assert (r["1"].commission_confirmed, r["1"].commission_estimated, r["1"].commission_rate_basis_points) == (40.0, None, 4000)
    assert (r["2"].commission_estimated, r["2"].commission_confirmed) == (10.0, None)
    assert (r["3"].status, r["3"].commission_estimated, r["3"].commission_confirmed) == ("CANCELLED", None, None)
    assert r["4"].commission_rate_basis_points is None  # total 0: não há taxa a calcular
    assert (r["1"].product_external_id, r["1"].product_title, r["1"].gross_amount) == ("55", "Mentoria Z", 100.0)
    first = http.calls[1][2]["params"]
    assert first["itemsPerPage"] == 100 and first["startDate"] == "2026-10-01"
    assert http.count("GET", "/myeduzz/v1/sales") == 2  # seguiu as 2 páginas


def test_eduzz_regenerates_the_token_only_once_on_401(monkeypatch):
    state = {"n": 0}

    def sales(kw):
        state["n"] += 1
        return _Resp(401, {}) if state["n"] == 1 else _Resp(200, {"pages": 1, "items": []})

    http = _Http(monkeypatch, {("POST", "oauth/token"): EDUZZ_TOKEN, ("GET", "/myeduzz/v1/sales"): sales})
    assert _eduzz().fetch_sales(since=SINCE) == []
    assert http.count("POST", "oauth/token") == 2


# ============================================ integração com o resto do sistema =======


def test_digital_platform_sales_flow_into_the_performance_page_without_a_catalog(session, monkeypatch):
    from core.services.product_performance import product_performance

    _Http(monkeypatch, {("POST", "oauth/token"): HOTMART_TOKEN,
                        ("GET", "sales/history"): lambda kw: _Resp(200, {"items": [_hotmart_item("HP-1", "COMPLETE", 200.0)] if not kw["params"].get("transaction_status") else []}),
                        ("GET", "sales/commissions"): _Resp(200, {"items": [{"transaction": "HP-1", "commissions": [
                            {"commission": {"value": 80.0}, "source": "AFFILIATE"}]}]})})
    ingest_sales(session, _hotmart().fetch_sales(since=SINCE), Marketplace.HOTMART)

    rows, _ = product_performance(session, Marketplace.HOTMART)
    (row,) = rows
    assert (row.marketplace, row.title, row.units, row.revenue, row.commission_confirmed) == ("hotmart", "Curso X", 1, 200.0, 80.0)


def test_the_three_platforms_are_registered_with_credential_schemas_and_a_working_check():
    from backend.routers.marketplaces import CREDENTIAL_FIELDS, _test_connection
    from integrations.marketplaces.registry import list_adapter_names, load_adapters

    load_adapters()
    for slug in ("hotmart", "monetizze", "eduzz"):
        assert slug in list_adapter_names() and slug in CREDENTIAL_FIELDS
    assert {f["name"] for f in CREDENTIAL_FIELDS["hotmart"]} == {"client_id", "client_secret", "basic_token", "sandbox"}
    assert [f["name"] for f in CREDENTIAL_FIELDS["monetizze"]] == ["consumer_key"]
    assert {f["name"] for f in CREDENTIAL_FIELDS["eduzz"]} == {"client_id", "client_secret"}
    # Todo campo do formulário existe no config do adapter (é por ali que a credencial salva é aplicada).
    for slug in ("hotmart", "monetizze", "eduzz"):
        from integrations.marketplaces.registry import resolve

        cfg = resolve(slug).cfg
        assert all(hasattr(cfg, f["name"]) for f in CREDENTIAL_FIELDS[slug]), slug

    class Fake:
        def is_configured(self):
            return True

        def check(self):
            return "token obtido"

    assert _test_connection(Fake(), "monetizze") == ("ok", "token obtido")
