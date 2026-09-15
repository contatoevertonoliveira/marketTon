"""API do Affiliate Intelligence System.

Aplicação FastAPI sobre PostgreSQL, com o domínio organizado em routers por área:
catálogo, scoring, portfólio, criativos, jobs e operação.

Mudança estrutural em relação à versão anterior: o backend usava `sqlite3` bruto com
um schema legado de 6 tabelas de suporte e nenhum endpoint de domínio. Agora ele fala
com os modelos SQLAlchemy da Fase 1, e o schema é responsabilidade exclusiva do
Alembic — a aplicação **não** cria tabela nenhuma em tempo de execução. Era essa
criação dupla que produzia três definições incompatíveis das mesmas tabelas.

Os endpoints legados de suporte (feedback, preferências, agenda, grupos, pagamentos)
foram preservados em `backend/legacy.py` e continuam montados, para não quebrar o
dashboard durante a transição.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.legacy import legacy_router
from backend.routers import API_ROUTERS
from config.settings import get_settings
from core.db.session import get_engine
from core.services.scoring.engine import load_specs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Valida a configuração no start e falha rápido se estiver errada.

    Sem isto, uma `DATABASE_URL` apontando para SQLite só apareceria no primeiro
    request, com um erro de driver confuso.
    """
    settings.validate_database_url()

    # Registra as dimensões de score e os adapters de marketplace. Ambos são
    # registro em processo — falhar aqui é melhor do que falhar no primeiro score.
    load_specs()
    from integrations.marketplaces.registry import list_adapter_names, load_adapters

    load_adapters()

    logger.info(
        "%s v%s starting | adapters: %s | IA: %s | auth: %s",
        settings.app_name,
        settings.app_version,
        ", ".join(sorted(list_adapter_names())) or "nenhum",
        "ligada" if settings.is_ai_configured else "desligada",
        "ligada" if settings.auth_enabled else "DESLIGADA",
    )

    # Problemas que impedem produção são reportados, não escondidos.
    for problem in settings.validate_production_readiness():
        logger.warning("prontidão de produção: %s", problem)

    try:
        with get_engine().connect():
            logger.info("conexão com o banco estabelecida")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "não foi possível conectar ao banco: %s. "
            "Rode `docker compose up -d db` e `alembic upgrade head`.",
            exc,
        )
    else:
        _bootstrap_admin()

    yield


def _bootstrap_admin() -> None:
    """Cria o administrador inicial quando não existe nenhum usuário.

    Necessário porque a API agora exige autenticação: sem usuário nenhum não há
    como autenticar para criar o primeiro. Só age com a tabela vazia, e apenas se
    `BOOTSTRAP_ADMIN_USERNAME`/`PASSWORD` estiverem definidos — do contrário, criar
    um admin com senha padrão seria pior do que não criar nenhum.
    """
    settings = get_settings()
    if not (settings.bootstrap_admin_username and settings.bootstrap_admin_password):
        return

    from core.db.session import session_scope
    from core.services.auth import WeakPassword, ensure_admin

    try:
        with session_scope() as session:
            created = ensure_admin(
                session,
                username=settings.bootstrap_admin_username,
                password=settings.bootstrap_admin_password,
            )
    except WeakPassword as exc:
        logger.error("BOOTSTRAP_ADMIN_PASSWORD não atende aos requisitos: %s", exc)
        return

    if created is not None:
        logger.warning(
            "administrador inicial '%s' criado. Remova BOOTSTRAP_ADMIN_PASSWORD do .env "
            "agora que a conta existe.",
            created.username,
        )


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Plataforma de inteligência e operação para marketing de afiliados "
        "multi-marketplace. Descobre oportunidades, pontua produtos de forma "
        "explicável, controla o pipeline criativo e acompanha vendas e comissões."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for api_router in API_ROUTERS:
    app.include_router(api_router)

# Endpoints de suporte herdados (feedback, preferências, agenda, grupos, pagamentos).
app.include_router(legacy_router)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "service": "marketTon — Affiliate Intelligence System",
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Verifica banco e configuração — não apenas se o processo subiu.

    A versão anterior respondia "ok" se o *arquivo* do SQLite existisse, o que não
    dizia nada sobre o schema estar aplicado.
    """
    from sqlalchemy import text

    database = {"connected": False, "error": None}
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        database["connected"] = True
    except Exception as exc:  # noqa: BLE001
        database["error"] = str(exc)

    from core.db.base import Marketplace

    problems = settings.validate_production_readiness()

    return {
        "status": "ok" if database["connected"] else "degraded",
        "version": settings.app_version,
        "database": database,
        "ai_enabled": settings.is_ai_configured,
        "auth_enabled": settings.auth_enabled,
        # Lista o que impediria ir a produção. Exposto porque "quase pronto" sem
        # dizer o que falta é indistinguível de pronto.
        "production_blockers": problems,
        "production_ready": not problems and database["connected"],
        # Marketplaces que o domínio suporta. O estado de configuração de cada
        # conector fica em `/operations/connectors`, que é onde é acionável.
        "marketplace_supported": sorted(marketplace.value for marketplace in Marketplace),
    }
