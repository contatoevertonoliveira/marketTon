"""Testes dos agentes convertidos para IA real (Fase 3).

O que estes testes protegem, e por quê:

1. **A IA é enriquecimento, não dependência.** Com IA desligada os agentes ainda
   funcionam e declaram o motivo — não inventam resultado.
2. **A IA não define score.** Os scores vêm do motor versionado; a IA recebe os
   números prontos. Um teste verifica que o insumo entregue ao modelo contém os
   scores calculados.
3. **Falha de coleta não vira dado.** Era o defeito do CSV de tendências, que
   gravava erro HTTP na coluna de fonte.
4. **Observabilidade de jobs.** Cada execução deixa registro consultável, com
   eventos e desfecho — inclusive as falhas.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from core.db.ai import AIInterpretation
from core.db.base import (
    CreativeAssetType,
    CreativeStatus,
    JobStatus,
    Marketplace,
    PortfolioState,
    RecommendationKind,
    ScoreRunStatus,
)
from core.db.catalog import PriceHistory, Product
from core.db.creative import CreativeAsset
from core.db.jobs import Job, JobEvent
from core.db.portfolio import PortfolioItem, Recommendation
from core.db.scoring import ScoreRun
from core.db.trends import TrendObservation
from core.services.ai.client import AIClient, AIError, AIResponse
from core.services.jobs import job_health, job_run, last_successful_job, recent_jobs
from integrations.marketplaces.base import ConnectorBatch, ConnectorProduct

NOW = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)


class FakeProvider:
    """Provedor dublê. Registra as chamadas para que os testes possam inspecioná-las."""

    def __init__(self, payload: dict | str):
        self.payload = payload
        self.calls: list = []

    def complete(self, messages, *, temperature: float = 0.2) -> AIResponse:
        self.calls.append(messages)
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return AIResponse(text=text, model="fake-model")


def fake_ai(payload: dict) -> tuple[AIClient, FakeProvider]:
    """Cliente com provedor dublê. `is_available` é True por ter provedor."""
    provider = FakeProvider(payload)
    return AIClient(provider=provider), provider


def unavailable_ai() -> AIClient:
    """Cliente com IA indisponível, para testar o caminho de degradação.

    `settings=None` força `is_available` a False de forma determinística: um
    `AIClient()` sem provedor consultaria `config.settings`, e o teste passaria a
    depender de `AI_ENABLED` estar desligado no ambiente.
    """
    client = AIClient(provider=None)
    client.settings = None
    return client


# --- Observabilidade de jobs --------------------------------------------------


class TestJobRecording:
    def test_successful_job_is_recorded_with_events(self, session) -> None:
        with job_run(session, job_type="test.ok", agent="tester") as handle:
            handle.add_event("passo 1")
            handle.add_event("passo 2", payload={"count": 2})
            handle.finish(summary="tudo certo", result={"rows": 2})

        job = session.scalars(select(Job)).one()
        assert job.status == JobStatus.SUCCEEDED
        assert job.agent == "tester"
        assert job.result_summary == "tudo certo"
        assert job.result == {"rows": 2}
        assert job.finished_at is not None
        assert job.duration_seconds is not None

        events = session.scalars(
            select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.occurred_at)
        ).all()
        # Um evento de início mais os dois adicionados.
        assert len(events) == 3
        assert events[0].message.startswith("job 'test.ok' iniciado")

    def test_failed_job_records_error_and_reraises(self, session) -> None:
        """O invólucro observa, não engole: a exceção propaga."""
        with pytest.raises(RuntimeError, match="falha simulada"):
            with job_run(session, job_type="test.fail", agent="tester"):
                raise RuntimeError("falha simulada")

        job = session.scalars(select(Job)).one()
        assert job.status == JobStatus.FAILED
        assert job.error_type == "RuntimeError"
        assert "falha simulada" in job.error_message
        assert job.error_traceback

    def test_job_without_explicit_finish_is_marked_succeeded(self, session) -> None:
        """Deixar em RUNNING para sempre é pior do que assumir conclusão normal."""
        with job_run(session, job_type="test.implicit"):
            pass

        job = session.scalars(select(Job)).one()
        assert job.status == JobStatus.SUCCEEDED

    def test_idempotency_key_prevents_duplicate_execution(self, session) -> None:
        executed: list[int] = []

        for _ in range(2):
            with job_run(
                session, job_type="test.idem", idempotency_key="chave-fixa"
            ) as handle:
                if "execução ignorada" not in " ".join(
                    event.message for event in handle._events
                ):
                    executed.append(1)

        assert executed == [1], "a segunda execução deveria ter sido ignorada"
        assert len(session.scalars(select(Job)).all()) == 1

    def test_progress_is_clamped(self, session) -> None:
        with job_run(session, job_type="test.progress") as handle:
            handle.set_progress(150)
            assert handle.job.progress_pct == 100.0
            handle.set_progress(-10)
            assert handle.job.progress_pct == 0.0

    def test_last_successful_job_ignores_failures(self, session) -> None:
        with pytest.raises(RuntimeError):
            with job_run(session, job_type="cycle", agent="a"):
                raise RuntimeError("x")

        assert last_successful_job(session, job_type="cycle") is None

        with job_run(session, job_type="cycle", agent="a") as handle:
            handle.finish(summary="ok")

        found = last_successful_job(session, job_type="cycle")
        assert found is not None
        assert found.result_summary == "ok"

    def test_job_health_reports_staleness(self, session) -> None:
        """Um job que deveria rodar de hora em hora e não roda há seis é um problema
        que nenhum log mostra diretamente."""
        with job_run(session, job_type="hourly", agent="a") as handle:
            handle.finish()
        job = session.scalars(select(Job)).one()
        job.finished_at = datetime.now(UTC) - timedelta(hours=30)
        session.commit()

        health = job_health(session)
        entry = next(item for item in health["types"] if item["job_type"] == "hourly")
        assert entry["stale"] is True
        assert entry["hours_since_last"] > 24

    def test_recent_jobs_filters_by_status(self, session) -> None:
        with job_run(session, job_type="a") as handle:
            handle.finish()
        with pytest.raises(RuntimeError):
            with job_run(session, job_type="b"):
                raise RuntimeError("x")

        assert len(recent_jobs(session, status=JobStatus.SUCCEEDED)) == 1
        assert len(recent_jobs(session, status=JobStatus.FAILED)) == 1


# --- Product Hunter -----------------------------------------------------------


def _batch(marketplace_product: ConnectorProduct) -> ConnectorBatch:
    return ConnectorBatch(
        connector="mercado_livre",
        products=[marketplace_product],
        collected_at=NOW,
        endpoint="https://api.mercadolibre.com/items",
        reliability=1.0,
    )


class _StubAdapter:
    """Adapter dublê: devolve lote fixo, sem rede."""

    name = "mercado_livre"
    reliability = 1.0

    def __init__(self, batch: ConnectorBatch | None = None, configured: bool = True):
        self._batch = batch
        self._configured = configured

    def is_configured(self) -> bool:
        return self._configured

    def fetch_products(self, *, limit=None, options=None) -> ConnectorBatch:
        if self._batch is None:
            return ConnectorBatch(connector=self.name, collected_at=NOW)
        return self._batch

    def fetch_sales(self, *, since=None):
        return []

    def search_competitor(self, query, *, limit=10):
        return []

    def get_status(self):
        return {"connector": self.name, "configured": self._configured}


class TestProductHunter:
    def test_without_session_declares_limitation(self) -> None:
        """O CSV anterior era beco sem saída; escrever CSV e chamar de coleta é pior
        que declarar que não persistiu."""
        from agents.product_hunter.agent import run

        result = run({})
        assert result.ok is True
        assert "sem sessão de banco" in result.summary
        assert result.artifacts["persisted"] is False

    def test_persists_products_with_provenance(self, session) -> None:
        from agents.product_hunter.agent import HunterOptions, run

        adapter = _StubAdapter(
            _batch(
                ConnectorProduct(
                    external_id="MLB1",
                    title="Fone Bluetooth",
                    price=99.9,
                    available_quantity=10,
                    rating=4.5,
                    sold_quantity=100,
                )
            )
        )

        options = HunterOptions(adapter_names=["mercado_livre"], use_ai=False, score_limit=5)
        result = run({}, session=session, adapters={"mercado_livre": adapter}, options=options)

        assert result.artifacts["created"] == 1
        product = session.scalars(select(Product)).one()
        assert product.title == "Fone Bluetooth"
        # Procedência: a constraint garante, e o teste confirma que passou por ela.
        assert product.source_record_id is not None

    def test_scores_come_from_the_engine_not_from_price(self, session) -> None:
        """O defeito antigo era `score = preço + 20`. Agora há ScoreRun persistido."""
        from agents.product_hunter.agent import HunterOptions, run

        adapter = _StubAdapter(
            _batch(
                ConnectorProduct(
                    external_id="MLB1",
                    title="Fone",
                    price=99.9,
                    sold_last_period=100,
                    rating=4.5,
                    available_quantity=10,
                )
            )
        )
        options = HunterOptions(adapter_names=["mercado_livre"], use_ai=False, score_limit=5)
        run({}, session=session, adapters={"mercado_livre": adapter}, options=options)

        runs = session.scalars(select(ScoreRun)).all()
        dimensions = {run.dimension.value for run in runs}
        assert {"HEAT", "OPPORTUNITY"} <= dimensions

        for run in runs:
            # Não é o preço somado a nada.
            assert float(run.score) != pytest.approx(99.9)
            assert float(run.score) != pytest.approx(119.9)
            assert run.inputs, "o cálculo precisa guardar os insumos"
            assert run.formula

    def test_unconfigured_adapter_is_reported_not_treated_as_empty(self, session) -> None:
        """Sem credencial é diferente de 'não há produtos'."""
        from agents.product_hunter.agent import HunterOptions, run

        adapter = _StubAdapter(configured=False)
        options = HunterOptions(adapter_names=["mercado_livre"], use_ai=False)
        result = run({}, session=session, adapters={"mercado_livre": adapter}, options=options)

        errors = result.artifacts["collect_errors"]
        assert any("sem credencial" in error for error in errors)

    def test_adapter_failure_does_not_break_the_job(self, session) -> None:
        from agents.product_hunter.agent import HunterOptions, run

        class Broken:
            name = "mercado_livre"
            reliability = 1.0

            def is_configured(self):
                return True

            def fetch_products(self, *, limit=None):
                raise RuntimeError("API fora do ar")

        options = HunterOptions(adapter_names=["mercado_livre"], use_ai=False)
        result = run({}, session=session, adapters={"mercado_livre": Broken()}, options=options)

        assert result.ok is True
        assert any("falhou" in error for error in result.artifacts["collect_errors"])

        job = session.scalars(select(Job)).one()
        assert job.status == JobStatus.SUCCEEDED

    def test_ai_receives_computed_scores(self, session) -> None:
        """A IA interpreta números prontos; não os recalcula."""
        from agents.product_hunter.agent import HunterOptions, run

        adapter = _StubAdapter(
            _batch(
                ConnectorProduct(
                    external_id="MLB1", title="Fone", price=99.9, sold_last_period=100, rating=4.5
                )
            )
        )
        ai, provider = fake_ai(
            {"verdict": "promising", "reasons_for": ["heat alto"], "reasons_against": []}
        )
        options = HunterOptions(
            adapter_names=["mercado_livre"], use_ai=True, ai_candidates=1, score_limit=5
        )
        result = run(
            {}, session=session, adapters={"mercado_livre": adapter}, ai=ai, options=options
        )

        evaluations = result.artifacts["evaluations"]
        assert len(evaluations) == 1
        assert evaluations[0]["verdict"] == "promising"

        # A interpretação foi registrada e o insumo contém os scores calculados.
        record = session.scalars(select(AIInterpretation)).one()
        assert record.agent == "product_hunter"
        scores = record.inputs["scores_calculados"]
        assert "HEAT" in scores and "OPPORTUNITY" in scores

    def test_ai_disabled_does_not_break_the_pipeline(self, session) -> None:
        from agents.product_hunter.agent import HunterOptions, run

        adapter = _StubAdapter(
            _batch(ConnectorProduct(external_id="MLB1", title="Fone", price=10.0, rating=4.0))
        )
        options = HunterOptions(adapter_names=["mercado_livre"], use_ai=True, score_limit=3)
        result = run(
            {},
            session=session,
            adapters={"mercado_livre": adapter},
            ai=unavailable_ai(),
            options=options,
        )

        assert result.ok is True
        assert result.artifacts["evaluations"] == []
        assert session.scalars(select(AIInterpretation)).all() == []


# --- Trend Hunter -------------------------------------------------------------


class _StubSeries:
    def __init__(self, frame):
        self.frame = frame


def test_trend_hunter_without_session_declares_limitation() -> None:
    from agents.trend_hunter.agent import run

    result = run({})
    assert "sem sessão de banco" in result.summary


class TestTrendHunter:
    @pytest.fixture
    def frame_factory(self):
        import pandas as pd

        def build(values):
            dates = pd.date_range("2026-04-01", periods=len(values), freq="D")
            return pd.DataFrame({"date": dates, "interest": values})

        return build

    def test_records_observations_with_provenance(self, session, frame_factory) -> None:
        from agents.trend_hunter.agent import TrendOptions, run

        def fetcher(keyword, *, geo, window_days):
            return _StubSeries(frame_factory([10, 12, 11, 40, 45, 50]))

        options = TrendOptions(keywords=["fone"], use_ai=False)
        result = run({}, session=session, options=options, fetcher=fetcher)

        assert result.artifacts["persisted"] is True
        observation = session.scalars(select(TrendObservation)).one()
        assert observation.points == 6
        assert observation.interest_last == 50
        assert observation.trend_direction == "rising"
        # Procedência: a série é uma coleta, com registro próprio.
        assert observation.source_record_id is not None

    def test_collection_failure_is_not_recorded_as_data(self, session) -> None:
        """O defeito do CSV: erro HTTP gravado na coluna de fonte, como se fosse dado.

        A correção é o erro ir para `warnings` do registro de procedência, e nenhuma
        observação de tendência ser criada.
        """
        from agents.trend_hunter.agent import TrendOptions, run

        def failing_fetcher(keyword, *, geo, window_days):
            raise RuntimeError("Google returned a response with code 400")

        options = TrendOptions(keywords=["marketing digital cristão"], use_ai=False)
        result = run({}, session=session, options=options, fetcher=failing_fetcher)

        # Nenhuma observação criada.
        assert session.scalars(select(TrendObservation)).all() == []

        failures = result.artifacts["collect_failures"]
        assert len(failures) == 1
        assert "400" in failures[0]["error"]

        # E o erro está na procedência, onde é auditável.
        from core.db.catalog import SourceRecord

        source = session.scalars(select(SourceRecord)).one()
        assert source.warnings
        assert "400" in source.warnings[0]["error"]

    def test_empty_series_is_not_treated_as_failure(self, session, frame_factory) -> None:
        """Fonte que responde sem série é diferente de falha de coleta."""
        from agents.trend_hunter.agent import TrendOptions, run

        def empty_fetcher(keyword, *, geo, window_days):
            return _StubSeries(frame_factory([]))

        options = TrendOptions(keywords=["x"], use_ai=False)
        result = run({}, session=session, options=options, fetcher=empty_fetcher)

        assert session.scalars(select(TrendObservation)).all() == []
        assert "série vazia" in result.artifacts["collect_failures"][0]["error"]

    def test_flat_series_is_stable_not_rising(self, session, frame_factory) -> None:
        """Faixa morta: ruído de medição não é tendência."""
        from agents.trend_hunter.agent import TrendOptions, run

        def flat_fetcher(keyword, *, geo, window_days):
            return _StubSeries(frame_factory([50, 51, 50, 49, 50, 51]))

        options = TrendOptions(keywords=["x"], use_ai=False)
        run({}, session=session, options=options, fetcher=flat_fetcher)

        observation = session.scalars(select(TrendObservation)).one()
        assert observation.trend_direction == "stable"
        assert abs(observation.change_pct or 0) <= 5

    def test_short_series_leaves_change_none(self, session, frame_factory) -> None:
        """Série curta não permite calcular variação; `None`, não zero."""
        from agents.trend_hunter.agent import TrendOptions, run

        def short_fetcher(keyword, *, geo, window_days):
            return _StubSeries(frame_factory([10, 20]))

        options = TrendOptions(keywords=["x"], use_ai=False)
        run({}, session=session, options=options, fetcher=short_fetcher)

        observation = session.scalars(select(TrendObservation)).one()
        assert observation.change_pct is None
        assert observation.trend_direction is None
        assert observation.interest_mean == 15.0

    def test_ai_gets_all_movements_together(self, session, frame_factory) -> None:
        """Uma chamada para o conjunto: o valor está em comparar movimentos entre si."""
        from agents.trend_hunter.agent import TrendOptions, run

        def fetcher(keyword, *, geo, window_days):
            values = [10, 12, 11, 40, 45, 50] if keyword == "sobe" else [50, 45, 40, 10, 12, 11]
            return _StubSeries(frame_factory(values))

        ai, provider = fake_ai({"movements": [], "summary": "leitura", "data_gaps": []})
        options = TrendOptions(keywords=["sobe", "cai"], use_ai=True)
        result = run({}, session=session, ai=ai, options=options, fetcher=fetcher)

        assert result.artifacts["interpretation"] == {
            "movements": [],
            "summary": "leitura",
            "data_gaps": [],
        }
        # Uma única chamada para os dois movimentos.
        assert len(provider.calls) == 1

        record = session.scalars(select(AIInterpretation)).one()
        assert record.agent == "trend_hunter"
        assert len(record.inputs["movimentos"]) == 2


# --- Copy Chief ---------------------------------------------------------------


class TestCopyChief:
    def _scored_product(self, session, source_record, title="Fone", score=80.0) -> Product:
        product = Product(
            marketplace=Marketplace.MERCADO_LIVRE,
            external_id=f"MLB-{title}",
            title=title,
            price=99.9,
            rating=4.5,
            sold_quantity=200,
            source_record_id=source_record.id,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        session.add(product)
        session.flush()

        session.add(
            ScoreRun(
                algorithm_id=1,
                dimension="OPPORTUNITY",
                algorithm_version="v1",
                target_type="product",
                target_id=product.id,
                computed_at=NOW,
                inputs={"price": 99.9},
                weights={"commission": 0.25},
                score=score,
                confidence=0.8,
                is_complete=True,
                status=ScoreRunStatus.SUCCEEDED,
            )
        )
        session.flush()
        return product

    def test_without_session_declares_limitation(self) -> None:
        from agents.copy_chief.agent import run

        assert "sem sessão de banco" in run({}).summary

    def test_without_scored_products_generates_nothing(self, session) -> None:
        """Sem score não há candidato: escrever copy para produto arbitrário era o
        comportamento antigo, que sempre usava um produto fixo."""
        from agents.copy_chief.agent import CopyOptions, run

        ai, _ = fake_ai({"hook": "x"})
        result = run({}, session=session, ai=ai, options=CopyOptions())

        assert result.artifacts["generated"] == 0
        assert "Opportunity Score" in result.summary

    def test_generates_brief_and_creates_copy_asset(self, session, source_record) -> None:
        from agents.copy_chief.agent import CopyOptions, run

        product = self._scored_product(session, source_record)
        ai, provider = fake_ai(
            {
                "hook": "Você não vai acreditar",
                "narrative": "Três razões para comprar",
                "cta": "Compre agora",
                "target_audience": "adultos 25-40",
                "visual_notes": ["cena do produto em uso"],
                "claims_to_avoid": ["não prometer cura"],
            }
        )
        result = run({}, session=session, ai=ai, options=CopyOptions(max_products=1))

        assert result.artifacts["generated"] == 1

        asset = session.scalars(select(CreativeAsset)).one()
        assert asset.asset_type == CreativeAssetType.COPY
        # PENDING de propósito: a IA escreveu, quem aprova é humano.
        assert asset.status == CreativeStatus.PENDING
        assert asset.product_id == product.id
        assert "HOOK: Você não vai acreditar" in asset.content_text
        assert "NÃO PROMETER" in asset.content_text

    def test_copy_asset_is_traceable_to_the_interpretation(self, session, source_record) -> None:
        """A copy precisa ser rastreável até o dado que a originou."""
        from agents.copy_chief.agent import CopyOptions, run

        self._scored_product(session, source_record)
        ai, _ = fake_ai({"hook": "x", "narrative": "y", "cta": "z"})
        run({}, session=session, ai=ai, options=CopyOptions(max_products=1))

        record = session.scalars(select(AIInterpretation)).one()
        asset = session.scalars(select(CreativeAsset)).one()
        assert asset.external_ref == str(record.id)

    def test_new_generation_increments_version(self, session, source_record) -> None:
        """Uma copy nova não pode apagar o histórico da anterior."""
        from agents.copy_chief.agent import CopyOptions, run

        self._scored_product(session, source_record)
        for _ in range(2):
            ai, _ = fake_ai({"hook": "h"})
            run({}, session=session, ai=ai, options=CopyOptions(max_products=1))

        assets = session.scalars(
            select(CreativeAsset).where(CreativeAsset.asset_type == CreativeAssetType.COPY)
        ).all()
        assert sorted(asset.version for asset in assets) == [1, 2]

    def test_ai_disabled_generates_nothing_with_reason(self, session, source_record) -> None:
        """Template fixo apresentado como copy personalizada seria pior que nada."""
        from agents.copy_chief.agent import CopyOptions, run

        self._scored_product(session, source_record)
        result = run(
            {},
            session=session,
            ai=unavailable_ai(),
            options=CopyOptions(max_products=1),
        )

        assert result.artifacts["generated"] == 0
        assert "IA desligada" in result.summary
        assert session.scalars(select(CreativeAsset)).all() == []

    def test_low_score_is_filtered_out(self, session, source_record) -> None:
        from agents.copy_chief.agent import CopyOptions, run

        self._scored_product(session, source_record, score=40.0)
        ai, _ = fake_ai({"hook": "x"})
        result = run(
            {},
            session=session,
            ai=ai,
            options=CopyOptions(max_products=1, min_opportunity_score=70.0),
        )
        assert result.artifacts["generated"] == 0


# --- Marketplace Manager ------------------------------------------------------


class TestMarketplaceManager:
    def test_without_session_declares_limitation(self) -> None:
        from agents.marketplace_manager.agent import run

        assert "sem sessão de banco" in run({}).summary

    def test_detects_out_of_stock_as_critical(self, session, source_record) -> None:
        from agents.marketplace_manager.agent import run

        session.add(
            Product(
                marketplace=Marketplace.MERCADO_LIVRE,
                external_id="MLB1",
                title="Sem estoque",
                price=50.0,
                available_quantity=0,
                source_record_id=source_record.id,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
        session.commit()

        result = run({}, session=session, ai=unavailable_ai())

        findings = result.artifacts["findings"]
        critical = [f for f in findings if f["severity"] == "critical"]
        assert any(f["rule"] == "stock_zero" for f in critical)

    def test_detects_stale_product(self, session, source_record) -> None:
        from agents.marketplace_manager.agent import run

        old = datetime.now(UTC) - timedelta(days=30)
        session.add(
            Product(
                marketplace=Marketplace.MERCADO_LIVRE,
                external_id="MLB1",
                title="Antigo",
                price=50.0,
                source_record_id=source_record.id,
                first_seen_at=old,
                last_seen_at=old,
            )
        )
        session.commit()

        result = run({}, session=session, ai=unavailable_ai())
        rules = {f["rule"] for f in result.artifacts["findings"]}
        assert any(rule.startswith("stale_product") for rule in rules)

    def test_detects_sharp_price_drop_as_info_not_alert(self, session, source_record) -> None:
        """Queda de preço pode ser oportunidade ou problema; quem decide é o operador."""
        from agents.marketplace_manager.agent import run

        product = Product(
            marketplace=Marketplace.MERCADO_LIVRE,
            external_id="MLB1",
            title="Caiu de preço",
            price=50.0,
            source_record_id=source_record.id,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        session.add(product)
        session.flush()

        session.add(
            PriceHistory(
                product_id=product.id,
                observed_at=NOW - timedelta(days=10),
                price=100.0,
                source_record_id=source_record.id,
            )
        )
        session.add(
            PriceHistory(
                product_id=product.id,
                observed_at=NOW,
                price=50.0,
                source_record_id=source_record.id,
            )
        )
        session.commit()

        result = run({}, session=session, ai=unavailable_ai())
        drops = [f for f in result.artifacts["findings"] if f["rule"].startswith("price_drop")]
        assert len(drops) == 1
        assert drops[0]["severity"] == "info"

    def test_detects_missing_price(self, session, source_record) -> None:
        from agents.marketplace_manager.agent import run

        session.add(
            Product(
                marketplace=Marketplace.MERCADO_LIVRE,
                external_id="MLB1",
                title="Sem preço",
                price=None,
                source_record_id=source_record.id,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
        session.commit()

        result = run({}, session=session, ai=unavailable_ai())
        assert any(f["rule"] == "missing_price" for f in result.artifacts["findings"])

    def test_ai_prioritizes_findings(self, session, source_record) -> None:
        from agents.marketplace_manager.agent import run

        session.add(
            Product(
                marketplace=Marketplace.MERCADO_LIVRE,
                external_id="MLB1",
                title="Sem estoque",
                price=10.0,
                available_quantity=0,
                source_record_id=source_record.id,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
        session.commit()

        ai, _ = fake_ai({"urgent": [], "watching": [], "summary": "ok"})
        result = run({}, session=session, ai=ai)

        assert result.artifacts["interpretation"]["summary"] == "ok"
        record = session.scalars(select(AIInterpretation)).one()
        assert record.agent == "marketplace_manager"

    def test_clean_catalog_produces_no_findings(self, session, source_record) -> None:
        from agents.marketplace_manager.agent import run

        session.add(
            Product(
                marketplace=Marketplace.MERCADO_LIVRE,
                external_id="MLB1",
                title="Saudável",
                price=50.0,
                available_quantity=10,
                source_record_id=source_record.id,
                first_seen_at=NOW,
                last_seen_at=datetime.now(UTC),
            )
        )
        session.commit()

        result = run({}, session=session, ai=unavailable_ai())
        assert result.artifacts["findings_count"] == 0


# --- Master -------------------------------------------------------------------


class TestMaster:
    def test_without_session_declares_limitation(self) -> None:
        from agents.master.agent import run

        assert "sem sessão de banco" in run({}).summary

    def test_empty_catalog_is_reported_as_note(self, session) -> None:
        from agents.master.agent import run

        result = run({}, session=session, ai=unavailable_ai(), options=_master_options())
        assert any("catálogo vazio" in note for note in result.artifacts["state"]["notes"])

    def test_high_score_product_becomes_a_recommendation(self, session, source_record) -> None:
        """A recomendação cita os fatores do próprio cálculo, não explicação inventada."""
        from agents.master.agent import run

        product = Product(
            marketplace=Marketplace.MERCADO_LIVRE,
            external_id="MLB1",
            title="Bom produto",
            price=99.9,
            source_record_id=source_record.id,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        session.add(product)
        session.flush()

        run_row = ScoreRun(
            algorithm_id=1,
            dimension="OPPORTUNITY",
            algorithm_version="v1",
            target_type="product",
            target_id=product.id,
            computed_at=NOW,
            inputs={"price": 99.9},
            weights={"commission": 0.25},
            score=85.0,
            confidence=0.9,
            is_complete=True,
            status=ScoreRunStatus.SUCCEEDED,
        )
        session.add(run_row)
        session.flush()

        from core.db.scoring import ScoreContribution

        session.add(
            ScoreContribution(
                run_id=run_row.id,
                position=0,
                factor="commission",
                label="comissão oferecida",
                impact=21.0,
                available=True,
                is_positive=True,
                explanation="comissão de 20%",
            )
        )
        session.commit()

        result = run({}, session=session, ai=unavailable_ai(), options=_master_options())

        recommendation = _recommendations_of(session, RecommendationKind.AFFILIATE)[0]
        assert recommendation.score_run_id == run_row.id
        assert recommendation.priority == 85
        assert "+ comissão de 20%" in recommendation.positive_factors
        assert "85.0/100" in recommendation.rationale
        del result

    def test_low_confidence_score_is_not_recommended(self, session, source_record) -> None:
        """Score alto com confiança baixa não é recomendação: é palpite."""
        from agents.master.agent import run

        product = Product(
            marketplace=Marketplace.MERCADO_LIVRE,
            external_id="MLB1",
            title="Incerto",
            price=99.9,
            source_record_id=source_record.id,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        session.add(product)
        session.flush()

        session.add(
            ScoreRun(
                algorithm_id=1,
                dimension="OPPORTUNITY",
                algorithm_version="v1",
                target_type="product",
                target_id=product.id,
                computed_at=NOW,
                inputs={},
                weights={},
                score=90.0,
                confidence=0.2,
                is_complete=False,
                status=ScoreRunStatus.SUCCEEDED,
            )
        )
        session.commit()

        run({}, session=session, ai=unavailable_ai(), options=_master_options())
        assert _recommendations_of(session, RecommendationKind.AFFILIATE) == []

    def test_low_score_is_not_recommended(self, session, source_record) -> None:
        from agents.master.agent import run

        product = Product(
            marketplace=Marketplace.MERCADO_LIVRE,
            external_id="MLB1",
            title="Fraco",
            price=99.9,
            source_record_id=source_record.id,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        session.add(product)
        session.flush()

        session.add(
            ScoreRun(
                algorithm_id=1,
                dimension="OPPORTUNITY",
                algorithm_version="v1",
                target_type="product",
                target_id=product.id,
                computed_at=NOW,
                inputs={},
                weights={},
                score=30.0,
                confidence=0.9,
                is_complete=True,
                status=ScoreRunStatus.SUCCEEDED,
            )
        )
        session.commit()

        run({}, session=session, ai=unavailable_ai(), options=_master_options())
        assert _recommendations_of(session, RecommendationKind.AFFILIATE) == []

    def test_deduplication_does_not_repeat_open_recommendation(self, session, source_record) -> None:
        """Sem dedupe, o ciclo criaria a mesma recomendação a cada execução."""
        from agents.master.agent import run

        item = _portfolio_item(session, source_record, PortfolioState.CREATIVE_PENDING)

        first = run({}, session=session, ai=unavailable_ai(), options=_master_options())
        second = run({}, session=session, ai=unavailable_ai(), options=_master_options())

        assert first.artifacts["persisted"] is True
        count = len(session.scalars(select(Recommendation)).all())
        assert count == len(first.artifacts["recommendations"])
        # A segunda execução não acumulou.
        assert count <= len(first.artifacts["recommendations"])
        del item, second

    def test_publish_readiness_creates_publish_recommendation(self, session, source_record) -> None:
        from agents.master.agent import run

        _portfolio_item(session, source_record, PortfolioState.READY_TO_PUBLISH)
        run({}, session=session, ai=unavailable_ai(), options=_master_options())

        recommendation = session.scalars(
            select(Recommendation).where(Recommendation.kind == RecommendationKind.PUBLISH)
        ).first()
        assert recommendation is not None
        assert recommendation.priority == 90

    def test_optimization_state_notes_missing_commission(self, session, source_record) -> None:
        """Diferencia 'sem resultado' de 'resultado ruim'."""
        from agents.master.agent import run

        _portfolio_item(session, source_record, PortfolioState.OPTIMIZATION_REQUIRED)
        run({}, session=session, ai=unavailable_ai(), options=_master_options())

        recommendation = session.scalars(
            select(Recommendation).where(Recommendation.kind == RecommendationKind.OPTIMIZE)
        ).first()
        assert recommendation is not None
        assert "Nenhuma comissão registrada" in recommendation.rationale

    def test_stale_job_becomes_a_recommendation(self, session) -> None:
        """Um job que nunca rodou é problema operacional, não detalhe técnico."""
        from agents.master.agent import run

        result = run({}, session=session, ai=unavailable_ai(), options=_master_options())

        assert result.artifacts["state"]["stale_jobs"]
        assert any(
            "Execução atrasada" in item["title"] for item in result.artifacts["recommendations"]
        )

    def test_persist_false_does_not_pollute_the_list(self, session, source_record) -> None:
        """Permite inspecionar o que o ciclo recomendaria sem gravar."""
        from agents.master.agent import run

        _portfolio_item(session, source_record, PortfolioState.READY_TO_PUBLISH)
        result = run(
            {},
            session=session,
            ai=unavailable_ai(),
            options=_master_options(),
            persist=False,
        )

        assert result.artifacts["persisted"] is False
        assert result.artifacts["recommendations"]
        assert _recommendations_of(session, RecommendationKind.PUBLISH) == []

    def test_ai_prioritizes_without_creating_recommendations(self, session, source_record) -> None:
        """A IA ordena e redige; não cria recomendação nem altera score."""
        from agents.master.agent import run

        _portfolio_item(session, source_record, PortfolioState.READY_TO_PUBLISH)
        ai, provider = fake_ai(
            {"what_is_working": ["publicação pronta"], "what_is_not": [], "priority_actions": []}
        )
        result = run({}, session=session, ai=ai, options=_master_options())

        assert result.artifacts["diagnosis"]["what_is_working"] == ["publicação pronta"]
        record = session.scalars(select(AIInterpretation)).one()
        assert record.agent == "master"

        # As recomendações continuam vindo da regra, com justificativa própria.
        for item in result.artifacts["recommendations"]:
            assert item["rationale"]


def _recommendations_of(session, kind: RecommendationKind) -> list[Recommendation]:
    """Recomendações de um tipo.

    O Master também cria recomendações sobre jobs parados, e isso é correto — mas
    torna os testes de produto ruidosos. Filtrar por tipo mantém cada teste focado
    no que ele verifica, sem depender do estado do pipeline.
    """
    return list(session.scalars(select(Recommendation).where(Recommendation.kind == kind)))


def _master_options():
    from agents.master.agent import MasterOptions

    return MasterOptions()


def _portfolio_item(session, source_record, state: PortfolioState) -> PortfolioItem:
    product = Product(
        marketplace=Marketplace.MERCADO_LIVRE,
        external_id=f"MLB-{state.value}",
        title=f"Produto {state.value}",
        price=99.9,
        source_record_id=source_record.id,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    session.add(product)
    session.flush()

    item = PortfolioItem(
        product_id=product.id,
        marketplace=Marketplace.MERCADO_LIVRE,
        label=product.title,
        state=state,
        state_changed_at=NOW,
    )
    session.add(item)
    session.commit()
    return item
