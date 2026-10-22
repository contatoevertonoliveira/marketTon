"""Vitrine pública "Achados do Felix": o que vai para a loja, como se monta e como se publica.

O marketTon roda no computador do operador, que a internet não alcança. A loja pública vive no Netlify
(`loja.felixsystems.com.br`) e **recebe uma fotografia do catálogo**: aqui se monta essa fotografia e se envia a
`/api/loja/publicar`. Assim a loja continua no ar com o computador desligado, e nada de interno vaza.

O que vai para a loja pública (e só isso): nome, foto, preço de referência com a data em que foi visto, marketplace,
categoria, texto curto e **o link** (o link curto rastreado, que conta o clique; sem o encurtador, o link de afiliado
direto). **Nunca** vão comissão, custo, pontuação, estado do portfólio nem identificadores internos.

Quem entra: todo item do portfólio (menos os pausados) mais o que o operador acrescentou à mão, descontando o que
ele ocultou. Produto sem link de afiliado https ou sem foto não entra — e a tela diz por quê.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.app_settings import AppSetting
from core.db.catalog import Product
from core.db.portfolio import PortfolioItem, PortfolioState
from core.db.service_credentials import ServiceCredential
from core.db.storefront import StorefrontItem
from core.db.tracking import AffiliateLink
from core.services import link_shortener

logger = logging.getLogger(__name__)

SERVICE = "storefront"
LAST_PUBLISH_KEY = "storefront_last_publish"
META_KEY = "storefront_meta"
CHANNEL = "vitrine"  # canal dos links curtos da loja: cliques da loja aparecem separados dos das redes
TIMEOUT = 30

DEFAULT_NAME = "Achados do Felix"
DEFAULT_TAGLINE = "Achados que valem o clique, escolhidos a dedo na Shopee e no Mercado Livre."
DISCLOSURE = (
    "O Achados do Felix participa dos programas de afiliados da Shopee e do Mercado Livre e pode receber uma comissão "
    "pelas compras feitas pelos links desta página, sem custo extra para você. A compra, o pagamento e a entrega são "
    "feitos no marketplace. Preços e disponibilidade são os vistos no dia indicado e podem mudar: confira antes de comprar."
)

CATEGORIES = ("Casa e cozinha", "Moda fitness", "Pet", "Eletrônicos", "Beleza", "Achados diversos")
MARKETPLACE_NAMES = {"shopee": "Shopee", "mercado_livre": "Mercado Livre"}
# A ordem importa: a primeira regra que casar vence ("tapete higiênico para cachorro" é Pet, não Casa).
_CATEGORY_RULES = (
    ("Pet", ("cachorro", "cão", "gato", "pet", "coleira", "ração", "petisco", "arranhador")),
    ("Beleza", ("unha", "maquiagem", "cabelo", "creme", "batom", "esmalte", "skincare", "perfume", "hidratante")),
    ("Eletrônicos", ("fone", "bluetooth", "carregador", "smartwatch", "cabo ", "caixa de som", "usb", "câmera", "mouse")),
    ("Moda fitness", ("legging", "fitness", "academia", "short", "top ", "treino", "camiseta", "calça", "bermuda", "tênis", "tenis", "sapato")),
    ("Casa e cozinha", ("copo", "garrafa", "térmic", "panela", "cozinha", "tapete", "organizador", "luminária", "pote", "prato")),
)


class StorefrontError(RuntimeError):
    """Falha da vitrine. A mensagem é segura para exibir ao operador."""


@dataclass
class StoreConfig:
    base_url: str  # onde estão as funções (felixsystems.com.br)
    admin_token: str
    public_url: str  # endereço que o público abre


# ------------------------------------------------------------------- configuração ---------


def load_config(session: Session) -> StoreConfig | None:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == SERVICE))
    if row is None or not row.enabled:
        return None
    values = row.values or {}
    base = str(values.get("base_url") or "").strip().rstrip("/")
    token = str(values.get("admin_token") or "").strip()
    if not base or not token:
        return None
    public = str(values.get("public_url") or "").strip().rstrip("/") or f"{base}/loja"
    return StoreConfig(base, token, public)


def _require(session: Session) -> StoreConfig:
    cfg = load_config(session)
    if cfg is None:
        raise StorefrontError("a vitrine não está configurada: preencha Integrações > Vitrine pública (endereço e token).")
    if not cfg.base_url.startswith("https://"):
        raise StorefrontError("o endereço da vitrine precisa ser https")
    return cfg


def _call(cfg: StoreConfig, method: str, path: str, **kwargs) -> dict:
    try:
        response = requests.request(method, f"{cfg.base_url}{path}", headers={"Authorization": f"Bearer {cfg.admin_token}"},
                                    timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise StorefrontError(f"sem conexão com a vitrine: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code == 401:
        raise StorefrontError("a vitrine recusou o token (confira o token em Integrações)")
    if not response.ok:
        raise StorefrontError(f"vitrine: {body.get('error') or f'HTTP {response.status_code}'}")
    return body


def check(cfg: StoreConfig) -> str:
    _call(cfg, "GET", "/api/loja/ping")
    return f"conectado a {cfg.base_url}"


def get_meta(session: Session) -> dict:
    row = session.scalar(select(AppSetting).where(AppSetting.key == META_KEY))
    value = row.value if row else {}
    return {"name": (value.get("name") or DEFAULT_NAME)[:60], "tagline": (value.get("tagline") or DEFAULT_TAGLINE)[:200]}


def set_meta(session: Session, *, name: str | None, tagline: str | None, actor: str) -> dict:
    row = session.scalar(select(AppSetting).where(AppSetting.key == META_KEY))
    if row is None:
        row = AppSetting(key=META_KEY, value={})
        session.add(row)
    value = dict(row.value or {})
    if name is not None:
        value["name"] = name.strip()[:60]
    if tagline is not None:
        value["tagline"] = tagline.strip()[:200]
    row.value, row.updated_by, row.changed_at = value, actor[:64], datetime.now(UTC)
    session.flush()
    return get_meta(session)


# --------------------------------------------------------------------- catálogo ------------


def guess_category(title: str | None) -> str:
    text = f" {(title or '').lower()} "
    for category, words in _CATEGORY_RULES:
        if any(w in text for w in words):
            return category
    return "Achados diversos"


def clean_title(title: str | None, limit: int = 84) -> str:
    text = re.sub(r"\s+", " ", title or "").strip(" -–|")
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;-–|")
    return f"{cut}…"


def _first_image(product: Product) -> str | None:
    for image in product.images or []:
        if isinstance(image, str) and image.startswith("https://"):
            return image
    return None


def _eligibility(product: Product, row: StorefrontItem | None, state: PortfolioState | None) -> str | None:
    """`None` se o produto pode ir para a loja; senão o motivo, em português."""
    if row is not None and row.hidden:
        return "oculto na vitrine"
    if state == PortfolioState.PAUSED:
        return "pausado no portfólio"
    if not product.is_active:
        return "inativo no catálogo"
    if not (product.affiliate_url or "").startswith("https://"):
        return "sem link de afiliado"
    if not _first_image(product):
        return "sem foto"
    return None


def _candidates(session: Session) -> list[tuple[Product, StorefrontItem | None, PortfolioItem | None]]:
    rows = {r.product_id: r for r in session.scalars(select(StorefrontItem))}
    items = {i.product_id: i for i in session.scalars(select(PortfolioItem))}
    ids = set(rows) | set(items)
    products = {p.id: p for p in session.scalars(select(Product).where(Product.id.in_(ids)))} if ids else {}
    out = [(products[i], rows.get(i), items.get(i)) for i in ids if i in products]
    out.sort(key=lambda t: (t[1].position if t[1] else 0, -(t[1].highlight if t[1] else 0), t[0].id))
    return out


def list_admin(session: Session) -> dict:
    """Tudo o que o operador vê na tela de administração da vitrine (inclui o que não pode ser publicado e por quê)."""
    cfg = load_config(session)
    rows = []
    for product, row, item in _candidates(session):
        reason = _eligibility(product, row, item.state if item else None)
        rows.append({
            "product_id": product.id, "portfolio_item_id": item.id if item else None,
            "title": clean_title(product.title, 120), "display_title": row.display_title if row else None,
            "image": _first_image(product), "marketplace": product.marketplace.value,
            "price": product.price, "commission_pct": product.affiliate_commission_pct,
            "category": (row.category if row and row.category else guess_category(product.title)),
            "category_is_guess": not (row and row.category),
            "blurb": row.blurb if row else None, "highlight": bool(row and row.highlight),
            "hidden": bool(row and row.hidden), "position": row.position if row else 0,
            "portfolio_state": item.state.value if item else None,
            "eligible": reason is None, "reason": reason,
        })
    last = session.scalar(select(AppSetting).where(AppSetting.key == LAST_PUBLISH_KEY))
    return {
        "configured": cfg is not None, "public_url": cfg.public_url if cfg else None,
        "meta": get_meta(session), "categories": list(CATEGORIES),
        "last_publish": last.value if last else None, "items": rows,
        "publishable": sum(1 for r in rows if r["eligible"]),
    }


def upsert_item(session: Session, product_id: int, **fields) -> StorefrontItem:
    """Cria ou atualiza o ajuste de um produto. Campos ausentes (`None`) não mudam; texto vazio limpa o campo."""
    product = session.get(Product, product_id)
    if product is None:
        raise StorefrontError(f"produto {product_id} não encontrado")
    row = session.scalar(select(StorefrontItem).where(StorefrontItem.product_id == product_id))
    if row is None:
        row = StorefrontItem(product_id=product_id, highlight=False, hidden=False, position=0)
        session.add(row)
    if "category" in fields and fields["category"] is not None:
        category = str(fields["category"]).strip()
        if category and category not in CATEGORIES:
            raise StorefrontError(f"categoria inválida: {category}. Use uma de {', '.join(CATEGORIES)}")
        row.category = category or None
    for name, limit in (("display_title", 160), ("blurb", 280)):
        if fields.get(name) is not None:
            setattr(row, name, str(fields[name]).strip()[:limit] or None)
    for name in ("highlight", "hidden"):
        if fields.get(name) is not None:
            setattr(row, name, bool(fields[name]))
    if fields.get("position") is not None:
        row.position = max(-999, min(int(fields["position"]), 999))
    session.flush()
    return row


# ------------------------------------------------------------------------ links ------------


def _public_link(session: Session, product: Product, *, create: bool) -> tuple[str, bool]:
    """(link, rastreado). O link curto conta o clique; sem ele cai no link de afiliado direto."""
    cfg = link_shortener.load_config(session)
    if cfg is not None:
        existing = session.scalar(select(AffiliateLink).where(
            AffiliateLink.product_id == product.id, AffiliateLink.channel == CHANNEL, AffiliateLink.campaign.is_(None),
            AffiliateLink.is_active.is_(True), AffiliateLink.affiliate_url.like(f"{cfg.base_url}/r/%")))
        if existing is not None:
            return existing.affiliate_url, True
        if create:
            try:
                return link_shortener.create_tracked_link(session, product_id=product.id, channel=CHANNEL).affiliate_url, True
            except link_shortener.ShortenerError as exc:
                logger.warning("link curto da vitrine não criado (%s): usando o link de afiliado", exc)
    return product.affiliate_url, False


# ---------------------------------------------------------------------- fotografia ---------


def build_snapshot(session: Session, *, create_links: bool = False) -> dict:
    """A fotografia pública do catálogo. `create_links=False` (prévia) não cria links curtos novos."""
    meta = get_meta(session)
    items, skipped = [], []
    for product, row, item in _candidates(session):
        reason = _eligibility(product, row, item.state if item else None)
        if reason:
            if reason != "oculto na vitrine":
                skipped.append({"product_id": product.id, "title": clean_title(product.title, 60), "reason": reason})
            continue
        url, tracked = _public_link(session, product, create=create_links)
        price, original = product.price, product.original_price
        seen = product.last_seen_at.date().isoformat() if product.last_seen_at else None
        items.append({
            "id": f"p{product.id}",
            "title": (row.display_title if row and row.display_title else clean_title(product.title)),
            "image": _first_image(product),
            "marketplace": product.marketplace.value,
            "marketplace_name": MARKETPLACE_NAMES.get(product.marketplace.value, product.marketplace.value),
            "category": row.category if row and row.category else guess_category(product.title),
            "blurb": row.blurb if row and row.blurb else None,
            "price": round(float(price), 2) if price else None,
            "original_price": round(float(original), 2) if price and original and original > price else None,
            "price_date": seen,
            "rating": round(float(product.rating), 1) if product.rating else None,
            "sold": product.sold_quantity if product.sold_quantity else None,
            "highlight": bool(row and row.highlight),
            "url": url,
            "tracked": tracked,
        })
    counts: dict[str, int] = {}
    for it in items:
        counts[it["category"]] = counts.get(it["category"], 0) + 1
    return {
        "version": 1, "generated_at": datetime.now(UTC).isoformat(),
        "store": {**meta, "disclosure": DISCLOSURE},
        "categories": [{"name": c, "count": counts[c]} for c in CATEGORIES if c in counts],
        "items": items, "skipped": skipped,
    }


def publish(session: Session, *, actor: str) -> dict:
    cfg = _require(session)
    snapshot = build_snapshot(session, create_links=True)
    if not snapshot["items"]:
        raise StorefrontError("nenhum produto pronto para a loja: confira os motivos na lista (sem link de afiliado, sem foto…)")
    skipped = snapshot.pop("skipped")
    _call(cfg, "POST", "/api/loja/publicar", json=snapshot)
    result = {"at": datetime.now(UTC).isoformat(), "count": len(snapshot["items"]), "by": actor,
              "untracked": sum(1 for i in snapshot["items"] if not i["tracked"])}
    row = session.scalar(select(AppSetting).where(AppSetting.key == LAST_PUBLISH_KEY))
    if row is None:
        row = AppSetting(key=LAST_PUBLISH_KEY, value={})
        session.add(row)
    row.value, row.updated_by, row.changed_at = result, actor[:64], datetime.now(UTC)
    session.flush()
    return {**result, "skipped": skipped, "public_url": cfg.public_url}
