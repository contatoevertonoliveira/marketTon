"""Testes da API (briefing seções 5, 6, 7, 8, 9, 13 e 15).

Usa `TestClient` sobre SQLite em memória, com a dependência de sessão sobrescrita.
Nenhum PostgreSQL, nenhum Docker.

O que estes testes protegem:

1. **A explicabilidade chega ao cliente.** `/scoring/targets/...` devolve a lista
   `+ motivo` / `- motivo` e a auditoria completa. É a resposta a "por que este
   produto foi recomendado?".
2. **O estado é decidido no backend.** Transição inválida devolve 409 com a lista
   do que *é* permitido. O cliente não replica a máquina de estados.
3. **O portão de publicação vale por HTTP.** Publicar sem material aprovado é
   recusado com a lista do que falta.
4. **Ausência não vira zero no JSON.** Campo não coletado sai `null`, nunca `0`.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.db  # noqa: F401 - o pacote carrega todos os modelos em Base.metadata
import core.db.support  # noqa: F401 - garante as tabelas de suporte
from core.db import Base
from core.db.auth import Role
from core.db.base import ConnectorKind, CreativeAssetType, CreativeStatus, Marketplace, PortfolioState
from core.db.catalog import Product, ProductMetric, Seller, SourceRecord
from core.db.creative import CreativeAsset
from core.db.support import SupportFeedback
from core.services.auth import create_user

NOW = datetime(2026, 3, 20, 10, 0, tzinfo=UTC)
ADMIN_PASSWORD = "SenhaDeTeste2026"


@pytest.fixture
def engine():
    """Banco em memória compartilhado entre todas as conexões.

    Ponto que não é óbvio: `sqlite:///:memory:` cria um banco **novo por conexão**.
    Sem `StaticPool`, o `create_all` roda numa conexão e cada request do
    `TestClient` abre outra — que não tem tabela nenhuma. O sintoma é
    "no such table: jobs" com o schema aparentemente criado.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(factory, monkeypatch):
    """TestClient autenticado como administrador.

    O cliente faz login de verdade e injeta o token em cada requisição. Isso é
    deliberado: um cliente anônimo só funcionaria com `AUTH_ENABLED=false`, e
    depender dessa variável tornaria estes testes sensíveis à ordem de execução —
    `test_api_auth.py` liga auth no import e o ambiente vaza entre módulos.

    Autenticar de verdade também significa que estes testes exercitam o caminho
    real de produção, e não um atalho.
    """
    from backend import deps
    from backend.main import app

    def override_session():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_session] = override_session
    # O lifespan tentaria conectar em PostgreSQL; desligamos para o teste.
    app.router.lifespan_context = _noop_lifespan

    with TestClient(app) as test_client:
        setup = factory()
        try:
            create_user(setup, username="admin_test", password=ADMIN_PASSWORD, role=Role.ADMIN)
            setup.commit()
        finally:
            setup.close()

        response = test_client.post(
            "/auth/login", json={"username": "admin_test", "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200, response.text
        test_client.headers.update(
            {"Authorization": f"Bearer {response.json()['access_token']}"}
        )
        yield test_client

    app.dependency_overrides.clear()


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _noop_lifespan(app):  # noqa: ANN001, ARG001
    yield


@pytest.fixture
def seeded(factory):
    """Catálogo mínimo com procedência, vendedor, métricas e histórico."""
    session = factory()

    source = SourceRecord(
        marketplace=Marketplace.MERCADO_LIVRE,
        connector="mercado_livre",
        connector_kind=ConnectorKind.OFFICIAL_API,
        endpoint="https://api.mercadolibre.com/items/MLB1",
        external_id="MLB1",
        collected_at=NOW,
        reliability=1.0,
        warnings=["coleta limitada a 50 anúncios"],
    )
    session.add(source)
    session.flush()

    seller = Seller(
        marketplace=Marketplace.MERCADO_LIVRE,
        external_id="555",
        nickname="Loja Teste",
        reputation_level="5_green",
        reputation_score=97.0,
        positive_rating_pct=97.0,
        total_sales=25000,
        feedback_count=1800,
        is_official_store=True,
        power_seller_status="gold",
        source_record_id=source.id,
        last_seen_at=NOW,
    )
    session.add(seller)
    session.flush()

    product = Product(
        marketplace=Marketplace.MERCADO_LIVRE,
        external_id="MLB1",
        title="Fone Bluetooth Mini",
        brand="Acme",
        price=99.9,
        original_price=149.9,
        discount_pct=33.36,
        # Comissão desconhecida de propósito: a API de itens do ML não a expõe.
        affiliate_commission_pct=None,
        currency="BRL",
        rating=4.6,
        review_count=120,
        available_quantity=30,
        sold_quantity=400,
        source_record_id=source.id,
        seller_id=seller.id,
        first_seen_at=NOW,
        last_seen_at=NOW,
        identity_key="fone bluetooth mini acme",
    )
    session.add(product)
    session.flush()

    for offset in range(3):
        observed = NOW.replace(hour=10 - offset)
        session.add(
            ProductMetric(
                product_id=product.id,
                observed_at=observed,
                sold_last_period=120 - offset * 10,
                review_count=120 - offset * 5,
                rating=4.6,
                source_record_id=source.id,
            )
        )

    session.commit()
    product_id = product.id
    session.close()
    return {"product_id": product_id, "source_id": source.id}


class TestMeta:
    def test_root(self, client) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "marketTon" in response.json()["service"]

    def test_health_reports_structure_and_connectors(self, client) -> None:
        """O health precisa informar banco, IA e conectores — não só "subiu".

        A versão anterior respondia "ok" se o *arquivo* do SQLite existisse, o que
        não dizia nada sobre o schema estar aplicado. Aqui o campo vem de um
        `SELECT 1` real.
        """
        response = client.get("/health")
        assert response.status_code == 200

        body = response.json()
        assert "database" in body
        assert isinstance(body["database"]["connected"], bool)
        assert body["status"] in {"ok", "degraded"}
        assert {"mercado_livre", "shopee", "amazon", "tiktok_shop"} <= set(
            body["marketplace_supported"]
        )

    def test_health_is_degraded_when_database_is_unreachable(self, client) -> None:
        """Banco fora do ar precisa aparecer como `degraded`, não como erro 500.

        Este é o estado esperado quando o PostgreSQL ainda não subiu — e é melhor
        que um 500, porque o operador consegue ler a causa.
        """
        response = client.get("/health")
        body = response.json()

        if not body["database"]["connected"]:
            assert body["status"] == "degraded"
            assert body["database"]["error"]


class TestCatalog:
    def test_lists_products(self, client, seeded) -> None:
        response = client.get("/catalog/products")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1

        item = items[0]
        assert item["title"] == "Fone Bluetooth Mini"
        assert item["price"] == 99.9
        # Ponto central: comissão não coletada sai `null`, não `0`.
        assert item["affiliate_commission_pct"] is None

    def test_product_detail_includes_seller_and_provenance(self, client, seeded) -> None:
        response = client.get(f"/catalog/products/{seeded['product_id']}")
        assert response.status_code == 200
        body = response.json()

        assert body["seller"]["nickname"] == "Loja Teste"
        assert body["seller"]["total_sales"] == 25000
        assert body["source_record"]["connector"] == "mercado_livre"
        assert body["source_record"]["reliability"] == 1.0
        assert body["source_record"]["warnings"] == ["coleta limitada a 50 anúncios"]

        # Série temporal em ordem cronológica para o gráfico.
        assert len(body["metrics_history"]) == 3
        assert body["metrics_history"][0]["sold_last_period"] == 100
        assert body["metrics_history"][-1]["sold_last_period"] == 120

    def test_product_not_found(self, client) -> None:
        assert client.get("/catalog/products/9999").status_code == 404

    def test_search_and_filters(self, client, seeded) -> None:
        assert len(client.get("/catalog/products", params={"search": "fone"}).json()) == 1
        assert client.get("/catalog/products", params={"search": "inexistente"}).json() == []
        assert len(client.get("/catalog/products", params={"min_price": 50}).json()) == 1
        assert client.get("/catalog/products", params={"min_price": 500}).json() == []

    def test_filter_by_unknown_commission_excludes_product(self, client, seeded) -> None:
        """Filtrar por comissão mínima exclui quem tem comissão desconhecida.

        É diferente de excluir quem tem comissão baixa — e é o comportamento
        correto: não dá para afirmar que a comissão de um produto desconhecido
        satisfaz o mínimo.
        """
        result = client.get("/catalog/products", params={"min_commission_pct": 1}).json()
        assert result == []

    def test_provenance_trail(self, client, seeded) -> None:
        response = client.get(f"/catalog/products/{seeded['product_id']}/source")
        assert response.status_code == 200
        records = response.json()
        assert len(records) >= 1
        assert records[0]["connector"] == "mercado_livre"

    def test_stats_reports_field_coverage(self, client, seeded) -> None:
        body = client.get("/catalog/stats").json()
        assert body["total_products"] == 1
        assert body["active_products"] == 1
        coverage = body["field_coverage"]
        # Preço foi coletado; comissão não. A cobertura precisa refletir isso.
        assert coverage["price"] == 1
        assert coverage["affiliate_commission_pct"] == 0

    def test_marketplaces_lists_connectors(self, client) -> None:
        body = client.get("/catalog/marketplaces").json()
        assert "mercado_livre" in body["supported"]
        names = {connector["connector"] for connector in body["connectors"]}
        assert {"mercado_livre", "shopee", "amazon", "tiktok_shop"} <= names


class TestScoringExplains:
    def test_algorithms_are_versioned_and_expose_weights(self, client) -> None:
        body = client.get("/scoring/algorithms").json()
        dimensions = {item["dimension"] for item in body}
        assert {"HEAT", "OPPORTUNITY", "PRODUCER_MOMENTUM", "CREATIVE_SATURATION"} <= dimensions

        heat = next(item for item in body if item["dimension"] == "HEAT")
        assert heat["version"] == "v1"
        assert heat["weights"]
        assert heat["formula"]

    def test_compute_produces_an_auditable_run(self, client, seeded) -> None:
        response = client.post(
            "/scoring/compute",
            json={"dimension": "HEAT", "target_type": "product", "target_id": seeded["product_id"]},
        )
        assert response.status_code == 201
        body = response.json()

        assert body["dimension"] == "HEAT"
        assert 0 <= body["score"] <= 100
        assert body["formula"]
        assert body["weights"]
        assert body["contributions"]

        # A soma dos impactos reconstrói o score — é o que torna a explicação
        # auditável em vez de narrativa.
        total = sum(c["impact"] for c in body["contributions"])
        assert total == pytest.approx(body["score"], abs=0.02)

    def test_reasons_use_the_briefing_format(self, client, seeded) -> None:
        client.post(
            "/scoring/compute",
            json={"dimension": "HEAT", "target_type": "product", "target_id": seeded["product_id"]},
        )
        body = client.get(f"/scoring/targets/product/{seeded['product_id']}").json()
        assert body

        explanation = next(item for item in body if item["dimension"] == "HEAT")
        assert explanation["reasons"], "a explicação não pode ser vazia"
        assert all(reason.startswith(("+ ", "- ")) for reason in explanation["reasons"])

    def test_missing_factor_is_reported_as_unavailable(self, client, seeded) -> None:
        """Sem dados de anúncios, a saturação sai como INSUFFICIENT_DATA.

        Este é o comportamento exigido pelo briefing seção 5: a dimensão é
        condicionada a "quando houver dados suficientes", e o sistema declara a
        ausência em vez de estimar.
        """
        response = client.post(
            "/scoring/compute",
            json={
                "dimension": "CREATIVE_SATURATION",
                "target_type": "product",
                "target_id": seeded["product_id"],
            },
        )
        assert response.status_code == 201
        body = response.json()

        assert body["status"] == "INSUFFICIENT_DATA"
        assert body["is_complete"] is False
        assert body["confidence"] == 0.0
        assert body["insufficient_reasons"]
        assert all(not c["available"] for c in body["contributions"])

    def test_run_audit_endpoint(self, client, seeded) -> None:
        created = client.post(
            "/scoring/compute",
            json={"dimension": "HEAT", "target_type": "product", "target_id": seeded["product_id"]},
        ).json()

        body = client.get(f"/scoring/runs/{created['id']}").json()
        assert body["id"] == created["id"]
        assert len(body["contributions"]) == len(created["contributions"])
        assert body["algorithm_version"] == "v1"

    def test_opportunity_consumes_other_scores(self, client, seeded) -> None:
        """Opportunity reutiliza scores **completos** já calculados.

        Ponto de arquitetura verificado aqui: um score com dado faltante não é
        propagado como insumo. O `PRODUCER_MOMENTUM` do fixture sai como
        `INSUFFICIENT_DATA` (a API do Mercado Livre não expõe número de anúncios
        ativos, promoções nem taxa de resposta), então ele **não** entra no
        Opportunity — que por isso reduz a própria confiança em vez de herdar um
        número de qualidade duvidosa e parecer bem fundamentado.

        O `HEAT`, esse sim, tem todos os insumos no fixture: propaga normalmente.
        """
        for dimension in ("HEAT", "PRODUCER_MOMENTUM"):
            computed = client.post(
                "/scoring/compute",
                json={
                    "dimension": dimension,
                    "target_type": "product",
                    "target_id": seeded["product_id"],
                },
            )
            assert computed.status_code == 201

        # Confirma a premissa: momentum saiu incompleto e heat não.
        momentum = client.get(f"/scoring/targets/product/{seeded['product_id']}").json()
        by_dimension = {item["dimension"]: item for item in momentum}
        assert by_dimension["PRODUCER_MOMENTUM"]["status"] == "INSUFFICIENT_DATA"
        assert by_dimension["HEAT"]["status"] == "SUCCEEDED"

        body = client.post(
            "/scoring/compute",
            json={
                "dimension": "OPPORTUNITY",
                "target_type": "product",
                "target_id": seeded["product_id"],
            },
        ).json()

        by_factor = {c["factor"]: c for c in body["contributions"]}
        # Heat propagou: foi calculado com insumos completos.
        assert by_factor["heat"]["available"] is True
        # Momentum não propagou: saiu incompleto, e ausência vira ausência.
        assert by_factor["producer_momentum"]["available"] is False
        # Sem coletor de anúncios, saturação e pressão continuam desconhecidas.
        assert by_factor["saturation_headroom"]["available"] is False
        assert by_factor["affiliate_pressure"]["available"] is False
        # A comissão também é desconhecida: a API de itens do ML não a expõe.
        assert by_factor["commission"]["available"] is False
        # E a confiança reflete isso, em vez de fingir completude.
        assert body["confidence"] < 1.0
        assert body["status"] == "INSUFFICIENT_DATA"

    def test_producer_momentum_reports_only_exposed_signals(self, client, seeded) -> None:
        """Só os fatores que a fonte expõe ficam disponíveis, e a confiança cai."""
        body = client.post(
            "/scoring/compute",
            json={
                "dimension": "PRODUCER_MOMENTUM",
                "target_type": "product",
                "target_id": seeded["product_id"],
            },
        ).json()

        by_factor = {c["factor"]: c for c in body["contributions"]}
        assert by_factor["sales_track_record"]["available"] is True
        assert by_factor["reputation"]["available"] is True
        assert by_factor["listing_growth"]["available"] is False
        assert by_factor["promotional_activity"]["available"] is False
        assert by_factor["responsiveness"]["available"] is False

        # Confiança parcial: os dois fatores disponíveis somam 0,45 dos pesos.
        assert 0 < body["confidence"] < 1.0

    def test_compute_without_required_fields(self, client) -> None:
        assert client.post("/scoring/compute", json={"dimension": "HEAT"}).status_code == 422

    def test_compute_unknown_product(self, client) -> None:
        response = client.post(
            "/scoring/compute",
            json={"dimension": "HEAT", "target_type": "product", "target_id": 9999},
        )
        assert response.status_code == 404

    def test_unsupported_dimension_target_combination(self, client, seeded) -> None:
        response = client.post(
            "/scoring/compute",
            json={"dimension": "PORTFOLIO", "target_type": "product", "target_id": seeded["product_id"]},
        )
        assert response.status_code == 422


class TestPortfolio:
    def test_transition_graph_is_exposed(self, client) -> None:
        body = client.get("/portfolio/transitions").json()
        assert "DISCOVERED" in body["states"]
        assert "REMOVED" in body["states"]
        assert body["transitions"]["REMOVED"] == []
        assert "ANALYZING" in body["transitions"]["DISCOVERED"]

    def test_add_product_to_portfolio(self, client, seeded) -> None:
        response = client.post("/portfolio/items", json={"product_id": seeded["product_id"]})
        assert response.status_code == 201
        body = response.json()

        assert body["state"] == "DISCOVERED"
        # O backend informa o que é permitido a seguir.
        assert "ANALYZING" in body["allowed_transitions"]

    def test_duplicate_add_is_rejected(self, client, seeded) -> None:
        client.post("/portfolio/items", json={"product_id": seeded["product_id"]})
        response = client.post("/portfolio/items", json={"product_id": seeded["product_id"]})
        assert response.status_code == 409
        assert "já está no portfólio" in response.json()["detail"]

    def test_add_unknown_product(self, client) -> None:
        assert client.post("/portfolio/items", json={"product_id": 9999}).status_code == 404

    def test_valid_transition(self, client, seeded) -> None:
        item = client.post("/portfolio/items", json={"product_id": seeded["product_id"]}).json()

        response = client.post(
            f"/portfolio/items/{item['id']}/transition",
            json={"to_state": "ANALYZING", "actor": "operator:everton", "reason": "score alto"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["from_state"] == "DISCOVERED"
        assert body["to_state"] == "ANALYZING"
        assert body["actor"] == "operator:everton"

        detail = client.get(f"/portfolio/items/{item['id']}").json()
        assert detail["state"] == "ANALYZING"
        assert len(detail["transitions"]) == 1

    def test_invalid_transition_returns_409_with_allowed_list(self, client, seeded) -> None:
        """O cliente não precisa conhecer o grafo: a API diz o que é permitido."""
        item = client.post("/portfolio/items", json={"product_id": seeded["product_id"]}).json()

        response = client.post(
            f"/portfolio/items/{item['id']}/transition",
            json={"to_state": "PUBLISHED"},
        )
        assert response.status_code == 409

        detail = response.json()["detail"]
        assert detail["current_state"] == "DISCOVERED"
        assert detail["requested_state"] == "PUBLISHED"
        assert "ANALYZING" in detail["allowed_transitions"]

    def test_unknown_state_returns_422(self, client, seeded) -> None:
        item = client.post("/portfolio/items", json={"product_id": seeded["product_id"]}).json()
        response = client.post(
            f"/portfolio/items/{item['id']}/transition", json={"to_state": "INVENTADO"}
        )
        assert response.status_code == 422

    def test_publish_gate_blocks_without_assets(self, client, seeded) -> None:
        """Briefing seção 8: READY_TO_PUBLISH exige os materiais obrigatórios."""
        item = client.post("/portfolio/items", json={"product_id": seeded["product_id"]}).json()

        for target in (
            "ANALYZING",
            "RECOMMENDED",
            "AFFILIATION_PENDING",
            "AFFILIATED",
            "PORTFOLIO_ACTIVE",
            "CREATIVE_PENDING",
        ):
            response = client.post(
                f"/portfolio/items/{item['id']}/transition", json={"to_state": target}
            )
            assert response.status_code == 200, response.text

        response = client.post(
            f"/portfolio/items/{item['id']}/transition", json={"to_state": "READY_TO_PUBLISH"}
        )
        assert response.status_code == 409
        assert "materiais obrigatórios pendentes" in response.json()["detail"]["message"]

    def test_publish_readiness_endpoint_lists_what_is_missing(self, client, seeded) -> None:
        item = client.post("/portfolio/items", json={"product_id": seeded["product_id"]}).json()
        body = client.get(f"/creatives/publish-readiness/{item['id']}").json()

        assert body["can_publish"] is False
        assert set(body["missing_assets"]) == {"COPY", "APPROVAL"}
        assert body["required_assets"] == ["APPROVAL", "COPY"]
        assert body["satisfied_assets"] == []


class TestCreativePipeline:
    @pytest.fixture
    def item(self, client, seeded):
        return client.post("/portfolio/items", json={"product_id": seeded["product_id"]}).json()

    def _create(self, client, item, asset_type="COPY"):
        return client.post(
            "/creatives/assets",
            json={
                "asset_type": asset_type,
                "title": f"{asset_type} do produto",
                "content_text": "Oferta direta",
            },
        ).json()

    def test_create_asset_starts_pending_with_event(self, client, item) -> None:
        asset = self._create(client, item)
        assert asset["status"] == "PENDING"
        assert asset["version"] == 1

        history = client.get(f"/creatives/assets/{asset['id']}/history").json()
        assert len(history) == 1
        assert history[0]["to_status"] == "PENDING"

    def test_status_transition_is_validated(self, client, item) -> None:
        asset = self._create(client, item)

        # PENDING -> APPROVED não é permitido: pular etapas esconderia revisão.
        response = client.post(
            f"/creatives/assets/{asset['id']}/status", json={"status": "APPROVED"}
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["current_status"] == "PENDING"
        assert "READY" in detail["allowed_transitions"]

    def test_full_copy_flow_records_history(self, client, item) -> None:
        asset = self._create(client, item)

        for status in ("IN_PROGRESS", "READY", "APPROVED"):
            response = client.post(
                f"/creatives/assets/{asset['id']}/status",
                json={"status": status, "actor": "operator:everton"},
            )
            assert response.status_code == 200, response.text

        final = client.get(f"/creatives/assets/{asset['id']}").json()
        assert final["status"] == "APPROVED"
        assert final["approved_by"] == "operator:everton"

        history = client.get(f"/creatives/assets/{asset['id']}/history").json()
        assert [entry["to_status"] for entry in history] == [
            "PENDING",
            "IN_PROGRESS",
            "READY",
            "APPROVED",
        ]

    def test_unknown_asset_type_is_rejected(self, client) -> None:
        response = client.post("/creatives/assets", json={"asset_type": "HOLOGRAMA"})
        assert response.status_code == 422

    def test_pending_and_ready_lists(self, client, item) -> None:
        self._create(client, item, "COPY")
        assert len(client.get("/creatives/pending").json()) == 1
        assert client.get("/creatives/ready").json() == []

        response = client.post(
            "/creatives/assets/1/status", json={"status": "READY"}
        )
        assert response.status_code == 200
        assert len(client.get("/creatives/ready").json()) == 1
        assert client.get("/creatives/pending").json() == []


class TestLegacySupport:
    def test_feedback_roundtrip(self, client) -> None:
        created = client.post(
            "/support/feedback",
            json={"channel": "telegram", "user_id": 7, "text": "gostei", "username": "ana"},
        )
        assert created.status_code == 201

        items = client.get("/support/feedback").json()
        assert len(items) == 1
        assert items[0]["text"] == "gostei"

    def test_preferences_upsert(self, client) -> None:
        first = client.put(
            "/support/preferences/7", json={"user_id": 7, "username": "ana", "muted": False}
        )
        assert first.status_code == 200

        client.put("/support/preferences/7", json={"user_id": 7, "username": "ana", "muted": True})
        items = client.get("/support/preferences").json()
        assert len(items) == 1, "upsert não pode duplicar"
        assert items[0]["muted"] is True

    def test_group_status_is_schema_validated(self, client) -> None:
        """O endpoint anterior recebia `dict` sem validação."""
        ok = client.post("/support/groups/42/status", json={"status": "blocked", "reason": "spam"})
        assert ok.status_code == 200

        missing_status = client.post("/support/groups/43/status", json={"reason": "sem status"})
        assert missing_status.status_code == 422

    def test_agenda_rejects_bad_date(self, client) -> None:
        response = client.post(
            "/support/agenda", json={"title": "Reunião", "when_date": "31/03/2026"}
        )
        assert response.status_code == 422

    def test_agenda_requires_title(self, client) -> None:
        assert client.post("/support/agenda", json={}).status_code == 422


class TestOperations:
    def test_daily_panel_has_every_block_even_when_empty(self, client, seeded) -> None:
        """Bloco vazio é diferente de bloco ausente."""
        body = client.get("/operations/daily").json()

        for block in (
            "opportunities_today",
            "recommended",
            "awaiting_decision",
            "affiliation_pending",
            "creatives_pending",
            "creatives_ready",
            "ready_to_publish",
            "published",
            "optimization_required",
            "alerts",
        ):
            assert block in body, f"bloco ausente: {block}"

        assert body["kpis"]["sales_count"] == 0
        # Sem venda, receita é `null`, não `0`.
        assert body["kpis"]["gross_revenue"] is None
        assert body["alerts"], "sem dado, o painel precisa avisar o operador"

    def test_weekly_review_compares_periods(self, client, seeded) -> None:
        body = client.get("/operations/weekly").json()

        assert "current" in body
        assert "previous" in body
        assert "delta" in body
        assert body["period"]["weeks_back"] == 1

        # Sem base nos dois períodos, o delta declara a limitação.
        revenue_delta = body["delta"]["gross_revenue"]
        assert revenue_delta["absolute"] is None
        assert revenue_delta["note"]

    def test_weekly_review_lists_candidate_blocks(self, client, seeded) -> None:
        body = client.get("/operations/weekly").json()
        for block in ("scale_candidates", "pause_candidates", "removal_candidates"):
            assert block in body

    def test_connector_status_endpoint(self, client) -> None:
        body = client.get("/operations/connectors").json()
        names = {connector["connector"] for connector in body}
        assert {"mercado_livre", "shopee", "amazon", "tiktok_shop"} <= names
        assert all(connector["configured"] is False for connector in body)


class TestJobs:
    def test_empty_job_lists(self, client) -> None:
        assert client.get("/jobs").json() == []
        assert client.get("/jobs/stats").json()["total_jobs"] == 0

    def test_job_stats_reports_null_success_rate_without_jobs(self, client) -> None:
        """Sem job, a taxa de sucesso é desconhecida — não 0%."""
        body = client.get("/jobs/stats").json()
        assert body["success_rate"] is None

    def test_job_not_found(self, client) -> None:
        assert client.get("/jobs/999").status_code == 404
        assert client.get("/jobs/999/events").status_code == 404
