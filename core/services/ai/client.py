"""Camada de IA dos agentes.

Regra que orienta este módulo (briefing seção 5): *"Nenhuma pontuação crítica poderá
existir apenas como opinião opaca de um modelo de IA."*

A consequência prática é uma separação de responsabilidades:

* **A IA interpreta e redige.** Ela lê dados estruturados e produz avaliações
  qualitativas, hipóteses e textos — coisas em que um modelo é genuinamente melhor
  que uma fórmula.
* **A IA não define score.** Os scores vêm do motor versionado em
  `core/services/scoring/`, que persiste inputs, pesos, fórmula e versão. Um número
  produzido por LLM não seria reproduzível nem auditável, e não entraria nessa
  estrutura.

Toda saída de IA fica registrada com o modelo usado, o prompt, os insumos e a
resposta bruta, para que a decisão continue auditável depois.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class AIError(RuntimeError):
    """Falha ao falar com o provedor de IA."""


class AINotConfigured(AIError):
    """IA desligada ou sem credencial.

    Não é um erro fatal: o sistema precisa funcionar de forma determinística sem
    LLM. Quem chama decide o que fazer — o padrão é degradar, não quebrar.
    """


@dataclass
class AIMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class AIResponse:
    """Resposta do modelo com o que é preciso para auditar depois."""

    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None

    def as_json(self) -> dict[str, Any]:
        """Converte a resposta em objeto, tolerando cercas de código markdown."""
        text = self.text.strip()
        if text.startswith("```"):
            # Modelos frequentemente embrulham JSON em ```json ... ```
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except ValueError as exc:
            raise AIError(f"resposta não é JSON válido: {text[:200]}") from exc


class AIProvider(Protocol):
    """Provedor de modelo. Existe para permitir dublê em teste."""

    def complete(self, messages: list[AIMessage], *, temperature: float = 0.2) -> AIResponse: ...


@dataclass
class OpenAIChatProvider:
    """Provedor OpenAI-compatível (OpenAI, Azure, vLLM, Ollama, DeepSeek…)."""

    api_key: str
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout: float = 60.0
    max_retries: int = 2
    _client: Any = field(default=None, repr=False)

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise AIError(
                "pacote `openai` não instalado. Rode `pip install -r requirements.txt`."
            ) from exc
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        return self._client

    def complete(self, messages: list[AIMessage], *, temperature: float = 0.2) -> AIResponse:
        client = self._ensure_client()
        payload = [{"role": message.role, "content": message.content} for message in messages]

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                completion = client.chat.completions.create(
                    model=self.model,
                    messages=payload,
                    temperature=temperature,
                )
            except Exception as exc:  # noqa: BLE001 - SDK tem hierarquia própria
                last_error = exc
                logger.warning("tentativa %d de IA falhou: %s", attempt + 1, exc)
                continue

            choice = completion.choices[0]
            usage = getattr(completion, "usage", None)
            return AIResponse(
                text=choice.message.content or "",
                model=getattr(completion, "model", self.model),
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                finish_reason=getattr(choice, "finish_reason", None),
                raw=completion.model_dump() if hasattr(completion, "model_dump") else None,
            )

        raise AIError(f"provedor de IA falhou após {self.max_retries + 1} tentativas: {last_error}")


@dataclass
class AIClient:
    """Fachada usada pelos agentes."""

    provider: AIProvider | None = None
    settings: Settings | None = None

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = get_settings()

    @property
    def is_available(self) -> bool:
        if self.provider is not None:
            return True
        return bool(self.settings and self.settings.is_ai_configured)

    def _resolve_provider(self) -> AIProvider:
        if self.provider is not None:
            return self.provider
        settings = self.settings
        assert settings is not None
        if not settings.is_ai_configured:
            raise AINotConfigured(
                "IA desligada ou sem chave. Defina AI_ENABLED=true e AI_API_KEY no .env. "
                "O sistema funciona sem IA, de forma determinística."
            )
        return OpenAIChatProvider(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            model=settings.ai_model,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    def complete(self, messages: list[AIMessage], *, temperature: float = 0.2) -> AIResponse:
        return self._resolve_provider().complete(messages, temperature=temperature)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Pede uma resposta JSON. O prompt precisa declarar o formato."""
        response = self.complete(
            [AIMessage("system", system), AIMessage("user", user)],
            temperature=temperature,
        )
        return response.as_json()


def build_ai_client(provider: AIProvider | None = None) -> AIClient:
    """Constrói o cliente. Em teste, passe um `provider` dublê."""
    return AIClient(provider=provider)


__all__ = [
    "AIClient",
    "AIError",
    "AIMessage",
    "AINotConfigured",
    "AIProvider",
    "AIResponse",
    "OpenAIChatProvider",
    "build_ai_client",
]
