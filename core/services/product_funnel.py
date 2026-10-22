"""Funil de venda de um produto: busca no Google + economia da comissão.

Responde "este produto tem um bom funil para vender?" com **regras explícitas e
auditáveis**, cada uma mostrando o dado que a sustenta — o mesmo espírito do selo
"Aprovado". Não é previsão de vendas: é um filtro que junta o que o sistema
sabe (Google Trends, Planejador do Google Ads, preço e comissão do produto).

Premissas que o operador controla e que ficam visíveis na resposta:

* a **palavra-chave** é sugerida a partir do título e pode ser trocada;
* a **taxa de conversão** (cliques que viram compra) não existe em nenhuma API,
  então é uma premissa ajustável; o teto de CPC depende dela.

Dado que falta vira `unknown` e não entra na conta: "sem dado" nunca é tratado
como "reprovado".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.services.keyword_metrics import KeywordMetrics

MIN_MONTHLY_VOLUME = 1000  # limiar adotado; aparece no texto do critério
DEFAULT_CONVERSION_PCT = 1.5  # premissa inicial editável, não uma medida

_STOPWORDS = {
    "de", "da", "do", "das", "dos", "para", "pra", "com", "sem", "e", "em", "a", "o", "as", "os", "um", "uma",
    "no", "na", "nos", "nas", "ou", "por", "kit", "unidade", "unidades", "cor", "cores", "tamanho", "original",
    "novo", "nova", "oferta", "promoção", "promocao", "frete", "grátis", "gratis", "envio", "imediato", "pronta",
    "entrega", "premium", "top", "alta", "qualidade", "importado", "importada", "lançamento", "lancamento",
    "pç", "pcs", "peças", "pecas", "conjunto", "linha", "ideal", "super", "mega", "melhor",
}


def _tokens(title: str | None) -> list[str]:
    """Palavras úteis do título: sem vazias, sem medidas/códigos (tokens com dígito) e sem repetidas."""
    if not title:
        return []
    words: list[str] = []
    for token in re.split(r"[^\wÀ-ÿ]+", title.lower()):
        if len(token) <= 2 or any(ch.isdigit() for ch in token) or "_" in token:
            continue
        if token in _STOPWORDS or token in words:
            continue
        words.append(token)
    return words


def suggest_keyword(title: str | None, max_words: int = 3) -> str | None:
    """Palavra-chave de busca a partir do título do anúncio (as primeiras palavras úteis).

    Heurística simples e declarada. Título de marketplace é ruidoso — por isso a
    tela deixa o operador editar o resultado.
    """
    return " ".join(_tokens(title)[:max_words]) or None


def suggest_candidates(title: str | None) -> list[str]:
    """Até 3 palavras-chave candidatas (2, 3 e 4 primeiras palavras úteis).

    Quanto mais palavras, mais específica e menos buscada. O endpoint mede o
    volume de cada uma no Google Ads e fica com a mais buscada.
    """
    words = _tokens(title)
    if not words:
        return []
    if len(words) == 1:
        return words
    out: list[str] = []
    for n in (2, 3, 4):
        if len(words) >= n:
            candidate = " ".join(words[:n])
            if candidate not in out:
                out.append(candidate)
    return out


@dataclass
class Check:
    key: str
    label: str
    status: str  # "pass" | "fail" | "unknown"
    detail: str
    group: str  # "demanda" | "anuncios"


@dataclass
class Funnel:
    commission_per_sale: float | None
    breakeven_cpc: float | None
    conversion_pct: float
    checks: list[Check] = field(default_factory=list)
    # Veredito geral = o da demanda (o produto vende?). O tráfego pago é separado: a
    # comissão de afiliado costuma ser pequena perto do CPC, e quem divulga de forma
    # orgânica (vídeo, redes) não paga clique — misturar os dois reprovaria quase tudo.
    verdict: str = "insufficient"  # "good" | "uncertain" | "weak" | "insufficient"
    demand_verdict: str = "insufficient"
    ads_verdict: str = "insufficient"
    summary: str = ""


def _brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def commission_per_sale(price: float | None, pct: float | None, fixed: float | None) -> float | None:
    if price is not None and pct is not None:
        return round(price * pct / 100, 2)
    if fixed is not None:
        return round(fixed, 2)
    return None


def compute_funnel(
    *,
    price: float | None,
    commission_pct: float | None,
    commission_fixed: float | None,
    sold_quantity: int | None,
    ranking_position: int | None,
    metrics: KeywordMetrics,
    conversion_pct: float = DEFAULT_CONVERSION_PCT,
) -> Funnel:
    per_sale = commission_per_sale(price, commission_pct, commission_fixed)
    breakeven = round(per_sale * conversion_pct / 100, 2) if per_sale is not None else None
    funnel = Funnel(commission_per_sale=per_sale, breakeven_cpc=breakeven, conversion_pct=conversion_pct)
    checks = funnel.checks

    # --- Demanda ---------------------------------------------------------------
    if metrics.trend_direction is None:
        checks.append(Check("trend", "Interesse de busca não está caindo", "unknown",
                            metrics.trend_error or "sem série do Google Trends", "demanda"))
    else:
        growth = f"{metrics.growth_pct_30d:+.1f}% em 30 dias" if metrics.growth_pct_30d is not None else ""
        ok = metrics.trend_direction in ("rising", "stable")
        word = {"rising": "em alta", "stable": "estável", "falling": "em queda"}[metrics.trend_direction]
        checks.append(Check("trend", "Interesse de busca não está caindo", "pass" if ok else "fail",
                            f"{word} ({growth})".strip(), "demanda"))

    if metrics.monthly_volume is None:
        checks.append(Check("volume", f"Volume de busca de pelo menos {MIN_MONTHLY_VOLUME:,}/mês".replace(",", "."),
                            "unknown", "Google Ads não conectado ou sem dado para esta palavra", "demanda"))
    else:
        ok = metrics.monthly_volume >= MIN_MONTHLY_VOLUME
        checks.append(Check("volume", f"Volume de busca de pelo menos {MIN_MONTHLY_VOLUME:,}/mês".replace(",", "."),
                            "pass" if ok else "fail", f"{metrics.monthly_volume:,} buscas/mês".replace(",", "."), "demanda"))

    has_sales_signal = (sold_quantity is not None and sold_quantity > 0) or (
        ranking_position is not None and ranking_position <= 10
    )
    checks.append(Check(
        "marketplace_demand", "Já vende no marketplace",
        "pass" if has_sales_signal else "unknown",
        (f"{sold_quantity} vendido(s)" if sold_quantity else f"#{ranking_position} nos mais vendidos")
        if has_sales_signal else "sem dado de vendas neste marketplace",
        "demanda",
    ))

    # --- Tráfego pago ------------------------------------------------------------
    cpc = metrics.cpc_brl
    if cpc is None:
        why = "Google Ads não conectado ou sem dado" if metrics.planner_source is None else "sem CPC em reais para esta palavra"
        checks.append(Check("cpc", "Se for anunciar: o CPC cabe na comissão", "unknown", why, "anuncios"))
    elif breakeven is None:
        checks.append(Check("cpc", "Se for anunciar: o CPC cabe na comissão", "unknown",
                            f"CPC {_brl(cpc)}, mas o produto não tem comissão informada", "anuncios"))
    else:
        ok = cpc <= breakeven
        checks.append(Check(
            "cpc", "Se for anunciar: o CPC cabe na comissão", "pass" if ok else "fail",
            f"CPC {_brl(cpc)} contra teto de {_brl(breakeven)} "
            f"(comissão {_brl(per_sale)} × conversão de {conversion_pct:g}%)", "anuncios"))

    if metrics.competition is None:
        checks.append(Check("ad_competition", "Disputa por anúncios não é alta", "unknown",
                            "Google Ads não conectado ou sem dado", "anuncios"))
    else:
        ok = metrics.competition in ("LOW", "MEDIUM")
        label = {"LOW": "baixa", "MEDIUM": "média", "HIGH": "alta"}[metrics.competition]
        idx = f" (índice {metrics.competition_index}/100)" if metrics.competition_index is not None else ""
        checks.append(Check("ad_competition", "Disputa por anúncios não é alta", "pass" if ok else "fail",
                            f"disputa {label}{idx}", "anuncios"))

    # --- Veredito ----------------------------------------------------------------
    demand = [c for c in checks if c.group == "demanda"]
    ads = [c for c in checks if c.group == "anuncios"]
    funnel.demand_verdict, d_pass, d_known = _group_verdict(demand, min_known=2)
    funnel.ads_verdict, a_pass, a_known = _group_verdict(ads, min_known=1)
    funnel.verdict = funnel.demand_verdict

    if funnel.demand_verdict == "insufficient":
        funnel.summary = (
            f"Dados insuficientes: só {d_known} de {len(demand)} critérios de demanda têm informação. "
            "Conecte o Google Ads e confira a palavra-chave para uma resposta."
        )
        return funnel

    d_word = {"good": "promissora", "uncertain": "incerta", "weak": "fraca"}[funnel.demand_verdict]
    parts = [f"Demanda {d_word} ({d_pass} de {d_known} critérios)"]
    if funnel.ads_verdict == "insufficient":
        parts.append("tráfego pago sem dado")
    else:
        a_word = {"good": "compensa", "uncertain": "é incerto", "weak": "não compensa"}[funnel.ads_verdict]
        parts.append(f"tráfego pago {a_word} ({a_pass} de {a_known})")
    failed = [c.label for c in checks if c.status == "fail"]
    funnel.summary = "; ".join(parts) + (f". Não passa: {'; '.join(failed)}." if failed else ".")
    return funnel


def _group_verdict(group: list[Check], *, min_known: int) -> tuple[str, int, int]:
    known = [c for c in group if c.status != "unknown"]
    passed = sum(1 for c in known if c.status == "pass")
    if len(known) < min_known:
        return "insufficient", passed, len(known)
    ratio = passed / len(known)
    return ("good" if ratio >= 0.75 else "weak" if ratio <= 0.34 else "uncertain"), passed, len(known)


__all__ = ["Check", "Funnel", "compute_funnel", "commission_per_sale", "suggest_candidates", "suggest_keyword", "DEFAULT_CONVERSION_PCT"]
