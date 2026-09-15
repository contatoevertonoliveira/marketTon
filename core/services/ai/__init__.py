"""Camada de IA: interpretação auditável sobre dados já calculados.

O que a IA faz aqui: interpreta, prioriza e redige. O que ela **não** faz: definir
score. Os scores vêm de `core/services/scoring/`, versionados e explicáveis, porque
o briefing seção 5 exige que nenhuma pontuação crítica seja opinião opaca de modelo.
"""
from __future__ import annotations

from core.services.ai.client import (
    AIClient,
    AIError,
    AIMessage,
    AINotConfigured,
    AIProvider,
    AIResponse,
    OpenAIChatProvider,
    build_ai_client,
)
from core.services.ai.interpreter import InterpretationResult, run_interpretation
from core.services.ai.prompts import PromptTemplate, get_prompt

__all__ = [
    "AIClient",
    "AIError",
    "AIMessage",
    "AINotConfigured",
    "AIProvider",
    "AIResponse",
    "InterpretationResult",
    "OpenAIChatProvider",
    "PromptTemplate",
    "build_ai_client",
    "get_prompt",
    "run_interpretation",
]
