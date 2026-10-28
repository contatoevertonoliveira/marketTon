"""Routers da API do Affiliate Intelligence System.

Cada módulo agrupa um domínio. `API_ROUTERS` é usado por `backend/main.py` para
registrar todos de uma vez.
"""
from __future__ import annotations

from backend.routers import (
    agent,
    agent_reports,
    auth,
    catalog,
    creative,
    creatives,
    finance,
    jobs,
    links,
    marketplaces,
    operations,
    performance,
    portfolio,
    scoring,
    services,
    social,
    storefront,
    trends,
    vetting,
)

API_ROUTERS = [
    auth.router,
    catalog.router,
    scoring.router,
    portfolio.router,
    creative.router,
    jobs.router,
    operations.router,
    marketplaces.router,
    trends.router,
    performance.router,
    services.router,
    agent.router,
    links.router,
    storefront.router,
    creatives.router,
    agent_reports.router,
    finance.router,
    social.router,
    vetting.router,
]

__all__ = [
    "API_ROUTERS",
    "agent",
    "agent_reports",
    "auth",
    "catalog",
    "creative",
    "creatives",
    "finance",
    "social",
    "jobs",
    "links",
    "marketplaces",
    "operations",
    "performance",
    "portfolio",
    "scoring",
    "services",
    "storefront",
    "trends",
    "vetting",
]
