"""Testes do motor de scoring (briefing seções 5 e 6).

O teste central é `test_impacts_sum_to_the_score`: se a soma dos impactos das
contribuições não reconstruir o score final, a explicação deixou de ser auditável
e passou a ser narrativa — que é precisamente o que o briefing proíbe.
"""
from __future__ import annotations

import pytest

from core.services.scoring import engine
from core.services.scoring.engine import (
    AlgorithmSpec,
    active_spec,
    compute,
    get_spec,
    growth,
    load_specs,
    normalize,
    register,
    saturate,
)

load_specs()

DIMENSIONS = ["HEAT", "OPPORTUNITY", "PRODUCER_MOMENTUM", "CREATIVE_SATURATION"]

# Tolerância da soma dos impactos: cada contribuição é arredondada a 3 casas.
IMPACT_TOLERANCE = 0.01


def _full_inputs() -> dict:
    """Insumos completos, todos os fatores disponíveis."""
    return {
        # Heat
        "sold_last_period": 1200,
        "sold_previous_period": 900,
        "new_reviews_period": 300,
        "rating": 4.7,
        "available_quantity": 80,
        # Opportunity
        "affiliate_commission_pct": 12.0,
        "price": 150.0,
        "heat_score": 78.0,
        "producer_momentum_score": 65.0,
        "creative_saturation_score": 30.0,
        "competing_ads_count": 8,
        # Producer momentum
        "seller_total_sales": 25000,
        "seller_active_listings": 300,
        "seller_active_listings_previous": 250,
        "seller_reputation_level": "5_green",
        "seller_positive_rating_pct": 97.0,
        "seller_active_promotions": 6,
        "seller_response_rate_pct": 92.0,
        # Creative saturation
        "active_ads_count": 40,
        "distinct_advertisers": 12,
        "median_ad_age_days": 45,
        "homogeneous_offer_pct": 55.0,
    }


class TestHelpers:
    def test_normalize_higher_is_better(self) -> None:
        assert normalize(10.0, best=10.0, worst=0.0) == 1.0
        assert normalize(0.0, best=10.0, worst=0.0) == 0.0
        assert normalize(5.0, best=10.0, worst=0.0) == pytest.approx(0.5)

    def test_normalize_lower_is_better(self) -> None:
        """Passar best < worst inverte a orientação: menor valor vale mais."""
        assert normalize(0.0, best=0.0, worst=100.0) == 1.0
        assert normalize(100.0, best=0.0, worst=100.0) == 0.0

    def test_normalize_clamps_out_of_range(self) -> None:
        assert normalize(999.0, best=10.0, worst=0.0) == 1.0
        assert normalize(-999.0, best=10.0, worst=0.0) == 0.0

    def test_normalize_returns_none_for_missing_value(self) -> None:
        """Ausência de dado não pode virar zero: vira ausência."""
        assert normalize(None, best=10.0, worst=0.0) is None

    def test_normalize_handles_degenerate_range(self) -> None:
        assert normalize(5.0, best=5.0, worst=5.0) == 1.0

    def test_saturate_has_diminishing_returns(self) -> None:
        low = saturate(100, ceiling=5000)
        high = saturate(4000, ceiling=5000)
        assert low < high
        # Dobrar um valor grande muda pouco; dobrar um valor pequeno muda muito.
        assert (saturate(200, ceiling=5000) - low) > (saturate(8000, ceiling=5000) - high)

    def test_saturate_bounds(self) -> None:
        assert saturate(0, ceiling=100) == 0.0
        assert saturate(100, ceiling=100) == 1.0
        assert saturate(1000, ceiling=100) == 1.0

    def test_growth_flat_band_is_neutral(self) -> None:
        """Ruído de medição não pode ser lido como tendência."""
        assert growth(102, 100) == 0.5
        assert growth(98, 100) == 0.5

    def test_growth_direction(self) -> None:
        assert growth(150, 100) > 0.5
        assert growth(50, 100) < 0.5
        assert growth(200, 100) == pytest.approx(1.0)

    def test_growth_undefined_without_base(self) -> None:
        """Crescimento a partir de zero é indefinido, não infinito."""
        assert growth(10, 0) is None
        assert growth(None, 100) is None
        assert growth(100, None) is None


class TestRegistry:
    def test_all_four_dimensions_registered(self) -> None:
        assert {spec.dimension for spec in engine.all_specs()} == set(DIMENSIONS)

    def test_get_spec_by_version(self) -> None:
        spec = get_spec("OPPORTUNITY", "v1")
        assert spec.algorithm_key == "opportunity.v1"

    def test_get_spec_unknown_version_is_explicit(self) -> None:
        with pytest.raises(KeyError, match="não registrado"):
            get_spec("OPPORTUNITY", "v99")

    def test_active_spec_orders_versions_numerically(self) -> None:
        """"v10" precisa ser mais nova que "v2" — comparação de string erraria."""
        assert active_spec("HEAT").version == "v1"

    def test_weights_are_declared_for_every_factor(self) -> None:
        """Fator sem peso declarado nunca contribuiria e sumiria em silêncio."""
        for spec in engine.all_specs():
            assert set(spec.weights) == set(spec.functions), (
                f"{spec.dimension}: pesos e funções divergem"
            )

    def test_every_factor_has_a_label(self) -> None:
        for spec in engine.all_specs():
            for factor in spec.functions:
                assert factor in spec.labels, f"{spec.dimension}.{factor} sem label"

    def test_duplicate_registration_is_rejected(self) -> None:
        spec = get_spec("HEAT", "v1")
        with pytest.raises(ValueError, match="já registrado"):
            register(spec)


