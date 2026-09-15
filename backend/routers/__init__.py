"""Routers da API do Affiliate Intelligence System.

Cada módulo agrupa um domínio. `API_ROUTERS` é usado por `backend/main.py` para
registrar todos de uma vez.
"""
from __future__ import annotations

from backend.routers import auth, catalog, creative, jobs, operations, portfolio, scoring

API_ROUTERS = [
    auth.router,
    catalog.router,
    scoring.router,
    portfolio.router,
    creative.router,
    jobs.router,
    operations.router,
]

__all__ = [
    "API_ROUTERS",
    "auth",
    "catalog",
    "creative",
    "jobs",
    "operations",
    "portfolio",
    "scoring",
]
