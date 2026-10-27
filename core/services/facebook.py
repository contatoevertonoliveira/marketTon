"""Publicar na Página do Facebook do Mural na Web (foto e Reel), como par do post do Instagram.

Mesmo caminho do Instagram: o Facebook busca a imagem ou o vídeo por um link público assinado do marketTon. A legenda do Facebook **tem link clicável**,
então leva o endereço da página do produto (com marcação da origem) em vez de "link na bio". Falha aqui não derruba o post do Instagram: fica no
histórico (`social_posts`, plataforma `facebook`).
"""
from __future__ import annotations

import logging
import re
import time

import requests
from sqlalchemy.orm import Session

from core.db.catalog import Product
from core.db.creatives import CreativeCampaign
from core.db.social import SocialPost
from core.services import aistudio, instagram, meta_ads, meta_campaigns, reels, storefront

logger = logging.getLogger(__name__)
TIMEOUT = 60


class FacebookError(RuntimeError):
    """Falha ao publicar na Página. A mensagem é segura para exibir."""


def caption(session: Session, creative_id: int) -> str:
    """Texto do Facebook: o do Instagram, com o link do produto clicável no lugar de "link na bio"."""
    base = instagram.default_caption(session, creative_id)["caption"]
    creative = session.get(CreativeCampaign, creative_id)
    product = session.get(Product, creative.product_id) if creative and creative.product_id else None
    cfg = storefront.load_config(session)
    if not (cfg and product):
        return base
    link = f"{cfg.public_url}/p/p{product.id}?utm_source=facebook&utm_medium=organic&utm_campaign=mural-{creative.external_ref}"[:300]
    return re.sub(r"👉 Link na bio: \S+", f"👉 Veja aqui: {link}", base, count=1)


def _page(session: Session) -> tuple[str, str]:
    values = meta_campaigns._meta_values(session)
    try:
        token = meta_campaigns._page_token(session)
    except meta_campaigns.AdsError as exc:
        raise FacebookError(str(exc)) from exc
    return values["page_id"], token


def _check(response: requests.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        raise FacebookError(f"o Facebook recusou ({err.get('code', response.status_code)}): {str(err.get('error_user_msg') or err.get('message') or 'erro')[:240]}")
    return body


def _post(endpoint: str, token: str, **data) -> dict:
    try:
        return _check(requests.post(endpoint, data={"access_token": token, **data}, timeout=TIMEOUT))
    except requests.RequestException as exc:
        raise FacebookError(f"sem conexão com o Facebook: {exc}") from exc


def _upload(endpoint: str, token: str, file_url: str) -> dict:
    """Envio do vídeo do Reel: o Facebook baixa o arquivo do link público (cabeçalho `file_url`)."""
    try:
        return _check(requests.post(endpoint, headers={"Authorization": f"OAuth {token}", "file_url": file_url}, timeout=TIMEOUT))
    except requests.RequestException as exc:
        raise FacebookError(f"sem conexão com o Facebook: {exc}") from exc


def _record(session: Session, kind: str, creative: CreativeCampaign, text: str, deliverable_id: str | None, actor: str) -> SocialPost:
    post = SocialPost(platform="facebook", kind=kind, creative_campaign_id=creative.id, product_id=creative.product_id, deliverable_id=deliverable_id,
                      caption=text, status="failed", created_by=actor[:64])
    session.add(post)
    session.flush()
    return post


def publish_photo(session: Session, creative_id: int, *, text: str, deliverable_id: str, actor: str) -> SocialPost:
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None or creative.mode != "live":
        raise FacebookError("só criativo ao vivo pode ser publicado")
    page, token = _page(session)
    post = _record(session, "image", creative, text, deliverable_id, actor)
    try:
        body = _post(f"{meta_ads.GRAPH}/{page}/photos", token, url=instagram.media_url(session, creative_id, deliverable_id), caption=text, published="true")
        post.external_id = str(body.get("post_id") or body.get("id"))
        try:
            post.permalink = meta_ads._get(post.external_id, token, fields="permalink_url").get("permalink_url")
        except meta_ads.MetaError:
            logger.info("sem o link do post %s", post.external_id)
        post.status = "published"
    except (FacebookError, KeyError) as exc:
        post.error = str(exc)[:500]
        session.flush()
        raise FacebookError(str(exc)) from exc
    session.flush()
    return post


def publish_reel(session: Session, creative_id: int, *, text: str, actor: str, wait_s: float = 180.0, sleep=time.sleep) -> SocialPost:
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None or creative.mode != "live":
        raise FacebookError("só criativo ao vivo pode ser publicado")
    if not reels.reel_path(creative_id).exists():
        raise FacebookError("gere o slideshow antes de publicar o Reel.")
    page, token = _page(session)
    post = _record(session, "reel", creative, text, None, actor)
    try:
        start = _post(f"{meta_ads.GRAPH}/{page}/video_reels", token, upload_phase="start")
        video_id, upload_url = start["video_id"], start["upload_url"]
        # O arquivo vai por link público: o Facebook baixa do marketTon.
        _upload(upload_url, token, instagram.video_url(session, creative_id))
        waited = 0.0
        while True:
            info = meta_ads._get(video_id, token, fields="status")
            phase = ((info.get("status") or {}).get("uploading_phase") or {}).get("status")
            if phase == "complete":
                break
            if phase == "error" or waited >= wait_s:
                raise FacebookError("o Facebook não conseguiu receber o vídeo" if phase == "error" else "o Facebook demorou demais para receber o vídeo")
            sleep(5)
            waited += 5
        _post(f"{meta_ads.GRAPH}/{page}/video_reels", token, video_id=video_id, upload_phase="finish", video_state="PUBLISHED", description=text)
        post.external_id = str(video_id)
        try:
            link = str(meta_ads._get(video_id, token, fields="permalink_url").get("permalink_url") or "")
            post.permalink = link if link.startswith("http") else f"https://www.facebook.com{link}"
        except meta_ads.MetaError:
            logger.info("sem o link do reel %s", video_id)
        post.status = "published"
    except (FacebookError, meta_ads.MetaError, KeyError) as exc:
        post.error = str(exc)[:500]
        session.flush()
        raise FacebookError(str(exc) if isinstance(exc, FacebookError) else f"falha ao publicar: {exc}") from exc
    session.flush()
    return post


def first_image(session: Session, creative_id: int) -> str | None:
    creative = session.get(CreativeCampaign, creative_id)
    pieces = [d for d in aistudio.deliverables(creative) if d.get("kind") == "image"] if creative else []
    pick = next((d for d in pieces if d.get("aspect_ratio") == "4:5"), pieces[0] if pieces else None)
    return pick["id"] if pick else None