class TestCompute:
    @pytest.mark.parametrize("dimension", DIMENSIONS)
    def test_impacts_sum_to_the_score(self, dimension: str) -> None:
        """O TESTE CENTRAL: a explicação reconstrói o score.

        Se isto falhar, a explicação virou narrativa independente do cálculo e o
        briefing seção 6 deixa de ser atendido de verdade.
        """
        spec = active_spec(dimension)
        result = compute(spec, _full_inputs())

        total_impact = sum(c.impact for c in result.contributions)
        assert total_impact == pytest.approx(result.score, abs=IMPACT_TOLERANCE), (
            f"{dimension}: soma dos impactos ({total_impact}) != score ({result.score})"
        )

    @pytest.mark.parametrize("dimension", DIMENSIONS)
    def test_score_stays_in_range(self, dimension: str) -> None:
        spec = active_spec(dimension)
        result = compute(spec, _full_inputs())
        assert 0.0 <= result.score <= 100.0

    @pytest.mark.parametrize("dimension", DIMENSIONS)
    def test_complete_inputs_yield_full_confidence(self, dimension: str) -> None:
        spec = active_spec(dimension)
        result = compute(spec, _full_inputs())
        assert result.is_complete, f"{dimension} deveria estar completo"
        assert result.confidence == pytest.approx(1.0)
        assert result.status == "SUCCEEDED"

    @pytest.mark.parametrize("dimension", DIMENSIONS)
    def test_missing_factor_reduces_confidence_without_zeroing(self, dimension: str) -> None:
        """Briefing seção 2: "não sabemos" não é "é ruim".

        O insumo é removido pela chave declarada em `input_keys`, que é o
        contrato que liga um fator ao dado que o alimenta e permite ao motor
        detectar a ausência.
        """
        spec = active_spec(dimension)
        full = compute(spec, _full_inputs())

        # Remove TODOS os insumos de um fator escolhido. Remove também as chaves
        # de contexto temporal que alimentam `growth`, para que a ausência seja
        # inequívoca e não dependa de qual função lê o quê.
        factor = "rating" if dimension == "HEAT" else next(iter(spec.input_keys))
        input_key = spec.input_keys[factor]
        drop = {input_key, f"{input_key}_previous"}

        partial_inputs = {k: v for k, v in _full_inputs().items() if k not in drop}
        partial = compute(spec, partial_inputs)

        assert partial.confidence < full.confidence, (
            f"{dimension}: remover '{input_key}' deveria reduzir a confiança"
        )
        assert partial.status == "INSUFFICIENT_DATA"
        assert factor in partial.insufficient_reasons
        # O score não pode colapsar: os fatores disponíveis continuam valendo.
        assert partial.score > 0.0

        missing = [c for c in partial.contributions if c.factor == factor][0]
        assert not missing.available
        assert missing.impact == 0.0
        assert "indisponível" in (missing.explanation or "")

    def test_no_inputs_at_all_is_insufficient_not_failed(self) -> None:
        """Sem insumo nenhum o algoritmo rodou: é INSUFFICIENT_DATA, não FAILED.

        A distinção importa para o operador: `FAILED` sugere defeito no motor,
        enquanto `INSUFFICIENT_DATA` diz que falta coletar dado. Com `confidence`
        0 e todos os fatores marcados indisponíveis, o score não é utilizável —
        mas a causa fica explícita.
        """
        for dimension in DIMENSIONS:
            result = compute(active_spec(dimension), {})
            assert result.status == "INSUFFICIENT_DATA", f"{dimension} deveria ser INSUFFICIENT_DATA"
            assert result.confidence == 0.0
            assert result.is_complete is False
            assert result.insufficient_reasons
            assert result.contributions, "os fatores precisam existir, marcados como indisponíveis"
            assert all(not c.available for c in result.contributions)
            assert result.explain() == [], "sem dado não há motivo a exibir"

    def test_algorithm_without_factors_fails_explicitly(self) -> None:
        """Um algoritmo sem fórmula é defeito de implementação, não falta de dado."""
        spec = AlgorithmSpec(
            dimension="BROKEN",
            version="v1",
            name="Sem fatores",
            algorithm_key="broken.v1",
            weights={},
            functions={},
            labels={},
        )
        result = compute(spec, {})
        assert result.status == "FAILED"
        assert result.contributions == []

    def test_explain_lists_reasons_with_signs(self) -> None:
        """Formato do briefing seção 6: "+ motivo" / "- motivo"."""
        result = compute(active_spec("OPPORTUNITY"), _full_inputs())
        lines = result.explain()
        assert lines, "a explicação não pode ser vazia"
        assert all(line.startswith(("+ ", "- ")) for line in lines)

    def test_explain_skips_unavailable_factors(self) -> None:
        spec = active_spec("HEAT")
        result = compute(spec, {"rating": 4.5})
        lines = result.explain()
        # Só `rating` está disponível.
        assert len(lines) == 1
        assert "nota 4.5 de 5" in lines[0]

    def test_inverted_factor_direction_is_honest(self) -> None:
        """Saturação alta é ruim, na aritmética E no sinal exibido.

        Este é o bug que a arquitetura precisa impedir: quando a inversão era
        feita dentro da função do fator, o texto da explicação podia contradizer
        o score. Aqui o score do índice SOBE com a saturação (maior = pior, e o
        spec declara `higher_score_is_better=False`), e o fator aparece como
        desfavorável — as duas coisas coerentes.
        """
        spec = active_spec("CREATIVE_SATURATION")
        assert spec.higher_score_is_better is False

        low_saturation = compute(
            spec,
            {
                "active_ads_count": 2,
                "distinct_advertisers": 1,
                "median_ad_age_days": 3,
                "homogeneous_offer_pct": 5.0,
            },
        )
        high_saturation = compute(
            spec,
            {
                "active_ads_count": 190,
                "distinct_advertisers": 48,
                "median_ad_age_days": 175,
                "homogeneous_offer_pct": 95.0,
            },
        )

        assert high_saturation.score > low_saturation.score, "mais saturação = índice maior"

        volume = [c for c in high_saturation.contributions if c.factor == "ad_volume"][0]
        assert volume.is_positive is False, "volume alto deve ser exibido como desfavorável"

        quiet = [c for c in low_saturation.contributions if c.factor == "ad_volume"][0]
        assert quiet.is_positive is True, "volume baixo deve ser exibido como favorável"

    def test_score_of_saturation_drives_opportunity_negatively(self) -> None:
        """O índice de saturação entra no Opportunity como espaço livre.

        Fecha o laço entre as duas dimensões: saturação alta precisa reduzir a
        oportunidade, e não aumentá-la.
        """
        opportunity = active_spec("OPPORTUNITY")
        base = _full_inputs()
        assert opportunity.higher_score_is_better is True

        saturated = compute(opportunity, {**base, "creative_saturation_score": 95.0})
        free = compute(opportunity, {**base, "creative_saturation_score": 5.0})
        assert free.score > saturated.score

    def test_opportunity_rewards_commission_and_headroom(self) -> None:
        spec = active_spec("OPPORTUNITY")
        base = _full_inputs()

        good = compute(spec, {**base, "affiliate_commission_pct": 25.0, "creative_saturation_score": 10.0})
        bad = compute(spec, {**base, "affiliate_commission_pct": 2.0, "creative_saturation_score": 90.0})
        assert good.score > bad.score

    def test_formatters_produce_human_text(self) -> None:
        """A explicação é para o operador, não para o log."""
        result = compute(active_spec("HEAT"), _full_inputs())
        by_factor = {c.factor: c for c in result.contributions}
        assert "nota 4.7 de 5" == by_factor["rating"].explanation
        assert "unidades vendidas" in (by_factor["sales_velocity"].explanation or "")


