"""Endpoints de catálogo: produtos coletados, procedência e séries temporais.

Leitura apenas. A entrada de dados acontece pela ingestão
(`core/services/ingestion.py`), não por HTTP — aceitar produto por POST criaria um
caminho sem proveniência, e o briefing seção 4 exige origem para todo dado.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.deps import get_adapters, get_session
from backend.security import Principal, record_action, require
from backend.serializers import (
    latest_scores_by_dimension,
    product_detail,
    product_summary,
    source_record_out,
)
from backend.schemas import ProductDetail, ProductSummary, SourceRecordOut, TrendingAbroadProduct
from core.db.base import Marketplace
from config.settings import get_settings
from core.db.catalog import Product, SourceRecord
from core.services.keyword_metrics import analyze_keywords, planner_provider, planner_volumes
from core.services.commission_offer import offer_info, offer_note
from core.services.product_funnel import DEFAULT_CONVERSION_PCT, compute_funnel, suggest_candidates

# Todas as rotas exigem `catalog.view`. O portão é declarado no router em vez de
# repetido em cada endpoint: esquecer um seria um buraco silencioso.
router = APIRouter(
    prefix="/catalog",
    tags=["catálogo"],
    dependencies=[Depends(require("catalog.view"))],
)


@router.get("/products", response_model=list[ProductSummary])
def list_products(
    session: Session = Depends(get_session),
    marketplace: Marketplace | None = None,
    category_id: str | None = None,
    brand: str | None = None,
    search: str | None = Query(None, description="Busca textual no título"),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    min_commission_pct: float | None = Query(None, ge=0),
    min_rating: float | None = Query(None, ge=0, le=5),
    only_active: bool = True,
    seen_within_days: int | None = Query(None, ge=1, description="Visto nos últimos N dias"),
    order_by: str = Query("last_seen_at", pattern="^(last_seen_at|price|rating|sold_quantity|discount_pct)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ProductSummary]:
    """Lista o catálogo com filtros.

    Campos sem dado na fonte não aparecem em filtro numérico — filtrar por
    `min_commission_pct` exclui produtos cuja comissão é desconhecida, o que é
    diferente de excluir produtos com comissão baixa.
    """
    statement = select(Product)

    if marketplace is not None:
        statement = statement.where(Product.marketplace == marketplace)
    if category_id:
        statement = statement.where(Product.category_id == category_id)
    if brand:
        statement = statement.where(Product.brand == brand)
    if search:
        statement = statement.where(Product.title.ilike(f"%{search}%"))
    if min_price is not None:
        statement = statement.where(Product.price >= min_price)
    if max_price is not None:
        statement = statement.where(Product.price <= max_price)
    if min_commission_pct is not None:
        statement = statement.where(Product.affiliate_commission_pct >= min_commission_pct)
    if min_rating is not None:
        statement = statement.where(Product.rating >= min_rating)
    if only_active:
        statement = statement.where(Product.is_active.is_(True))
    if seen_within_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=seen_within_days)
        statement = statement.where(Product.last_seen_at >= cutoff)

    order_column = getattr(Product, order_by)
    statement = statement.order_by(order_column.desc().nullslast()).limit(limit).offset(offset)
    # Card grid mostra confiabilidade do vendedor — carrega junto para não
    # virar uma consulta por produto.
    statement = statement.options(selectinload(Product.seller))

    products = list(session.scalars(statement))
    scores = latest_scores_by_dimension(session, [product.id for product in products])
    return [product_summary(product, scores.get(product.id)) for product in products]


@router.get("/products/{product_id}", response_model=ProductDetail)
def get_product(product_id: int, session: Session = Depends(get_session)) -> ProductDetail:
    """Detalhe do produto: procedência, histórico de preço, métricas e explicações.

    `score_explanations` responde "por que este produto foi recomendado?" — é a
    lista `+ motivo` / `- motivo` derivada da aritmética do score.
    """
    product = session.scalar(
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.seller),
            selectinload(Product.source_record),
        )
    )
    if product is None:
        raise HTTPException(status_code=404, detail=f"produto {product_id} não encontrado")
    return product_detail(session, product)


_MEDIA_HOSTS = ("susercontent.com", "shopee.com.br", "shopee.com")
_MAX_IMAGE_BYTES = 15 * 1024 * 1024
_EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@router.post(
    "/products/{product_id}/download-images",
    dependencies=[Depends(require("portfolio.manage"))],
)
def download_product_images(product_id: int, session: Session = Depends(get_session)) -> dict:
    """Baixa as fotos que a API do marketplace devolveu para `data/media/<mp>/<id>/`.

    Só baixa URLs já gravadas no produto (nunca uma URL vinda do cliente) e só
    de domínios da própria Shopee — evita que o endpoint vire proxy aberto.
    A API oficial de afiliados entrega apenas a foto principal; vídeo e
    galeria completa não estão nela.
    """
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"produto {product_id} não encontrado")
    urls = [u for u in (product.images or []) if isinstance(u, str)]
    if not urls:
        raise HTTPException(status_code=404, detail="produto sem foto registrada")

    marketplace = product.marketplace.value if hasattr(product.marketplace, "value") else str(product.marketplace)
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", product.external_id)
    folder = Path(get_settings().media_dir) / marketplace / safe_id
    folder.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for index, url in enumerate(urls, start=1):
        host = urlparse(url).hostname or ""
        if not any(host == h or host.endswith("." + h) for h in _MEDIA_HOSTS):
            continue
        try:
            response = requests.get(url, timeout=20, stream=True)
            response.raise_for_status()
            ext = _EXT_BY_TYPE.get(response.headers.get("content-type", "").split(";")[0], ".jpg")
            data = response.raw.read(_MAX_IMAGE_BYTES + 1, decode_content=True)
        except requests.RequestException:
            continue
        if len(data) > _MAX_IMAGE_BYTES:
            continue
        target = folder / f"foto_{index}{ext}"
        target.write_bytes(data)
        saved.append(str(target.resolve()))

    if not saved:
        raise HTTPException(status_code=502, detail="não foi possível baixar nenhuma foto")
    return {"folder": str(folder.resolve()), "files": saved}


class ManualSignalsIn(BaseModel):
    affiliate_count: int | None = Field(None, ge=0, le=10_000_000)
    affiliate_count_period: str | None = Field(None, pattern="^(total|semana|mes)$")
    manual_stock: int | None = Field(None, ge=0, le=1_000_000_000)


@router.put(
    "/products/{product_id}/manual-signals",
    response_model=ProductSummary,
    dependencies=[Depends(require("portfolio.manage"))],
)
def set_manual_signals(
    product_id: int, body: ManualSignalsIn, session: Session = Depends(get_session)
) -> ProductSummary:
    """Registra afiliados (e período) e estoque lidos no app de afiliados.

    Nem a Affiliate Open API nem os feeds expõem esses números, então são
    dados digitados, não coletados; `None` limpa o valor.
    """
    product = session.scalar(
        select(Product).where(Product.id == product_id).options(selectinload(Product.seller))
    )
    if product is None:
        raise HTTPException(status_code=404, detail=f"produto {product_id} não encontrado")
    product.affiliate_count = body.affiliate_count
    product.affiliate_count_period = body.affiliate_count_period if body.affiliate_count is not None else None
    product.manual_stock = body.manual_stock
    typed = body.affiliate_count is not None or body.manual_stock is not None
    product.affiliate_count_updated_at = datetime.now(UTC) if typed else None
    session.commit()
    scores = latest_scores_by_dimension(session, [product.id])
    return product_summary(product, scores.get(product.id))


@router.get("/products/{product_id}/comparables", response_model=list[ProductSummary])
def product_comparables(product_id: int, session: Session = Depends(get_session)) -> list[ProductSummary]:
    """Mesmo produto (por `identity_key`) já visto em outro anúncio ou marketplace.

    `identity_key` (título normalizado + marca) é gerado na ingestão, mas nunca
    tinha um consumidor — é a resposta real para "esse preço compete com quem
    mais vende a mesma coisa?", sem inventar um comparador externo. Só existe
    resultado quando o catálogo já coletou o mesmo produto de outro lugar;
    catálogo pequeno ou de nicho único não terá comparáveis, o que é honesto,
    não um bug.
    """
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"produto {product_id} não encontrado")
    if not product.identity_key:
        return []

    others = session.scalars(
        select(Product)
        .where(Product.identity_key == product.identity_key, Product.id != product_id)
        .options(selectinload(Product.seller))
        .order_by(Product.price.asc().nullslast())
    ).all()
    scores = latest_scores_by_dimension(session, [p.id for p in others])
    return [product_summary(p, scores.get(p.id)) for p in others]


_ML_SITE_COUNTRY = {
    "MLB": "Brasil",
    "MLA": "Argentina",
    "MLM": "México",
    "MCO": "Colômbia",
    "MLC": "Chile",
    "MLU": "Uruguai",
    "MPE": "Peru",
    "MLV": "Venezuela",
}


@router.get("/trending-abroad", response_model=list[TrendingAbroadProduct])
def trending_abroad(
    session: Session = Depends(get_session),
    sites: str = Query("MLM,MCO,MLC", description="Sites da Mercado Livre, separados por vírgula"),
    limit_per_site: int = Query(15, ge=1, le=30),
) -> list[TrendingAbroadProduct]:
    """Mais vendidos de outros países da Mercado Livre — ao vivo, não persistido.

    Confirmado ao vivo que o mesmo app funciona em MLM/MCO/MLC sem credencial
    nova; um site bloqueado (ex.: MLA) é só pulado, sem quebrar os demais.
    `already_in_brazil_catalog` compara `identity_key` (título normalizado +
    marca) exato com o catálogo brasileiro já coletado — não é tradução
    automática, então `False` aqui é "não achamos correspondência exata", não
    "produto inédito garantido".
    """
    from integrations.marketplaces.mercado_livre import MLAdapterOptions

    adapter = get_adapters().get("mercado_livre")
    if adapter is None:
        raise HTTPException(status_code=500, detail="adapter mercado_livre não registrado")

    # Um lote só, reaproveitado por todos os produtos estrangeiros — bem mais
    # barato que uma consulta por item quando o catálogo BR já tem centenas
    # de linhas.
    br_products = list(
        session.scalars(
            select(Product)
            .where(Product.marketplace == Marketplace.MERCADO_LIVRE, Product.identity_key.is_not(None))
            .options(selectinload(Product.seller))
        )
    )
    br_by_key: dict[str, list[Product]] = {}
    for p in br_products:
        br_by_key.setdefault(p.identity_key, []).append(p)
    br_scores = latest_scores_by_dimension(session, [p.id for p in br_products])

    out: list[TrendingAbroadProduct] = []
    for site in [s.strip().upper() for s in sites.split(",") if s.strip()]:
        try:
            batch = adapter.fetch_products(
                options=MLAdapterOptions(
                    site_id=site,
                    max_items=limit_per_site,
                    fetch_reviews=False,
                    fetch_seller_profile=True,
                )
            )
        except Exception:  # noqa: BLE001 - país indisponível não pode quebrar os outros
            continue
        for product in batch.products:
            matches = br_by_key.get(product.identity_key(), [])
            attrs = product.attributes or {}
            out.append(
                TrendingAbroadProduct(
                    site_id=site,
                    country=_ML_SITE_COUNTRY.get(site, site),
                    external_id=product.external_id,
                    title=product.title,
                    category_id=product.category_id,
                    price=product.price,
                    currency=product.currency,
                    ranking_position=product.ranking_position,
                    product_url=product.product_url,
                    images=product.images,
                    seller_nickname=product.seller_nickname,
                    competing_offers=attrs.get("competing_offers"),
                    competing_price_min=attrs.get("competing_price_min"),
                    competing_price_max=attrs.get("competing_price_max"),
                    already_in_brazil_catalog=bool(matches),
                    brazil_matches=[product_summary(p, br_scores.get(p.id)) for p in matches],
                )
            )
    return out


@router.get("/products/{product_id}/source", response_model=list[SourceRecordOut])
def product_provenance(
    product_id: int, session: Session = Depends(get_session)
) -> list[SourceRecordOut]:
    """Trilha de procedência: todas as coletas que tocaram este produto.

    Usa o `external_id` e o marketplace do produto para reunir o histórico de
    coletas, não apenas a última — é isso que permite auditar de onde veio cada
    valor ao longo do tempo.
    """
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"produto {product_id} não encontrado")

    statement = (
        select(SourceRecord)
        .where(
            SourceRecord.marketplace == product.marketplace,
            SourceRecord.external_id == product.external_id,
        )
        .order_by(SourceRecord.collected_at.desc())
    )
    records = list(session.scalars(statement))

    # A coleta mais recente pode ter vindo de um lote sem `external_id` por item;
    # nesse caso incluímos o registro atual do produto para não devolver vazio.
    if not records and product.source_record is not None:
        records = [product.source_record]

    return [out for out in (source_record_out(record) for record in records) if out is not None]


@router.get("/stats")
def catalog_stats(session: Session = Depends(get_session)) -> dict:
    """Panorama do catálogo. Serve de contexto para filtros e para o painel."""
    total = session.scalar(select(func.count()).select_from(Product)) or 0
    active = session.scalar(select(func.count()).select_from(Product).where(Product.is_active.is_(True))) or 0

    by_marketplace = session.execute(
        select(Product.marketplace, func.count(Product.id)).group_by(Product.marketplace)
    ).all()

    # Quantos produtos têm cada campo preenchido. É a medida de completude real da
    # coleta, e o que explica por que um score pode sair com confiança baixa.
    field_coverage = {
        field: int(session.scalar(select(func.count()).select_from(Product).where(column.is_not(None))) or 0)
        for field, column in (
            ("price", Product.price),
            ("affiliate_commission_pct", Product.affiliate_commission_pct),
            ("rating", Product.rating),
            ("review_count", Product.review_count),
            ("available_quantity", Product.available_quantity),
            ("sold_quantity", Product.sold_quantity),
            ("seller_id", Product.seller_id),
        )
    }

    last_collection = session.scalar(select(func.max(Product.last_seen_at)))

    return {
        "total_products": total,
        "active_products": active,
        "inactive_products": total - active,
        "by_marketplace": [
            {"marketplace": marketplace.value, "products": int(count)}
            for marketplace, count in by_marketplace
        ],
        "field_coverage": field_coverage,
        "last_collection_at": last_collection.isoformat() if last_collection else None,
    }


@router.get("/marketplaces")
def available_marketplaces() -> dict:
    """Marketplaces suportados pelo domínio e o estado de cada conector."""
    adapters = get_adapters()
    return {
        "supported": [marketplace.value for marketplace in Marketplace],
        "connectors": [
            {
                "connector": name,
                "configured": adapter.is_configured(),
                "reliability": adapter.reliability,
            }
            for name, adapter in sorted(adapters.items())
            if adapter is not None
        ],
    }


# --- Funil de venda (Google Trends + Google Ads) -----------------------------


class FunnelCheckOut(BaseModel):
    key: str
    label: str
    status: str  # "pass" | "fail" | "unknown"
    detail: str
    group: str  # "demanda" | "anuncios"


class ProductFunnelOut(BaseModel):
    product_id: int
    keyword: str | None = None
    keyword_source: str  # "title" (sugerida) | "manual" (informada pelo operador)
    # Candidatas tiradas do título, com o volume medido (None = sem dado). A escolhida
    # é a de maior volume; a tela deixa trocar.
    candidates: list[dict] = Field(default_factory=list)
    metrics: dict | None = None
    planner_provider: str | None = None
    planner_error: str | None = None
    conversion_pct: float
    commission_per_sale: float | None = None
    breakeven_cpc: float | None = None
    verdict: str  # "good" | "uncertain" | "weak" | "insufficient" (= demanda)
    demand_verdict: str = "insufficient"
    ads_verdict: str = "insufficient"
    summary: str
    checks: list[FunnelCheckOut] = Field(default_factory=list)
    # Comissão extra do vendedor e até quando vale (None = produto sem comissão extra).
    commission_offer: dict | None = None
    commission_note: str | None = None


class DigitalImportIn(BaseModel):
    csv: str = Field(min_length=1, max_length=400_000)


@router.post("/import-digital", summary="Importar produtos digitais (Hotmart, Eduzz, Monetizze) de uma planilha CSV")
def import_digital(
    payload: DigitalImportIn,
    principal: Principal = Depends(require("catalog.manage")),
    session: Session = Depends(get_session),
) -> dict:
    """As plataformas digitais não têm API de descoberta: o operador escolhe no painel de cada uma e importa aqui."""
    from core.services import digital_import

    try:
        report = digital_import.import_csv(session, payload.csv)
    except digital_import.ImportError_ as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="catalog.digital_import", resource_type="product",
                  detail=f"{report.created_or_updated} produto(s): {report.by_platform}")
    session.commit()
    return {"imported": report.created_or_updated, "rows": report.rows, "by_platform": report.by_platform, "errors": report.errors}


@router.get("/products/{product_id}/funnel", response_model=ProductFunnelOut)
def product_funnel(
    product_id: int,
    keyword: str | None = Query(None, max_length=120, description="Palavra-chave; padrão: sugerida pelo título"),
    conversion_pct: float = Query(DEFAULT_CONVERSION_PCT, gt=0, le=50, description="Premissa: % dos cliques que viram compra"),
    session: Session = Depends(get_session),
) -> ProductFunnelOut:
    """Funil de venda do produto: Trends + Planejador do Google Ads + economia da comissão.

    Ao vivo (com cache de 6 h por palavra-chave). Sem palavra-chave utilizável, ou
    sem Google Ads, devolve o que tem e marca o resto como "sem dado" — nunca estima.
    """
    from dataclasses import asdict

    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"produto {product_id} não encontrado")

    offer = offer_info(product.attributes)
    manual = bool(keyword and keyword.strip())
    candidates = suggest_candidates(product.title)
    volumes = planner_volumes(candidates) if candidates else {}
    if manual:
        term = keyword.strip()
    elif candidates:
        # A mais buscada; sem volume para nenhuma, a primeira (a mais curta).
        term = max(candidates, key=lambda c: (volumes.get(c) or -1, -len(c)))
    else:
        term = None
    candidate_out = [{"keyword": c, "monthly_volume": volumes.get(c)} for c in candidates]
    if not term:
        return ProductFunnelOut(
            product_id=product_id, keyword=None, keyword_source="title", conversion_pct=conversion_pct,
            verdict="insufficient", summary="Não foi possível sugerir uma palavra-chave a partir do título. Informe uma.",
            commission_offer=offer, commission_note=offer_note(offer),
        )

    (metrics,) = analyze_keywords([term])
    funnel = compute_funnel(
        price=product.price,
        commission_pct=product.affiliate_commission_pct,
        commission_fixed=product.affiliate_commission_fixed,
        sold_quantity=product.sold_quantity,
        ranking_position=product.ranking_position,
        metrics=metrics,
        conversion_pct=conversion_pct,
    )
    return ProductFunnelOut(
        product_id=product_id,
        keyword=term,
        keyword_source="manual" if manual else "title",
        candidates=candidate_out,
        metrics={k: v for k, v in asdict(metrics).items() if k != "notes"},
        planner_provider=planner_provider(),
        planner_error=metrics.planner_error,
        conversion_pct=conversion_pct,
        commission_per_sale=funnel.commission_per_sale,
        breakeven_cpc=funnel.breakeven_cpc,
        verdict=funnel.verdict,
        demand_verdict=funnel.demand_verdict,
        ads_verdict=funnel.ads_verdict,
        summary=funnel.summary,
        checks=[FunnelCheckOut(**asdict(c)) for c in funnel.checks],
        commission_offer=offer,
        commission_note=offer_note(offer),
    )
