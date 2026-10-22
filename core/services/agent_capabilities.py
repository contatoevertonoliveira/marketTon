"""O que o agente pode usar hoje, o que falta configurar e o que ainda não foi construído.

É a resposta honesta para "o que falta eu instalar para dar recursos de trabalho":
cada capacidade tem um status calculado do estado real do sistema, com o que o
operador precisa fornecer e o que isso destrava.

Status:
* `pronto`          — funciona agora;
* `configurar`      — existe, mas falta credencial/chave do operador;
* `nao_construido`  — ainda não existe no marketTon (precisa de desenvolvimento; é o
  que "vamos adicionando"). Nunca é apresentado como pronto.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from config.settings import get_settings
from core.db.base import JobStatus
from core.db.catalog import Product
from core.db.jobs import Job
from core.db.marketplace_credentials import MarketplaceCredential
from core.db.service_credentials import ServiceCredential
from core.db.tracking import Sale
from core.services.agent_chat import counts
from integrations.google_ads import GoogleAdsConfig

MARKETPLACE_SLUGS = ("mercado_livre", "shopee", "amazon", "tiktok_shop")


def integration_states(session: Session) -> list[dict]:
    """Estado das integrações, sem nenhum valor de credencial."""
    from backend.routers.marketplaces import CREDENTIAL_FIELDS  # evita ciclo na importação

    rows = {row.marketplace.value: row for row in session.scalars(select(MarketplaceCredential))}
    out = []
    for slug, fields in CREDENTIAL_FIELDS.items():
        row = rows.get(slug)
        out.append({
            "name": slug,
            "enabled": bool(row and row.enabled),
            "has_credentials": bool(row) and any(bool(row.values.get(f["name"])) for f in fields),
            "last_check_status": row.last_check_status if row else None,
            "last_check_message": row.last_check_message if row else None,
        })
    google = session.scalar(select(ServiceCredential).where(ServiceCredential.service == "google_ads"))
    out.append({
        "name": "google_ads",
        "enabled": bool(google and google.enabled),
        "has_credentials": bool(google) and GoogleAdsConfig.from_values(google.values).is_complete(),
        "last_check_status": google.last_check_status if google else None,
        "last_check_message": google.last_check_message if google else None,
    })
    return out


def _cap(key: str, name: str, status: str, unlocks: str, needs: list[str] | None = None, note: str | None = None) -> dict:
    return {"key": key, "name": name, "status": status, "unlocks": unlocks, "needs": needs or [], "note": note}


def capabilities(session: Session) -> list[dict]:
    settings = get_settings()
    states = {i["name"]: i for i in integration_states(session)}

    def marketplace(slug: str, label: str, unlocks: str) -> dict:
        s = states.get(slug, {})
        ok = s.get("enabled") and s.get("last_check_status") == "ok"
        return _cap(
            f"marketplace_{slug}", label, "pronto" if ok else "configurar", unlocks,
            [] if ok else [f"ativar {label} em Integrações, preencher as credenciais e testar a conexão"],
            s.get("last_check_message") if s.get("last_check_status") == "error" else None,
        )

    ads = states.get("google_ads", {})
    ads_ok = ads.get("enabled") and ads.get("last_check_status") == "ok"
    return [
        marketplace("mercado_livre", "Mercado Livre", "catálogo, concorrência por produto, tendências de outros países"),
        marketplace("shopee", "Shopee", "catálogo, comissão, vendas e comissão por pedido"),
        marketplace("hotmart", "Hotmart", "vendas e comissão como afiliado (a API não lista produtos para afiliar)"),
        marketplace("monetizze", "Monetizze", "produtos em que você é afiliado, vendas e comissão"),
        marketplace("eduzz", "Eduzz", "vendas e ganho como afiliado (a API não lista produtos para afiliar)"),
        _cap("google_trends", "Google Trends", "pronto", "tendência de busca de cada produto e palavra-chave",
             note="Acesso não oficial (biblioteca trendspy); a API oficial ainda é alfa com inscrição."),
        _cap("google_ads_keyword_planner", "Google Ads — Planejador de Palavras-chave", "pronto" if ads_ok else "configurar",
             "volume de busca, CPC e disputa por anúncios",
             [] if ads_ok else ["conectar a conta em Integrações → Google Ads e testar"]),
        _cap("ai_creatives", "Criativos com IA (AI Studio / Gemini)", "pronto" if settings.is_ai_configured else "configurar",
             "gerar roteiros, legendas, hooks e imagens/vídeos profissionais pela ferramenta de criação",
             [] if settings.is_ai_configured else [
                 "chave da API do AI Studio em AI_API_KEY",
                 "AI_ENABLED=true e AI_BASE_URL/AI_MODEL do modelo Gemini escolhido no .env"]),
        _cap("meta_ads_library", "Meta Ads Library (quem está gastando em anúncio)", "nao_construido",
             "listar anunciantes e criativos ativos por palavra-chave, para posicionar o orgânico na mesma onda",
             ["META_ACCESS_TOKEN (app da Meta com a Ads Library API)", "ferramenta MCP para consultar (a construir; o coletor existe em collectors/meta_ads/)"]),
        _cap("social_publishing", "Publicação nas redes (Instagram, TikTok, YouTube Shorts, Pinterest…)", "nao_construido",
             "publicar 1x de manhã e 1x à noite, com agendamento, pelas APIs oficiais",
             ["conta de desenvolvedor e app aprovado em cada rede", "tokens de acesso de cada conta",
              "integração construída no marketTon (hoje só existe o registro de publicações, sem conector)"]),
        _cap("ads_management", "Gerenciar anúncios pagos", "nao_construido",
             "criar e ajustar campanhas",
             ["escolher a plataforma (Google Ads, Meta, Shopee Ads…)", "permissão de escrita na conta e orçamento definido por você",
              "integração construída"],
             "O Google Ads está conectado só para leitura do Planejador. Afiliado não edita o anúncio do vendedor."),
        _cap("link_clicks", "Contagem de cliques nos links de afiliado", "nao_construido",
             "saber quais divulgações geram clique, não só venda", ["encurtador de links com contador (a construir)"]),
        _cap("catalog_collect_api", "Atualizar o catálogo pelo agente", "pronto",
             "coletar produtos e recalcular scores quando o catálogo envelhecer ou para um nicho novo",
             note="Intervalo mínimo de 6 h por marketplace; precisa de credencial testada."),
        _cap("sales_sync", "Sincronizar vendas e avisar", "pronto" if states.get("shopee", {}).get("last_check_status") == "ok" else "configurar",
             "trazer vendas novas, aprender comissão e avisar no chat", [] if states.get("shopee", {}).get("last_check_status") == "ok"
             else ["conectar a Shopee em Integrações"]),
        *[
            _cap(f"marketplace_{slug}", label, "nao_construido", "produtos, vendas e comissões da plataforma",
                 [f"credenciais da API do {label}", "adaptador construído e validado contra uma conta real"],
                 "Plataforma de produtos digitais: o modelo de comissão por oferta é diferente do de marketplace físico.")
            for slug, label in (("kirvano", "Kirvano"),)
        ],
    ]


def health(session: Session) -> dict:
    """Saúde do sistema: banco, frescor dos dados, integrações, jobs, e pendências do chat."""
    now = datetime.now(UTC)
    checks: list[dict] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    try:
        session.execute(text("SELECT 1"))
        add("banco_de_dados", "ok", "respondendo")
    except Exception as exc:  # noqa: BLE001 - a saúde precisa reportar, não quebrar
        add("banco_de_dados", "erro", str(exc)[:160])

    def age_days(value: datetime | None) -> float | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return (now - value).total_seconds() / 86400

    products = session.scalar(select(func.count()).select_from(Product)) or 0
    last_seen = session.scalar(select(func.max(Product.last_seen_at)))
    age = age_days(last_seen)
    if not products:
        add("catalogo", "aviso", "catálogo vazio")
    elif age is not None and age > 2:
        add("catalogo", "aviso", f"{products} produtos; última atualização há {age:.0f} dias — use refresh_catalog")
    else:
        add("catalogo", "ok", f"{products} produtos; atualizado há {0 if age is None else age:.1f} dia(s)")

    last_sale_sync = session.scalar(select(func.max(Sale.created_at)))
    sales = session.scalar(select(func.count()).select_from(Sale)) or 0
    sage = age_days(last_sale_sync)
    add("vendas", "ok" if sales else "aviso",
        f"{sales} venda(s) registrada(s)" + (f"; último registro há {sage:.1f} dia(s)" if sage is not None else "; nenhuma ainda"))

    for integ in integration_states(session):
        if not integ["enabled"]:
            continue
        if integ["last_check_status"] == "error":
            add(f"integracao_{integ['name']}", "erro", integ["last_check_message"] or "falha na última verificação")
        elif integ["last_check_status"] is None:
            add(f"integracao_{integ['name']}", "aviso", "nunca testada")
        else:
            add(f"integracao_{integ['name']}", "ok", "conectada")

    failed = session.scalar(
        select(func.count()).select_from(Job).where(Job.status == JobStatus.FAILED, Job.created_at >= now - timedelta(days=1))
    ) or 0
    add("jobs", "aviso" if failed else "ok", f"{failed} job(s) com falha nas últimas 24 h" if failed else "sem falhas nas últimas 24 h")

    c = counts(session)
    if c["open_requests"]:
        add("pedidos_do_agente", "aviso", f"{c['open_requests']} pedido(s) de recurso aguardando você")
    worst = "erro" if any(c_["status"] == "erro" for c_ in checks) else "aviso" if any(c_["status"] == "aviso" for c_ in checks) else "ok"
    return {"overall": worst, "checked_at": now.isoformat(), "checks": checks}
