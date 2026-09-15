"""Motor de avaliação de scores: contrato, registro de algoritmos e persistência.

Todo algoritmo declara sua contribuição fator a fator, e a soma documentada das
contribuições reconstrói o score final. É isso que satisfaz as seções 5 e 6 do
briefing simultaneamente: o score é versionado e auditável, e a explicação não é
uma narrativa gerada à parte — é a própria aritmética do cálculo.

Desenho da fórmula (idêntico em todas as dimensões, para que scores sejam
comparáveis entre si):

    1. Cada fator é normalizado para 0..1 (`normalize`), onde 1 é sempre a
       situação mais favorável para a operação.
    2. Aplica-se uma raiz de compressão: `adjust(n) = n ** gamma`, com
       gamma < 1. Isso penaliza a inconsistência — um produto excepcional em um
       fator e péssimo em outro pontua menos que um produto bom em todos.
    3. O score é a soma ponderada, reescalada para 0..100.

Fator sem dado disponível não vira zero: ele é marcado `available=False`, sai do
denominador e reduz a `confidence`. É a diferença entre "não sabemos" e "é ruim".
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import Marketplace
from core.db.scoring import ScoreAlgorithm, ScoreContribution, ScoreRun

# Raiz de compressão aplicada a cada fator normalizado.
DEFAULT_GAMMA = 0.6
# Abaixo disto o resultado é considerado não confiável o bastante para decidir.
DEFAULT_MIN_CONFIDENCE = 0.5


@dataclass(frozen=True)
class AlgorithmSpec:
    """Registro imutável de uma versão de algoritmo.

    Publicar uma mudança de pesos ou de fórmula significa declarar uma nova
    `version`. É este contrato que permite ao motor de aprendizado comparar a
    previsão de uma versão com o resultado que ela de fato produziu.
    """

    dimension: str
    version: str
    name: str
    algorithm_key: str
    weights: dict[str, float]
    functions: dict[str, Callable[[dict[str, Any]], float | None]]
    labels: dict[str, str]
    units: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str | None = None
    # Formata a explicação legível a partir do valor bruto ("+ forte crescimento").
    formatters: dict[str, Callable[[Any], str]] = field(default_factory=dict)
    # Direção de cada fator sobre o valor BRUTO: True = maior é melhor para nós.
    # A inversão dos fatores desfavoráveis é feita pelo motor, em um único lugar,
    # para que o sinal exibido e a normalização nunca divirjam.
    higher_is_better: dict[str, bool] = field(default_factory=dict)
    # Insumo bruto que representa cada fator. Declarar isto é o que permite:
    #   a) exibir o valor no texto da explicação, e
    #   b) saber que o dado faltou quando o insumo não veio.
    # Sem esta declaração, uma explicação cairia no rótulo genérico e a confiança
    # não reagiria à ausência de dado.
    input_keys: dict[str, str] = field(default_factory=dict)
    # Orientação do score final. Nem toda dimensão é "maior = melhor": a
    # saturação de mercado, por exemplo, é um índice em que maior é pior. Isto
    # fica explícito para que a UI nunca pinte um score alto de verde por engano.
    higher_score_is_better: bool = True

    def direction(self, factor: str) -> bool:
        return self.higher_is_better.get(factor, True)

    @property
    def gamma(self) -> float:
        return float(self.parameters.get("gamma", DEFAULT_GAMMA))

    @property
    def min_confidence(self) -> float:
        return float(self.parameters.get("min_confidence", DEFAULT_MIN_CONFIDENCE))

    def formula_text(self) -> str:
        terms = " + ".join(
            f"{weight:g}*{factor}^gamma" for factor, weight in self.weights.items()
        )
        return f"100 * ({terms}) / sum(weights disponíveis), gamma={self.gamma:g}"

    def inputs_hash(self, inputs: dict[str, Any]) -> str:
        """Hash estável dos insumos, para detectar recálculo idêntico."""
        payload = json.dumps(inputs, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class ContributionResult:
    """Resultado de um único fator, antes de virar linha de banco."""

    factor: str
    label: str
    # Sempre na convenção "1 = favorável", usada para o sinal da explicação.
    normalized: float | None
    impact: float = 0.0
    raw_value: float | None = None
    raw_unit: str | None = None
    weight: float | None = None
    available: bool = True
    is_positive: bool | None = None
    explanation: str | None = None
    # Valor efetivamente ponderado no score. Difere de `normalized` em dimensões
    # do tipo índice, onde o score sobe com o problema (`higher_score_is_better=False`).
    _weighted_value: float = 0.0


@dataclass
class ScoreResult:
    """Resultado completo e persistível de um cálculo."""

    dimension: str
    score: float
    contributions: list[ContributionResult]
    inputs: dict[str, Any]
    confidence: float
    is_complete: bool
    insufficient_reasons: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        """Situação do cálculo, com uma distinção que importa operacionalmente.

        * `FAILED` — não houve cálculo. Acontece quando o algoritmo não declara
          fator nenhum; não é falta de dado, é ausência de fórmula.
        * `INSUFFICIENT_DATA` — o cálculo rodou, mas faltou insumo. É o caso de um
          produto cuja fonte não expõe os campos necessários. Aqui o score existe e
          é reportado com `confidence` reduzida, porque `FAILED` sugeriria que o
          motor quebrou, e a ação do operador é diferente: falta coletar dado, não
          corrigir o algoritmo.
        """
        if not self.contributions:
            return "FAILED"
        if not self.is_complete:
            return "INSUFFICIENT_DATA"
        return "SUCCEEDED"

    def explain(self, limit: int | None = None) -> list[str]:
        """Explicação legível: o formato "+ motivo" / "- motivo" do briefing seção 6."""
        ordered = sorted(self.contributions, key=lambda c: abs(c.impact), reverse=True)
        if limit is not None:
            ordered = ordered[:limit]
        lines = []
        for contribution in ordered:
            if not contribution.available:
                continue
            sign = "+" if (contribution.is_positive is not False) else "-"
            text = contribution.explanation or contribution.label
            lines.append(f"{sign} {text}")
        return lines


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def normalize(value: float | None, *, best: float, worst: float) -> float | None:
    """Mapeia um valor bruto para 0..1, onde 1 é sempre o melhor para nós.

    `best` e `worst` são os extremos na direção favorável. Funciona para as duas
    orientações: se menor é melhor, basta passar `best < worst`.
    """
    if value is None:
        return None
    if math.isclose(best, worst):
        return 1.0
    return clamp((value - worst) / (best - worst))


def saturate(value: float | None, *, ceiling: float) -> float | None:
    """Normalização saturante de 0 até `ceiling`, com retorno decrescente.

    Adequada a sinais de demanda acumulada (vendas, número de avaliações):
    crescer de 0 para 100 importa muito mais do que de 1.000 para 1.100. O
    logaritmo captura isso; atingir `ceiling` significa saturação total.
    """
    if value is None:
        return None
    if ceiling <= 0:
        return 1.0
    return clamp(math.log1p(max(value, 0.0)) / math.log1p(ceiling))


def growth(
    current: float | None,
    previous: float | None,
    *,
    flat_band: float = 0.05,
    strong: float = 0.5,
) -> float | None:
    """Normaliza variação relativa entre duas medições.

    `flat_band` define a zona morta em torno de zero (ruído de medição não é
    tendência). `strong` é o crescimento que já vale normalizado 1,0.
    """
    if current is None or previous is None:
        return None
    if previous == 0:
        # Sem base de comparação: crescimento de zero é indefinido, não infinito.
        return None
    change = (current - previous) / abs(previous)
    if abs(change) <= flat_band:
        return 0.5
    if change > 0:
        excess = (change - flat_band) / max(strong - flat_band, 1e-9)
        return clamp(0.5 + 0.5 * excess)
    excess = (abs(change) - flat_band) / max(strong - flat_band, 1e-9)
    return clamp(0.5 - 0.5 * excess)


# --- Registro de algoritmos ---------------------------------------------------

_REGISTRY: dict[tuple[str, str], AlgorithmSpec] = {}


def register(spec: AlgorithmSpec) -> AlgorithmSpec:
    key = (spec.dimension, spec.version)
    if key in _REGISTRY:
        raise ValueError(f"algoritmo já registrado: {spec.dimension} v{spec.version}")
    _REGISTRY[key] = spec
    return spec


def get_spec(dimension: str, version: str) -> AlgorithmSpec:
    try:
        return _REGISTRY[(dimension, version)]
    except KeyError as exc:
        available = sorted(v for (dim, v) in _REGISTRY if dim == dimension)
        raise KeyError(
            f"algoritmo {dimension} v{version} não registrado. Versões disponíveis: {available}"
        ) from exc


def all_specs() -> list[AlgorithmSpec]:
    return list(_REGISTRY.values())


def active_spec(dimension: str) -> AlgorithmSpec:
    """Versão mais alta registrada para a dimensão (ordenação por versão)."""
    candidates = [spec for spec in _REGISTRY.values() if spec.dimension == dimension]
    if not candidates:
        raise KeyError(f"nenhum algoritmo registrado para a dimensão {dimension}")
    return max(candidates, key=lambda spec: _version_key(spec.version))


def _version_key(version: str) -> tuple:
    """Compara "v2" > "v10" corretamente comparando partes numéricas."""
    parts = []
    for chunk in version.replace("v", "").split("."):
        parts.append((0, int(chunk)) if chunk.isdigit() else (1, chunk))
    return tuple(parts)


def compute(spec: AlgorithmSpec, inputs: dict[str, Any]) -> ScoreResult:
    """Executa o cálculo declarado por `spec` sobre `inputs`.

    Função pura: não toca no banco. É o que torna o motor testável sem infra.

    Convenção de `inputs`: cada fator `f` pode ter `f` (o insumo usado pela
    função) e `f_raw` (o valor de exibição). Quando o spec declara
    `input_keys[f]`, o valor bruto é lido automaticamente dessa chave — é assim
    que a explicação mostra o número real em vez do rótulo genérico.
    """
    raw_values: dict[str, Any] = dict(inputs.get("_raw", {}))
    for factor, input_key in spec.input_keys.items():
        if factor not in raw_values and input_key in inputs:
            raw_values[factor] = inputs[input_key]

    contributions: list[ContributionResult] = []
    insufficient: list[str] = []

    for factor, function in spec.functions.items():
        label = spec.labels.get(factor, factor)
        weight = spec.weights.get(factor, 0.0)
        # A função devolve o valor BRUTO já na escala 0..1 (sem inversão).
        directional = function(inputs)

        if directional is None:
            contributions.append(
                ContributionResult(
                    factor=factor,
                    label=label,
                    normalized=None,
                    weight=weight,
                    available=False,
                    explanation=f"{label}: dado indisponível",
                )
            )
            insufficient.append(factor)
            continue

        # Inversão em um único ponto: se menor é melhor, `normalized = 1 - bruto`.
        # Assim a convenção "normalizado 1 = favorável" vale para todos os fatores
        # e o sinal da explicação acompanha a aritmética do score.
        favorable = clamp(1.0 - float(directional)) if not spec.direction(factor) else clamp(float(directional))

        # Orientação do SCORE da dimensão. Em dimensões tipo índice — a saturação
        # de mercado, em que maior é pior — a pontuação publicada sobe com o
        # problema, conforme `higher_score_is_better=False`. O detalhe que torna
        # isso honesto: `is_positive` continua indicando se o fator é FAVORÁVEL,
        # independentemente de como o número final é escalado.
        weighted_value = favorable if spec.higher_score_is_better else clamp(1.0 - favorable)

        contributions.append(
            ContributionResult(
                factor=factor,
                label=label,
                normalized=favorable,
                raw_value=raw_values.get(factor),
                raw_unit=spec.units.get(factor),
                weight=weight,
                available=True,
                is_positive=favorable >= 0.5,
                _weighted_value=weighted_value,
            )
        )

    available_weight = sum(c.weight or 0.0 for c in contributions if c.available)
    total_weight = sum(spec.weights.values()) or 1.0
    confidence = available_weight / total_weight if total_weight else 0.0

    if available_weight <= 0:
        return ScoreResult(
            dimension=spec.dimension,
            score=0.0,
            contributions=contributions,
            inputs=inputs,
            confidence=0.0,
            is_complete=False,
            insufficient_reasons=insufficient or ["nenhum insumo disponível"],
        )

    gamma = spec.gamma
    weighted_sum = 0.0
    for contribution in contributions:
        if not contribution.available or contribution.normalized is None:
            continue
        weight = contribution.weight or 0.0
        # Usa `_weighted_value`, não `normalized`: em dimensões tipo índice a
        # pontuação publicada é invertida, mas a explicação continua falando em
        # termos favoráveis/desfavoráveis.
        weighted_sum += weight * (contribution._weighted_value**gamma)

    score = 100.0 * weighted_sum / available_weight
    score = round(clamp(score, 0.0, 100.0), 3)

    # Segunda passada: impacto de cada fator no score final e texto de explicação.
    for contribution in contributions:
        if not contribution.available or contribution.normalized is None:
            contribution.impact = 0.0
            continue
        weight = contribution.weight or 0.0
        contribution.impact = round(
            100.0 * weight * (contribution._weighted_value**gamma) / available_weight, 3
        )

        formatter = spec.formatters.get(contribution.factor)
        if formatter is not None and contribution.raw_value is not None:
            try:
                contribution.explanation = formatter(contribution.raw_value)
            except Exception:  # noqa: BLE001 - formatação nunca deve quebrar o cálculo
                contribution.explanation = contribution.label
        else:
            contribution.explanation = contribution.label

    is_complete = not insufficient
    return ScoreResult(
        dimension=spec.dimension,
        score=score,
        contributions=contributions,
        inputs=inputs,
        confidence=round(confidence, 4),
        is_complete=is_complete,
        insufficient_reasons=insufficient,
    )


# --- Persistência -------------------------------------------------------------


def ensure_algorithm(session: Session, spec: AlgorithmSpec) -> ScoreAlgorithm:
    """Garante que a versão do algoritmo exista no banco (idempotente)."""
    existing = session.scalar(
        select(ScoreAlgorithm).where(
            ScoreAlgorithm.dimension == spec.dimension,
            ScoreAlgorithm.version == spec.version,
        )
    )
    if existing is not None:
        return existing

    algorithm = ScoreAlgorithm(
        dimension=spec.dimension,
        version=spec.version,
        name=spec.name,
        description=spec.description,
        algorithm_key=spec.algorithm_key,
        weights=dict(spec.weights),
        parameters=dict(spec.parameters),
        formula=spec.formula_text(),
        is_active=True,
        effective_from=datetime.now(UTC),
    )
    session.add(algorithm)
    session.flush()
    return algorithm


def persist_run(
    session: Session,
    *,
    spec: AlgorithmSpec,
    result: ScoreResult,
    target_type: str,
    target_id: int,
    computed_at: datetime | None = None,
    marketplace: Marketplace | str | None = None,
    source_record_id: int | None = None,
) -> ScoreRun:
    """Persiste o cálculo inteiro: inputs, pesos, fórmula, versão, resultado e ts."""
    algorithm = ensure_algorithm(session, spec)
    computed_at = computed_at or datetime.now(UTC)
    if isinstance(marketplace, str):
        marketplace = Marketplace(marketplace)

    run = ScoreRun(
        algorithm_id=algorithm.id,
        dimension=spec.dimension,
        algorithm_version=spec.version,
        target_type=target_type,
        target_id=target_id,
        computed_at=computed_at,
        inputs=result.inputs,
        weights=dict(spec.weights),
        formula=spec.formula_text(),
        inputs_hash=spec.inputs_hash(result.inputs),
        score=result.score,
        confidence=result.confidence,
        is_complete=result.is_complete,
        status=result.status,
        insufficient_reasons=result.insufficient_reasons or None,
        marketplace=marketplace,
        source_record_id=source_record_id,
    )
    session.add(run)
    session.flush()

    for position, contribution in enumerate(result.contributions):
        session.add(
            ScoreContribution(
                run_id=run.id,
                position=position,
                factor=contribution.factor,
                label=contribution.label,
                raw_value=contribution.raw_value,
                raw_unit=contribution.raw_unit,
                normalized_value=contribution.normalized,
                weight=contribution.weight,
                impact=contribution.impact,
                is_positive=contribution.is_positive,
                available=contribution.available,
                explanation=contribution.explanation,
            )
        )
    session.flush()
    return run


def load_specs() -> None:
    """Importa os módulos de algoritmo para que se registrem."""
    from core.services.scoring import (  # noqa: F401
        creative_saturation,
        heat,
        opportunity,
        producer_momentum,
    )


__all__ = [
    "AlgorithmSpec",
    "ContributionResult",
    "ScoreResult",
    "active_spec",
    "all_specs",
    "clamp",
    "compute",
    "ensure_algorithm",
    "get_spec",
    "growth",
    "load_specs",
    "normalize",
    "persist_run",
    "register",
    "saturate",
]
