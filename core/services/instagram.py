"""Publicar no Instagram do Mural na Web (conta profissional ligada à Página), sempre com o **ok do operador**.

* Quem publica é o operador (botão na tela; o agente só prepara o texto). Nada sai sozinho.
* O Instagram busca a imagem por um endereço público: o marketTon serve a peça por um link **assinado e com validade**
  (`/api/public/media/...`), em JPEG (o Instagram só aceita JPEG). A imagem original fica no AI Studio, na rede interna.
* O texto leva o aviso de divulgação (link de afiliado). Legenda do Instagram não tem link clicável: o texto manda para o
  **link da bio** (que deve ser o do Mural) e escreve o endereço.
* Cada tentativa (publicada ou não) fica no histórico (`social_posts`).
"""
from __future__ import annotations

import hashlib
import hmac
import io
import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import get_settings
from core.db.catalog import Product
from core.db.creatives import CreativeCampaign
from core.db.social import SocialPost
from core.services import aistudio, meta_ads, meta_campaigns, storefront

logger = logging.getLogger(__name__)
TIMEOUT = 40
MEDIA_TTL = 3 * 3600
CAPTION_MAX = 2200
HASHTAGS = "#achadinhos #ofertas #shopee #muralnaweb"


class InstagramError(RuntimeError):
    """Falha ao preparar ou publicar no Instagram. A mensagem é segura para exibir."""


# ------------------------------------------------------------------ link público assinado da imagem ---------


def _sig(creative_id: int, deliverable_id: str, exp: int) -> str:
    key = get_settings().jwt_secret_key.encode()
    return hmac.new(key, f"media.{creative_id}.{deliverable_id}.{exp}".encode(), hashlib.sha256).hexdigest()[:40]


def verify_media(creative_id: int, deliverable_id: str, exp: int, sig: str, *, now: float | None = None) -> bool:
    if (now if now is not None else time.time()) > exp:
        return False
    return hmac.compare_digest(_sig(creative_id, deliverable_id, exp), str(sig))


