"""Testes da camada de IA.

Usa um provedor dublê: nenhuma chamada real a LLM, nenhum custo, resultado
determinístico.

O que estes testes protegem:

1. **A IA não é dependência.** Com ela desligada o sistema funciona, e a ausência
   fica registrada com o motivo — não como falha silenciosa.
2. **Toda saída é auditável.** Modelo, versão de prompt, insumos e resposta bruta
   ficam gravados. É o que permite responder "por que o sistema recomendou isso?"
   quando um modelo participou da decisão.
3. **Falha do modelo não derruba o pipeline.** Resposta malformada é registrada
   como `parse_ok=False`, com o texto bruto preservado.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from core.db.ai import AIInterpretation, AIInterpretationKind
from core.services.ai.client import AIClient, AIError, AIMessage, AIResponse
from core.services.ai.interpreter import run_interpretation
from core.services.ai.prompts import (
    GROUND_RULES,
    PRODUCT_EVALUATOR,
    REGISTRY,
    get_prompt,
)


class FakeProvider:
    """Provedor dublê que devolve o texto configurado e registra as chamadas."""

    def __init__(self, text: str = "{}", model: str = "fake-model"):
        self.text = text
        self.model = model
        self.calls: list[list[AIMessage]] = []
        self.temperatures: list[float] = []

    def complete(self, messages: list[AIMessage], *, temperature: float = 0.2) -> AIResponse:
        self.calls.append(messages)
        self.temperatures.append(temperature)
        return AIResponse(
            text=self.text,
            model=self.model,
            prompt_tokens=100,
            completion_tokens=50,
            finish_reason="stop",
        )


class FailingProvider:
    def complete(self, messages: list[AIMessage], *, temperature: float = 0.2) -> AIResponse:
        raise AIError("provedor indisponível")


@pytest.fixture
def fake_ai() -> tuple[AIClient, FakeProvider]:
    provider = FakeProvider(text=json.dumps({"verdict": "promising", "reasons_for": ["comissão 18%"]}))
    return AIClient(provider=provider), provider


class TestPrompts:
    def test_every_prompt_forbids_inventing_numbers(self) -> None:
        """A regra central da camada: o modelo interpreta, não estima."""
        for key, template in REGISTRY.items():
            system = template.render_system()
            assert "Não estime" in system or "não estime" in system, f"{key} sem regra de estimativa"
            assert "Não produza pontuações numéricas" in system, f"{key} pode inventar score"

    def test_ground_rules_require_declaring_missing_data(self) -> None:
        assert "não estiver presente" in GROUND_RULES
        assert "Não preencha a lacuna" in GROUND_RULES

    def test_every_prompt_declares_an_output_format(self) -> None:
        for key, template in REGISTRY.items():
            assert template.output_format, f"{key} sem formato de saída"
            assert template.version, f"{key} sem versão"

    def test_prompts_are_versioned(self) -> None:
        """Mudar um prompt muda o comportamento; precisa ser rastreável."""
        assert all(template.version.startswith("v") for template in REGISTRY.values())

    def test_unknown_prompt_raises_with_the_available_list(self) -> None:
        with pytest.raises(KeyError, match="não registrado"):
            get_prompt("nao_existe")

    def test_product_evaluator_tells_the_model_scores_are_already_computed(self) -> None:
        """Evita que o modelo recalcule ou contradiga o motor de scoring."""
        system = PRODUCT_EVALUATOR.render_system()
        assert "já foram calculados" in system
        assert "não os recalcule" in system


class TestAIClient:
    def test_disabled_when_not_configured(self) -> None:
        client = AIClient(provider=None)
        # Sem provider e com settings padrão (AI_ENABLED=false), não está disponível.
        assert client.is_available is False

    def test_available_with_injected_provider(self, fake_ai) -> None:
        client, _ = fake_ai
        assert client.is_available is True

    def test_strips_markdown_code_fences(self, fake_ai) -> None:
        """Modelos embrulham JSON em ```json; isso não pode quebrar o parse."""
        _, provider = fake_ai
        provider.text = '```json\n{"ok": true}\n```'
        client, _ = fake_ai
        assert client.complete_json(system="s", user="u") == {"ok": True}

    def test_invalid_json_raises_with_context(self, fake_ai) -> None:
        _, provider = fake_ai
        provider.text = "isto não é json"
        client, _ = fake_ai
        with pytest.raises(AIError, match="não é JSON válido"):
            client.complete_json(system="s", user="u")

    def test_system_prompt_is_sent_with_the_ground_rules(self, fake_ai) -> None:
        client, provider = fake_ai
        run_interpretation(
            session=_SessionStub(),
            ai=client,
            agent="test",
            kind=AIInterpretationKind.PRODUCT_EVALUATION,
            prompt=PRODUCT_EVALUATOR,
            inputs={"price": 1},
        )
        system_message = provider.calls[0][0]
        assert system_message.role == "system"
        assert "Não estime" in system_message.content


class _SessionStub:
    """Sessão mínima para testar o interpreter sem banco."""

    def __init__(self):
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        for index, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = index


class TestInterpretationRecording:
    def test_records_everything_needed_to_audit(self, session) -> None:
        provider = FakeProvider(text=json.dumps({"verdict": "uncertain"}))
        client = AIClient(provider=provider)

        result = run_interpretation(
            session=session,
            ai=client,
            agent="product_hunter",
            kind=AIInterpretationKind.PRODUCT_EVALUATION,
            prompt=PRODUCT_EVALUATOR,
            inputs={"price": 99.9, "commission_pct": 12},
            target_type="product",
            target_id=42,
        )

        assert result.ok is True
        assert result.output == {"verdict": "uncertain"}

        record = session.scalar(select(AIInterpretation))
        assert record.agent == "product_hunter"
        assert record.kind == AIInterpretationKind.PRODUCT_EVALUATION
        assert record.prompt_key == PRODUCT_EVALUATOR.key
        assert record.prompt_version == PRODUCT_EVALUATOR.version
        assert record.model == "fake-model"
        assert record.inputs == {"price": 99.9, "commission_pct": 12}
        assert record.inputs_hash
        assert record.raw_text
        assert record.parse_ok is True
        assert record.prompt_tokens == 100
        assert record.completion_tokens == 50
        assert record.target_type == "product"
        assert record.target_id == 42

    def test_skipped_when_ai_is_disabled(self, session) -> None:
        """Sem IA o sistema segue; a ausência é declarada, não silenciosa."""
        result = run_interpretation(
            session=session,
            ai=AIClient(provider=None),
            agent="product_hunter",
            kind=AIInterpretationKind.PRODUCT_EVALUATION,
            prompt=PRODUCT_EVALUATOR,
            inputs={"price": 1},
        )

        assert result.ok is False
        assert result.skipped_reason
        assert "IA desligada" in result.skipped_reason
        # E nada é gravado: não houve chamada.
        assert session.scalars(select(AIInterpretation)).all() == []

    def test_malformed_response_is_recorded_with_raw_text(self, session) -> None:
        """A resposta bruta é o que permite entender o que o modelo fez."""
        provider = FakeProvider(text="Desculpe, não posso ajudar com isso.")
        client = AIClient(provider=provider)

        result = run_interpretation(
            session=session,
            ai=client,
            agent="product_hunter",
            kind=AIInterpretationKind.PRODUCT_EVALUATION,
            prompt=PRODUCT_EVALUATOR,
            inputs={"price": 1},
        )

        assert result.ok is False
        assert result.error

        record = session.scalar(select(AIInterpretation))
        assert record.parse_ok is False
        assert record.raw_text == "Desculpe, não posso ajudar com isso."
        assert record.output is None
        assert record.error_message

    def test_provider_failure_is_recorded_not_raised(self, session) -> None:
        """Um provedor fora do ar não pode derrubar o pipeline inteiro."""
        result = run_interpretation(
            session=session,
            ai=AIClient(provider=FailingProvider()),
            agent="product_hunter",
            kind=AIInterpretationKind.PRODUCT_EVALUATION,
            prompt=PRODUCT_EVALUATOR,
            inputs={"price": 1},
        )

        assert result.ok is False
        assert "indisponível" in (result.error or "")

        record = session.scalar(select(AIInterpretation))
        assert record.parse_ok is False
        assert "indisponível" in (record.error_message or "")

    def test_inputs_hash_is_stable_and_order_independent(self, session) -> None:
        """O hash detecta insumo idêntico mesmo com ordem diferente de chaves."""
        provider = FakeProvider(text="{}")
        client = AIClient(provider=provider)

        for payload in ({"a": 1, "b": 2}, {"b": 2, "a": 1}):
            run_interpretation(
                session=session,
                ai=client,
                agent="test",
                kind=AIInterpretationKind.PERFORMANCE_DIAGNOSIS,
                prompt=get_prompt("performance_diagnosis"),
                inputs=payload,
            )

        hashes = {record.inputs_hash for record in session.scalars(select(AIInterpretation)).all()}
        assert len(hashes) == 1

    def test_custom_user_content_is_respected(self, session) -> None:
        provider = FakeProvider(text="{}")
        client = AIClient(provider=provider)

        run_interpretation(
            session=session,
            ai=client,
            agent="test",
            kind=AIInterpretationKind.CREATIVE_BRIEF,
            prompt=get_prompt("creative_brief"),
            inputs={"product": "Fone"},
            user_content="Produza o briefing para o produto Fone.",
        )

        user_message = provider.calls[0][1]
        assert user_message.role == "user"
        assert user_message.content == "Produza o briefing para o produto Fone."
