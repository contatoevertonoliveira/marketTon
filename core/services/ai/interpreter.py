"""Execução de interpretações de IA com registro auditável.

Separa duas responsabilidades:

* montar o pedido e registrar o resultado (`run_interpretation`);
* *o que* perguntar, que fica com cada agente.

Se a IA estiver desligada, a função devolve `None` em vez de levantar exceção. O
sistema foi desenhado para operar de forma determinística sem LLM — a IA é
enriquecimento, não dependência. Quem chama trata o `None` como "sem interpretação
disponível", e o registro sai com o motivo.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from core.db.ai import AIInterpretation, AIInterpretationKind
from core.services.ai.client import AIClient, AIError, AINotConfigured
from core.services.ai.prompts import PromptTemplate

logger = logging.getLogger(__name__)


@dataclass
class InterpretationResult:
    """Resultado de uma tentativa de interpretação."""

    ok: bool
    output: dict[str, Any] | None = None
    interpretation_id: int | None = None
    skipped_reason: str | None = None
    error: str | None = None


def _hash_inputs(inputs: dict[str, Any]) -> str:
    payload = json.dumps(inputs, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_interpretation(
    session: Session,
    *,
    ai: AIClient,
    agent: str,
    kind: AIInterpretationKind,
    prompt: PromptTemplate,
    inputs: dict[str, Any],
    user_content: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    job_id: int | None = None,
    temperature: float = 0.1,
) -> InterpretationResult:
    """Executa a interpretação e grava o registro — inclusive quando falha.

    Registrar a falha importa: sem isso, "o agente não trouxe análise" seria
    indistinguível de "a análise não foi pedida".
    """
    inputs_hash = _hash_inputs(inputs)

    if not ai.is_available:
        return InterpretationResult(
            ok=False,
            skipped_reason="IA desligada ou sem credencial (AI_ENABLED / AI_API_KEY)",
        )

    user = user_content or (
        f"Dados para análise:\n\n```json\n{json.dumps(inputs, indent=2, default=str, ensure_ascii=False)}\n```\n\n"
        f"Formato de saída exigido:\n\n```json\n{prompt.output_format}\n```"
    )

    record = AIInterpretation(
        agent=agent,
        kind=kind,
        prompt_key=prompt.key,
        prompt_version=prompt.version,
        model=getattr(getattr(ai, "settings", None), "ai_model", "unknown"),
        inputs=inputs,
        inputs_hash=inputs_hash,
        target_type=target_type,
        target_id=target_id,
        job_id=job_id,
    )

    started = time.monotonic()
    try:
        response = ai.complete(
            [
                # Import local evita ciclo: `client` importa `config`, não `prompts`.
                _system_message(prompt),
                _user_message(user),
            ],
            temperature=temperature,
        )
    except AINotConfigured as exc:
        return InterpretationResult(ok=False, skipped_reason=str(exc))
    except AIError as exc:
        record.parse_ok = False
        record.error_message = str(exc)
        record.latency_seconds = round(time.monotonic() - started, 3)
        session.add(record)
        session.flush()
        return InterpretationResult(ok=False, interpretation_id=record.id, error=str(exc))

    record.latency_seconds = round(time.monotonic() - started, 3)
    record.raw_text = response.text
    record.model = response.model
    record.prompt_tokens = response.prompt_tokens
    record.completion_tokens = response.completion_tokens

    try:
        record.output = response.as_json()
        record.parse_ok = True
    except AIError as exc:
        # O modelo respondeu, mas não no formato pedido. A resposta bruta fica
        # gravada: é ela que permite entender o que aconteceu.
        record.parse_ok = False
        record.error_message = str(exc)

    session.add(record)
    session.flush()

    return InterpretationResult(
        ok=record.parse_ok,
        output=record.output,
        interpretation_id=record.id,
        error=None if record.parse_ok else record.error_message,
    )


def _system_message(prompt: PromptTemplate):
    from core.services.ai.client import AIMessage

    return AIMessage("system", prompt.render_system())


def _user_message(content: str):
    from core.services.ai.client import AIMessage

    return AIMessage("user", content)


__all__ = ["InterpretationResult", "run_interpretation"]
