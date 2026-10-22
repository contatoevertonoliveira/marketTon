"""Links curtos rastreados: o clique é contado num redirecionador público e o marketTon busca a contagem.

Por que fora do backend: o marketTon roda no computador do operador (`localhost`), que a internet não
alcança. O redirecionador vive no domínio público (funções Netlify em `site/netlify/functions`), guarda
cada clique lá — mesmo com o computador desligado — e este módulo cria os links e traz os cliques para o
banco (`affiliate_links`, `click_events`), de onde saem "Mais cliques" e a taxa de clique por divulgação.

Contagem honesta: robôs e pré-visualizadores de link (WhatsApp, Telegram, Facebook…) não contam; o clique é
do link curto, **não** é visualização do post nem venda (a venda continua vindo do marketplace).
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.db.app_settings import AppSetting
from core.db.catalog import Product
from core.db.portfolio import PortfolioItem
from core.db.service_credentials import ServiceCredential
from core.db.tracking import AffiliateLink, ClickEvent

logger = logging.getLogger(__name__)

SERVICE = "link_shortener"
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # sem 0/o/1/l/i: o código pode ser lido e digitado
CODE_LENGTH = 7
CURSOR_KEY = "link_clicks_cursor"
CHANNELS = ("instagram", "tiktok", "youtube", "pinterest", "whatsapp", "telegram", "facebook", "x", "shopee_video", "outro")
TIMEOUT = 25


class ShortenerError(RuntimeError):
    """Falha do encurtador. A mensagem é segura para exibir ao operador."""


@dataclass
class ShortenerConfig:
    base_url: str
    admin_token: str


def load_config(session: Session) -> ShortenerConfig | None:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == SERVICE))
    if row is None or not row.enabled:
        return None
    base, token = str((row.values or {}).get("base_url") or "").strip().rstrip("/"), str((row.values or {}).get("admin_token") or "").strip()
    return ShortenerConfig(base, token) if base and token else None


def _require(session: Session) -> ShortenerConfig:
    cfg = load_config(session)
    if cfg is None:
        raise ShortenerError("encurtador de links não configurado (Integrações → Encurtador de links)")
    if not cfg.base_url.startswith("https://"):
        raise ShortenerError("o endereço do encurtador precisa ser https")
    return cfg


def _call(cfg: ShortenerConfig, method: str, path: str, **kwargs) -> dict:
    try:
        response = requests.request(method, f"{cfg.base_url}{path}", headers={"Authorization": f"Bearer {cfg.admin_token}"},
                                    timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise ShortenerError(f"sem conexão com o encurtador: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code == 401:
        raise ShortenerError("o encurtador recusou o token (confira o token em Integrações)")
    if not response.ok:
        raise ShortenerError(f"encurtador: {body.get('error') or f'HTTP {response.status_code}'}")
    return body


def check(cfg: ShortenerConfig) -> str:
    _call(cfg, "GET", "/api/links/ping")
    return f"conectado a {cfg.base_url}"


def _new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def create_tracked_link(
    session: Session, *, portfolio_item_id: int | None = None, product_id: int | None = None,
    channel: str = "outro", campaign: str | None = None,
) -> AffiliateLink:
    """Cria (ou reaproveita) o link curto de um produto para um canal. Devolve o `AffiliateLink`.

    Só encurta o **link de afiliado** do produto: encurtar o link comum faria a divulgação render clique e
    nenhuma comissão. Mesmo produto + canal + campanha reaproveita o link que já existe.
    """
    cfg = _require(session)
    item = session.get(PortfolioItem, portfolio_item_id) if portfolio_item_id else None
    if portfolio_item_id and item is None:
        raise ShortenerError(f"item de portfólio {portfolio_item_id} não encontrado")
    product = session.get(Product, item.product_id if item else product_id)
    if product is None:
        raise ShortenerError("produto não encontrado")
    channel = (channel or "outro").strip().lower()
    if channel not in CHANNELS:
        raise ShortenerError(f"canal inválido: {channel}. Use um de {', '.join(CHANNELS)}")
    campaign = (campaign or "").strip()[:128] or None
    if not (product.affiliate_url or "").startswith("https://"):
        raise ShortenerError(
            "este produto não tem link de afiliado https: encurtar o link comum geraria clique sem comissão. "
            "Atualize o catálogo ou gere o link de afiliado no marketplace.")

    existing = session.scalar(select(AffiliateLink).where(
        AffiliateLink.product_id == product.id, AffiliateLink.channel == channel,
        AffiliateLink.campaign.is_(None) if campaign is None else AffiliateLink.campaign == campaign,
        AffiliateLink.is_active.is_(True), AffiliateLink.affiliate_url.like(f"{cfg.base_url}/r/%")))
    if existing is not None:
        return existing

    for _ in range(6):
        code = _new_code()
        if session.scalar(select(AffiliateLink.id).where(AffiliateLink.short_code == code)):
            continue
        try:
            _call(cfg, "POST", "/api/links", json={"code": code, "url": product.affiliate_url})
        except ShortenerError as exc:
            if "já existe" in str(exc):
                continue  # colisão no lado público: sorteia outro
            raise
        link = AffiliateLink(
            product_id=product.id, portfolio_item_id=item.id if item else None, marketplace=product.marketplace,
            channel=channel, destination_url=product.affiliate_url, affiliate_url=f"{cfg.base_url}/r/{code}",
            short_code=code, campaign=campaign)
        session.add(link)
        session.flush()
        return link
    raise ShortenerError("não consegui gerar um código livre; tente de novo")


def sync_clicks(session: Session) -> dict:
    """Traz os cliques novos do redirecionador. Idempotente: cada clique tem id único (`external_click_id`)."""
    cfg = _require(session)
    today = datetime.now(UTC).date()
    cursor_row = session.scalar(select(AppSetting).where(AppSetting.key == CURSOR_KEY))
    first = session.scalar(select(func.min(AffiliateLink.created_at)).where(AffiliateLink.affiliate_url.like(f"{cfg.base_url}/r/%")))
    if cursor_row and cursor_row.value.get("since"):
        since = datetime.fromisoformat(cursor_row.value["since"]).date() - timedelta(days=1)  # 1 dia de folga: o dedupe cobre o resto
    elif first:
        since = (first if first.tzinfo else first.replace(tzinfo=UTC)).date()
    else:
        return {"new_clicks": 0, "links": 0, "truncated": False, "note": "ainda não há links rastreados"}
    since = max(since, today - timedelta(days=60))

    data = _call(cfg, "GET", "/api/links/clicks", params={"since": since.isoformat(), "until": today.isoformat()})
    events = data.get("events") or []
    codes = {e["code"] for e in events}
    links = {l.short_code: l for l in session.scalars(select(AffiliateLink).where(AffiliateLink.short_code.in_(codes)))} if codes else {}
    ids = [e["id"] for e in events if e.get("code") in links]
    known = set(session.scalars(select(ClickEvent.external_click_id).where(ClickEvent.external_click_id.in_(ids)))) if ids else set()

    new = 0
    for event in events:
        link = links.get(event.get("code"))
        if link is None or event["id"] in known:
            continue
        session.add(ClickEvent(
            affiliate_link_id=link.id, portfolio_item_id=link.portfolio_item_id,
            occurred_at=datetime.fromisoformat(event["t"].replace("Z", "+00:00")), external_click_id=event["id"],
            channel=link.channel, referrer=(event.get("referrer") or None), country=(event.get("country") or None),
            device=(event.get("device") or None)))
        link.clicks_total = (link.clicks_total or 0) + 1
        new += 1
    session.flush()

    for item_id in {l.portfolio_item_id for l in links.values() if l.portfolio_item_id}:
        item = session.get(PortfolioItem, item_id)
        item.clicks_total = session.scalar(select(func.count()).select_from(ClickEvent).where(ClickEvent.portfolio_item_id == item_id)) or 0

    truncated = bool(data.get("truncated"))
    # Se o redirecionador cortou a lista (5.000 eventos), não avança o cursor: o próximo sync continua de onde parou.
    if not truncated:
        if cursor_row is None:
            cursor_row = AppSetting(key=CURSOR_KEY, value={})
            session.add(cursor_row)
        cursor_row.value = {"since": today.isoformat()}
        cursor_row.changed_at = datetime.now(UTC)
    session.flush()
    return {"new_clicks": new, "links": len(links), "truncated": truncated}


def list_links(session: Session, *, portfolio_item_id: int | None = None, product_id: int | None = None) -> list[dict]:
    stmt = select(AffiliateLink).where(AffiliateLink.is_active.is_(True)).order_by(AffiliateLink.id.desc()).limit(200)
    if portfolio_item_id:
        stmt = stmt.where(AffiliateLink.portfolio_item_id == portfolio_item_id)
    if product_id:
        stmt = stmt.where(AffiliateLink.product_id == product_id)
    out = []
    for link in session.scalars(stmt):
        product = session.get(Product, link.product_id) if link.product_id else None
        out.append({
            "id": link.id, "short_url": link.affiliate_url, "code": link.short_code, "channel": link.channel,
            "campaign": link.campaign, "clicks": link.clicks_total or 0, "product_id": link.product_id,
            "portfolio_item_id": link.portfolio_item_id, "product_title": product.title if product else None,
            "created_at": link.created_at.isoformat() if link.created_at else None,
        })
    return out
