"""Google Ads (Planejador de Palavras-chave) e a tela de serviços de dados.

Nenhum teste fala com o Google: `requests.post` é substituído. O que travam:

* segredo nunca volta pela API, e string vazia mantém o valor salvo;
* o teste de conexão devolve o motivo real da falha (ex.: token não aprovado);
* CPC na moeda da conta: BRL vira `cpc_brl` direto, USD só converte com cotação;
* credencial salva depois de um resultado sem volume invalida o cache.
"""
from __future__ import annotations

import time

import pytest

import core.services.keyword_metrics as km
from backend.routers import services
from integrations import google_ads
from integrations.google_ads import GoogleAdsClient, GoogleAdsConfig, GoogleAdsError

VALUES = {
    "developer_token": "dev-token",
    "client_id": "cid",
    "client_secret": "csecret",
    "refresh_token": "rtoken",
    "customer_id": "123-456-7890",
}


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.ok = status < 400
        self.text = str(self._body)

    def json(self):
        return self._body


def _fake_google(monkeypatch, *, search=None, metrics=None, token=None, calls=None):
    """Roteia as chamadas HTTP do cliente para respostas fixas."""

    def post(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        if url == google_ads.TOKEN_URL:
            return token or _Resp(200, {"access_token": "at", "expires_in": 3600})
        if url.endswith("googleAds:search"):
            return search or _Resp(200, {"results": [{"customer": {"currencyCode": "BRL"}}]})
        if url.endswith(":generateKeywordHistoricalMetrics"):
            return metrics or _Resp(200, {"results": []})
        raise AssertionError(url)

    monkeypatch.setattr(google_ads.requests, "post", post)


def test_config_normalizes_ids_and_reports_missing_fields():
    cfg = GoogleAdsConfig.from_values({**VALUES, "login_customer_id": "999-888-7777"})
    assert cfg.customer_id == "1234567890" and cfg.login_customer_id == "9998887777"
    assert cfg.api_version == google_ads.DEFAULT_API_VERSION and cfg.is_complete()

    partial = GoogleAdsConfig.from_values({"client_id": "x"})
    assert not partial.is_complete()
    assert "refresh_token" in partial.missing()
    # O Google desativou o developer token em 9/9/2026: não é mais obrigatório.
    assert "developer_token" not in partial.missing()


def test_check_succeeds_and_reports_account_currency(monkeypatch):
    _fake_google(monkeypatch)
    message = GoogleAdsClient(GoogleAdsConfig.from_values(VALUES)).check()
    assert "1234567890" in message and "BRL" in message


def test_check_surfaces_unapproved_developer_token(monkeypatch):
    body = {
        "error": {
            "message": "The developer token is only approved for use with test accounts.",
            "details": [{"errors": [{"errorCode": {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"}}]}],
        }
    }
    _fake_google(monkeypatch, search=_Resp(403, body))
    with pytest.raises(GoogleAdsError, match="DEVELOPER_TOKEN_NOT_APPROVED"):
        GoogleAdsClient(GoogleAdsConfig.from_values(VALUES)).check()


def test_check_surfaces_oauth_rejection(monkeypatch):
    _fake_google(monkeypatch, token=_Resp(400, {"error": "invalid_grant", "error_description": "Token has been expired"}))
    with pytest.raises(GoogleAdsError, match="invalid_grant"):
        GoogleAdsClient(GoogleAdsConfig.from_values(VALUES)).check()


def test_check_lists_missing_fields_without_calling_google(monkeypatch):
    calls: list = []
    _fake_google(monkeypatch, calls=calls)
    with pytest.raises(GoogleAdsError, match="refresh_token"):
        GoogleAdsClient(GoogleAdsConfig.from_values({**VALUES, "refresh_token": ""})).check()
    assert calls == []


def test_keyword_metrics_parses_volume_cpc_and_competition(monkeypatch):
    calls: list = []
    metrics = _Resp(
        200,
        {
            "results": [
                {
                    "text": "Lanterna Tática",
                    "keywordMetrics": {
                        "avgMonthlySearches": "22200",
                        "competition": "LOW",
                        "competitionIndex": "18",
                        "lowTopOfPageBidMicros": "300000",
                        "highTopOfPageBidMicros": "900000",
                    },
                },
                {"text": "sem dados", "keywordMetrics": {"competition": "UNSPECIFIED"}},
            ]
        },
    )
    _fake_google(monkeypatch, metrics=metrics, calls=calls)

    found, currency = GoogleAdsClient(GoogleAdsConfig.from_values(VALUES)).keyword_metrics(["lanterna tática"])

    assert currency == "BRL"
    assert found["lanterna tática"] == {
        "search_volume": 22200,
        "competition": "LOW",
        "competition_index": 18,
        "cpc": 0.6,  # média de 0,30 e 0,90
        "currency": "BRL",
    }
    # Campo ausente vira None, não zero.
    assert found["sem dados"]["search_volume"] is None and found["sem dados"]["competition"] is None
    sent = next(kw for url, kw in calls if url.endswith(":generateKeywordHistoricalMetrics"))
    assert sent["headers"]["developer-token"] == "dev-token"
    assert sent["json"]["geoTargetConstants"] == [google_ads.BRAZIL_GEO]
    assert "login-customer-id" not in sent["headers"]


def test_works_without_developer_token_and_omits_the_header(monkeypatch):
    calls: list = []
    _fake_google(monkeypatch, calls=calls)
    values = {k: v for k, v in VALUES.items() if k != "developer_token"}
    assert GoogleAdsConfig.from_values(values).is_complete()
    GoogleAdsClient(GoogleAdsConfig.from_values(values)).check()
    search = next(kw for url, kw in calls if url.endswith("googleAds:search"))
    assert "developer-token" not in search["headers"]


def test_surfaces_cloud_project_not_approved(monkeypatch):
    body = {
        "error": {
            "message": "The Cloud project is not approved for production use.",
            "details": [{"errors": [{"errorCode": {"authorizationError": "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"}}]}],
        }
    }
    _fake_google(monkeypatch, search=_Resp(403, body))
    with pytest.raises(GoogleAdsError, match="CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"):
        GoogleAdsClient(GoogleAdsConfig.from_values(VALUES)).check()


def test_manager_account_id_is_sent_as_login_customer(monkeypatch):
    calls: list = []
    _fake_google(monkeypatch, calls=calls)
    GoogleAdsClient(GoogleAdsConfig.from_values({**VALUES, "login_customer_id": "999-888-7777"})).check()
    search = next(kw for url, kw in calls if url.endswith("googleAds:search"))
    assert search["headers"]["login-customer-id"] == "9998887777"


# --- tela de serviços ----------------------------------------------------------


def test_secrets_are_never_returned_and_blank_keeps_saved_value(session):
    out = services.update_service("google_ads", services.ServiceUpdate(values=VALUES), session)
    assert out.configured is True
    assert out.values_set["developer_token"] is True
    assert "dev-token" not in out.model_dump_json()

    again = services.update_service(
        "google_ads", services.ServiceUpdate(values={"developer_token": "", "client_id": "novo"}), session
    )
    assert again.configured is True  # o token em branco manteve o anterior
    saved = services._row(session, "google_ads")
    assert saved.values["developer_token"] == "dev-token" and saved.values["client_id"] == "novo"


def test_changing_a_credential_clears_the_previous_test_result(session, monkeypatch):
    _fake_google(monkeypatch)
    services.update_service("google_ads", services.ServiceUpdate(values=VALUES), session)
    assert services.test_service("google_ads", session).last_check_status == "ok"

    out = services.update_service("google_ads", services.ServiceUpdate(values={"client_secret": "outro"}), session)
    assert out.last_check_status is None


def test_service_test_records_failure_reason(session, monkeypatch):
    _fake_google(monkeypatch, token=_Resp(400, {"error": "invalid_client", "error_description": "Unauthorized"}))
    services.update_service("google_ads", services.ServiceUpdate(values=VALUES), session)
    out = services.test_service("google_ads", session)
    assert out.last_check_status == "error" and "invalid_client" in out.last_check_message


def test_unknown_service_is_404(session):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        services.update_service("nao_existe", services.ServiceUpdate(), session)
    assert exc.value.status_code == 404


# --- métricas de palavra-chave -------------------------------------------------


@pytest.fixture
def no_trends(monkeypatch):
    km._cache.clear()
    monkeypatch.setattr(km, "_trend_summary", lambda keyword, geo: {"growth_pct_30d": 10.0, "trend_direction": "rising"})
    monkeypatch.setattr(km, "planner_provider", lambda: None)
    yield
    km._cache.clear()


def test_brl_account_cpc_is_used_as_is(no_trends, monkeypatch):
    monkeypatch.setattr(
        km,
        "_planner_metrics",
        lambda kws: ({"lanterna": {"search_volume": 100, "competition": "LOW", "cpc": 0.6, "currency": "BRL"}}, "google_ads", None),
    )
    (m,) = km.analyze_keywords(["lanterna"])
    assert (m.cpc_brl, m.cpc_usd, m.planner_source, m.monthly_volume) == (0.6, None, "google_ads", 100)


def test_usd_cpc_only_converts_with_a_configured_rate(no_trends, monkeypatch):
    monkeypatch.setattr(
        km,
        "_planner_metrics",
        lambda kws: ({"a": {"cpc": 1.0, "currency": "USD"}, "b": {"cpc": 2.0, "currency": "EUR"}}, "dataforseo", None),
    )
    monkeypatch.setattr(km, "get_settings", lambda: type("S", (), {"usd_brl_rate": None})())
    a, b = km.analyze_keywords(["a", "b"])
    assert (a.cpc_usd, a.cpc_brl) == (1.0, None)  # sem cotação, não inventa R$
    assert (b.cpc_usd, b.cpc_brl) == (None, None) and b.notes  # moeda desconhecida: avisa


def test_provider_failure_is_reported_not_swallowed(no_trends, monkeypatch):
    monkeypatch.setattr(km, "_planner_metrics", lambda kws: ({}, None, "Google Ads: DEVELOPER_TOKEN_NOT_APPROVED"))
    (m,) = km.analyze_keywords(["lanterna"])
    assert m.planner_error == "Google Ads: DEVELOPER_TOKEN_NOT_APPROVED" and m.monthly_volume is None


def test_cached_result_without_volume_is_refreshed_once_a_provider_exists(no_trends, monkeypatch):
    monkeypatch.setattr(
        km,
        "_planner_metrics",
        lambda kws: ({"lanterna": {"search_volume": 5, "cpc": 1.0, "currency": "BRL"}}, "google_ads", None),
    )
    # Resultado recente, guardado quando ainda não havia provedor.
    km._cache[("lanterna", "BR")] = (time.time(), km.KeywordMetrics(keyword="lanterna"))
    monkeypatch.setattr(km, "planner_provider", lambda: "google_ads")
    (second,) = km.analyze_keywords(["lanterna"])
    assert second.monthly_volume == 5
