"""TikTok Ads Library.

Estado atual: **não implementado**, e isso é deliberado.

A biblioteca pública de anúncios do TikTok (TikTok Creative Center / Commercial
Content Library) não expõe uma API REST pública e documentada com os campos que o
Creative Saturation Score precisa (volume de anúncios, anunciantes distintos,
idade do criativo). Implementar um scraper não oficial aqui produziria exatamente
o que o briefing seção 2 proíbe: dado de origem frágil entrando no domínio sem
nível de confiabilidade declarado.

Enquanto isso, `search_ads` falha de forma explícita e acionável. O Creative
Saturation Score trata a ausência como `INSUFFICIENT_DATA` e reduz a confiança,
em vez de estimar.
"""
from __future__ import annotations

from typing import Any


class TikTokAdsUnavailable(RuntimeError):
    """A fonte de anúncios do TikTok não está disponível."""


_MESSAGE = (
    "TikTok Ads Library não está integrada. Não há API pública documentada que "
    "forneça volume de anúncios e anunciantes distintos, que são os insumos do "
    "Creative Saturation Score. Possibilidades, em ordem de preferência:\n"
    "  1. TikTok Shop Affiliate Open API (requer aprovação de parceiro) — "
    "fornece dados de afiliado, não de anúncios de terceiros;\n"
    "  2. TikTok Business API — requer conta de anunciante própria;\n"
    "  3. Coleta manual/assistida, registrada com reliability reduzida.\n"
    "Enquanto isso o score de saturação é marcado como INSUFFICIENT_DATA."
)


def get_status() -> dict[str, Any]:
    return {"status": "not_implemented", "reason": _MESSAGE}


def search_ads(
    query: str,  # noqa: ARG001 - assinatura mantida para compatibilidade
    *,
    country: str = "BR",  # noqa: ARG001
    limit: int = 25,  # noqa: ARG001
) -> list[dict[str, Any]]:
    """Sempre levanta. Preferimos falhar a inventar dados."""
    raise TikTokAdsUnavailable(_MESSAGE)


__all__ = ["TikTokAdsUnavailable", "get_status", "search_ads"]
