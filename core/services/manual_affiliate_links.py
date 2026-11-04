"""Links de afiliado colados à mão (Mercado Livre e Amazon), porque esses programas não têm API pública para gerar o link.

No Mercado Livre o link de afiliado sai do "Gerador de link" do painel de Afiliados (um endereço `mercadolivre.com/sec/...`, `meli.la/...`): o
operador cola o endereço do produto, copia o link gerado e cola aqui. O sistema guarda o link no produto; a coleta seguinte não o apaga (a coleta
só sobrescreve campos que vêm preenchidos). Com o link, o produto passa a valer para anúncio direto e para o link rastreado.

Nada é gerado nem raspado por código: o painel do marketplace exige o login do operador, e automatizar esse login seria exatamente o que não se faz.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.catalog import Product

# Endereços que um link de afiliado de cada marketplace pode ter. Qualquer outro é recusado: colar o link errado geraria clique sem comissão.
ALLOWED_HOSTS: dict[str, tuple[str, ...]] = {
    "mercado_livre": ("mercadolivre.com", "mercadolivre.com.br", "meli.la", "mercadolibre.com"),
    "amazon": ("amzn.to", "amazon.com.br", "amzn.com"),
}
_ML_ID = re.compile(r"MLB-?(\d{6,})", re.I)


class AffiliateLinkError(ValueError):
    """Link ou produto inválido; a mensagem é segura para exibir."""


def _host_ok(marketplace: str, url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS.get(marketplace, ()))


def validate_link(marketplace: str, url: str) -> str:
    url = (url or "").strip()
    if marketplace not in ALLOWED_HOSTS:
        raise AffiliateLinkError(f"{marketplace}: o link de afiliado deste marketplace vem da API dele, não é colado à mão.")
    if not url.startswith("https://") or len(url) > 4000:
        raise AffiliateLinkError("o link de afiliado precisa começar com https://")
    if not _host_ok(marketplace, url):
        raise AffiliateLinkError(f"o endereço não é de um link de afiliado do marketplace ({', '.join(ALLOWED_HOSTS[marketplace])}).")
    return url


def set_affiliate_url(session: Session, product_id: int, url: str) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise AffiliateLinkError(f"produto {product_id} não encontrado")
    product.affiliate_url = validate_link(product.marketplace.value, url)
    session.flush()
    return product


def _find_product(session: Session, marketplace: str, product_url: str) -> Product | None:
    """Acha o produto pelo código do anúncio no endereço (MLB…) ou pelo endereço sem parâmetros."""
    ids = {m.replace("-", "") for m in re.findall(r"MLB-?\d{6,}", product_url, re.I)}
    bare = product_url.split("?")[0].split("#")[0].rstrip("/")
    for p in session.scalars(select(Product).where(Product.marketplace == marketplace)):
        ext = (p.external_id or "").upper().replace("-", "")
        if ext and ext in {i.upper() for i in ids}:
            return p
        if p.product_url and p.product_url.split("?")[0].rstrip("/") == bare:
            return p
        if ids and p.product_url and any(i.upper() in p.product_url.upper().replace("-", "") for i in ids):
            return p
    return None


def import_links(session: Session, text: str, marketplace: str = "mercado_livre") -> dict:
    """Importa várias linhas `endereço-do-produto  link-de-afiliado` (separadas por espaço, tab, ponto e vírgula ou vírgula)."""
    done, missing, rejected = [], [], []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p for p in re.split(r"[\s;,]+", line) if p]
        if len(parts) != 2:
            rejected.append({"line": line[:160], "reason": "use duas colunas: endereço do produto e link de afiliado"})
            continue
        product_url, link = parts
        try:
            link = validate_link(marketplace, link)
        except AffiliateLinkError as exc:
            rejected.append({"line": line[:160], "reason": str(exc)})
            continue
        product = _find_product(session, marketplace, product_url)
        if product is None:
            missing.append({"product_url": product_url[:160], "reason": "este produto ainda não está no catálogo"})
            continue
        product.affiliate_url = link
        done.append({"product_id": product.id, "title": (product.title or "")[:70], "affiliate_url": link})
    session.flush()
    return {"saved": done, "not_in_catalog": missing, "rejected": rejected}