def to_jpeg(data: bytes) -> bytes:
    """O Instagram só aceita JPEG: converte (sem transparência: fundo branco). Sem Pillow, devolve o original."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow está nas dependências
        return data
    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        base = Image.new("RGB", img.size, (255, 255, 255))
        base.paste(img, mask=img.getchannel("A"))
        img = base
    else:
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


def _public_base(session: Session) -> str:
    cfg = aistudio.load_config(session)
    origin = urlparse(cfg.callback_url if cfg else "")
    if not origin.scheme or not origin.netloc:
        raise InstagramError("não sei o endereço público do marketTon (preencha o endereço do webhook no cartão do AI Studio).")
    return f"{origin.scheme}://{origin.netloc}"


def media_url(session: Session, creative_id: int, deliverable_id: str, *, now: float | None = None) -> str:
    exp = int((now if now is not None else time.time()) + MEDIA_TTL)
    return f"{_public_base(session)}/api/public/media/{creative_id}/{deliverable_id}.jpg?exp={exp}&sig={_sig(creative_id, deliverable_id, exp)}"


# ------------------------------------------------------------------ texto ---------


def default_caption(session: Session, creative_id: int) -> dict:
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise InstagramError(f"criativo {creative_id} não encontrado")
    try:
        kit = meta_campaigns.post_kit(session, creative_id)
    except meta_campaigns.AdsError as exc:
        raise InstagramError(str(exc)) from exc
    cfg = storefront.load_config(session)
    site = (cfg.public_url if cfg else "").replace("https://", "")
    body = re.sub(r"\s+", " ", kit["message"]).strip()
    caption = (f"{body}\n\n👉 Link na bio: {site or 'mural.felixsystems.com.br'}\n"
               f"Divulgação: link de afiliado, podemos receber comissão se você comprar.\n\n{HASHTAGS}")
    image = next((d for d in aistudio.deliverables(creative) if d.get("kind") == "image" and d.get("aspect_ratio") == "4:5"), None) \
        or next((d for d in aistudio.deliverables(creative) if d.get("kind") == "image"), None)
    return {"creative_id": creative_id, "caption": caption[:CAPTION_MAX], "deliverable_id": image["id"] if image else None,
            "image_file": image.get("file") if image else None}


# ------------------------------------------------------------------ publicar ---------


def _ig_user(session: Session) -> tuple[str, str]:
    """(id da conta do Instagram, token). A conta vem da Página; sem ela não há o que publicar."""
    values = meta_campaigns._meta_values(session)
    try:
        info = meta_ads._get(values["page_id"], values["access_token"], fields="instagram_business_account")
    except meta_ads.MetaError as exc:
        raise InstagramError(f"não consegui ler a Página: {exc}") from exc
    ig = (info.get("instagram_business_account") or {}).get("id")
    if not ig:
        raise InstagramError("a Página não tem uma conta profissional do Instagram ligada.")
    return ig, values["access_token"]


def _post(path: str, token: str, **data) -> dict:
    try:
        response = requests.post(f"{meta_ads.GRAPH}/{path.lstrip('/')}", data={"access_token": token, **data}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise InstagramError(f"sem conexão com a Meta: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        raise InstagramError(f"o Instagram recusou ({err.get('code', response.status_code)}): {str(err.get('error_user_msg') or err.get('message') or 'erro')[:240]}")
    return body


def publish_image(session: Session, creative_id: int, *, caption: str, deliverable_id: str | None = None, actor: str,
                  wait_s: float = 45.0, sleep=time.sleep) -> SocialPost:
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise InstagramError(f"criativo {creative_id} não encontrado")
    if creative.mode != "live":
        raise InstagramError("criativo de teste (sandbox) não pode ser publicado.")
    caption = (caption or "").strip()
    if not caption or len(caption) > CAPTION_MAX:
        raise InstagramError(f"o texto precisa ter de 1 a {CAPTION_MAX} caracteres.")
    d = deliverable_id or default_caption(session, creative_id)["deliverable_id"]
    if not d or not any(x["id"] == d and x.get("kind") == "image" for x in aistudio.deliverables(creative)):
        raise InstagramError("esse criativo não tem a imagem escolhida.")
    ig, token = _ig_user(session)
    post = SocialPost(platform="instagram", kind="image", creative_campaign_id=creative.id, product_id=creative.product_id, deliverable_id=d,
                      caption=caption, status="failed", created_by=actor[:64])
    session.add(post)
    session.flush()
    try:
        container = _post(f"{ig}/media", token, image_url=media_url(session, creative_id, d), caption=caption)["id"]
        waited = 0.0
        while True:  # o Instagram baixa a imagem e processa: espera ficar pronto
            status = meta_ads._get(container, token, fields="status_code").get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR" or waited >= wait_s:
                raise InstagramError("o Instagram não conseguiu processar a imagem" if status == "ERROR" else "o Instagram demorou demais para processar a imagem")
            sleep(3)
            waited += 3
        made = _post(f"{ig}/media_publish", token, creation_id=container)
        post.external_id = str(made.get("id"))
        try:
            post.permalink = meta_ads._get(post.external_id, token, fields="permalink").get("permalink")
        except meta_ads.MetaError:
            logger.info("sem o link do post %s", post.external_id)
        post.status = "published"
    except (InstagramError, meta_ads.MetaError, KeyError) as exc:
        post.error = str(exc)[:500]
        session.flush()
        raise InstagramError(str(exc) if isinstance(exc, InstagramError) else f"falha ao publicar: {exc}") from exc
    session.flush()
    return post


def out(p: SocialPost) -> dict:
    return {"id": p.id, "platform": p.platform, "kind": p.kind, "creative_id": p.creative_campaign_id, "product_id": p.product_id,
            "caption": p.caption, "status": p.status, "permalink": p.permalink, "error": p.error, "created_by": p.created_by,
            "created_at": p.created_at.isoformat() if p.created_at else datetime.now(UTC).isoformat()}


def list_posts(session: Session, limit: int = 30) -> list[dict]:
    return [out(p) for p in session.scalars(select(SocialPost).order_by(SocialPost.id.desc()).limit(max(1, min(limit, 100))))]


def product_for(session: Session, post: SocialPost) -> Product | None:
    return session.get(Product, post.product_id) if post.product_id else None
