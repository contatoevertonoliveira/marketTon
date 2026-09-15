"""Integrações externas: marketplaces, anúncios, pagamentos e mensageria.

Cada subpacote é independente. Nada aqui deve conter regra de negócio — apenas
tradução entre a API externa e o domínio (briefing seção 2).
"""
from __future__ import annotations

__all__ = ["marketplaces"]