class TestCustomSpec:
    def test_single_factor_matches_normalized_value(self) -> None:
        """Com um único fator e peso 1, o score é a própria normalização."""
        spec = AlgorithmSpec(
            dimension="TEST",
            version="v1",
            name="Teste",
            algorithm_key="test.v1",
            weights={"only": 1.0},
            functions={"only": lambda inputs: 0.5},
            labels={"only": "único fator"},
            parameters={"gamma": 1.0},
        )
        result = compute(spec, {})
        assert result.score == pytest.approx(50.0)
        assert result.contributions[0].impact == pytest.approx(50.0)

    def test_gamma_penalises_inconsistency(self) -> None:
        """Um produto excepcional em um fator e péssimo em outro perde para o consistente.

        Este é o motivo de existir a raiz de compressão: sem ela, a média
        ponderada premiaria extremos isolados.
        """
        base = dict(
            dimension="TEST",
            version="v1",
            name="Teste",
            algorithm_key="test.v1",
            weights={"a": 0.5, "b": 0.5},
            labels={"a": "A", "b": "B"},
            parameters={"gamma": 0.6},
        )
        spec = AlgorithmSpec(
            **base,
            functions={"a": lambda i: i["a"], "b": lambda i: i["b"]},
        )
        consistent = compute(spec, {"a": 0.6, "b": 0.6})
        spiky = compute(spec, {"a": 1.0, "b": 0.2})

        assert consistent.score > spiky.score, "consistência deve vencer o extremo isolado"
