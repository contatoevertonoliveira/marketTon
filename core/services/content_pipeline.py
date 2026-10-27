"""Publicação automática de conteúdo orgânico (Instagram): o agente cria, confere, refaz o que estiver errado e publica, sem o operador.

Quem manda é o operador, por uma chave única (`social_autopublish`). Ligada, o agente pode publicar, mas só passando pelas travas, em código:

* **parecer**: o agente precisa ter registrado `approved` para aquele criativo e tipo (imagem ou Reel) depois de olhar as imagens; um parecer
  `rejected` mais novo bloqueia. O parecer vale 48 h;
* **texto**: precisa ter o aviso de divulgação (link de afiliado) e o endereço do Mural; até 2.200 caracteres;
* **sem repetir**: o mesmo criativo não é publicado duas vezes como o mesmo tipo;
* **teto por dia**: no máximo `max_per_day` publicações (padrão 2), contando as do operador;
* criativo de teste (sandbox) nunca; o dinheiro dos anúncios **não** entra aqui: ligar anúncio continua só do operador.

Cada publicação cai no histórico (`social_posts`) e o agente a registra no relatório.
"""
from __future__ import annotations

import base64
import io
import logging
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.app_settings import AppSetting
from core.db.catalog import Product
from core.db.content_review import CreativeReview
from core.db.creatives import CreativeCampaign
from core.db.social import SocialPost
from core.services import aistudio, instagram, reels, storefront

logger = logging.getLogger(__name__)

KEY = "social_autopublish"
DEFAULTS = {"enabled": False, "max_per_day": 2}
REVIEW_VALID = timedelta(hours=48)
KINDS = ("image", "reel")
CHECKLIST = [
    "Produto fiel à foto real (formato, cor, detalhes); nada inventado nem de outra marca.",
    "Título inteiro e legível, em no máximo 2 linhas, sem cobrir o produto nem a logo.",
    "Preço correto, uma vez só, legível (preço antigo riscado em selo amarelo, se houver).",
    "Logo como carimbo no canto, sem cobrir texto; botão e endereço legíveis; aviso de IA presente.",
    "Nenhuma logo ou marca de terceiros no produto (risco de imitação); sem promessa que não se prove.",
    "Reel: transições suaves, nenhuma imagem cortada ou borrada demais, o criativo abre e fecha.",
]


class ContentError(ValueError):
    """Publicação automática recusada; a mensagem diz o motivo e é segura para exibir."""


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


# --------------------------------------------------------------------- chave e teto ---------


def get_settings(session: Session) -> dict:
    row = session.scalar(select(AppSetting).where(AppSetting.key == KEY))
    saved = (row.value or {}) if row else {}
    return {"enabled": bool(saved.get("enabled", DEFAULTS["enabled"])), "max_per_day": int(saved.get("max_per_day", DEFAULTS["max_per_day"]))}


def set_settings(session: Session, *, enabled: bool, max_per_day: int, actor: str) -> dict:
    if not 1 <= int(max_per_day) <= 6:
        raise ContentError("o teto por dia deve ficar entre 1 e 6 publicações")
    row = session.scalar(select(AppSetting).where(AppSetting.key == KEY))
    if row is None:
        row = AppSetting(key=KEY, value={})
        session.add(row)
    row.value, row.updated_by, row.changed_at = {"enabled": bool(enabled), "max_per_day": int(max_per_day)}, actor[:64], datetime.now(UTC)
    session.flush()
    return get_settings(session)


def published_today(session: Session, now: datetime | None = None) -> int:
    local = (now or datetime.now(UTC)).astimezone()
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return sum(1 for p in session.scalars(select(SocialPost).where(SocialPost.status == "published"))
               if (a := _aware(p.created_at)) is not None and a.astimezone() >= start)


def status(session: Session, now: datetime | None = None) -> dict:
    cfg = get_settings(session)
    return {**cfg, "published_today": published_today(session, now), "posts": instagram.list_posts(session, 8)}


# --------------------------------------------------------------------- parecer ---------


def submit_review(session: Session, creative_id: int, kind: str, verdict: str, notes: str | None, reviewer: str) -> CreativeReview:
    if session.get(CreativeCampaign, creative_id) is None:
        raise ContentError(f"criativo {creative_id} não encontrado")
    if kind not in KINDS or verdict not in ("approved", "rejected"):
        raise ContentError("tipo: image ou reel; parecer: approved ou rejected")
    if verdict == "rejected" and not (notes or "").strip():
        raise ContentError("parecer recusado precisa do motivo (o que está errado)")
    row = CreativeReview(creative_campaign_id=creative_id, kind=kind, verdict=verdict, notes=(notes or "").strip()[:1500] or None, reviewer=reviewer[:64])
    session.add(row)
    session.flush()
    return row


def _latest_review(session: Session, creative_id: int, kind: str) -> CreativeReview | None:
    return session.scalar(select(CreativeReview).where(CreativeReview.creative_campaign_id == creative_id, CreativeReview.kind == kind)
                          .order_by(CreativeReview.id.desc()).limit(1))


# --------------------------------------------------------------------- o que o agente enxerga ---------


def _frames_strip(path: Path) -> bytes:
    """Quatro quadros do vídeo lado a lado (início, 35%, 65% e fim): o suficiente para ver transição e corte sem gastar token."""
    from PIL import Image

    exe, probe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not exe or not probe:
        raise ContentError("o ffmpeg não está disponível para olhar o vídeo")
    dur = float(subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                               capture_output=True, text=True, timeout=30).stdout.strip() or 0)
    frames = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, frac in enumerate((0.05, 0.35, 0.65, 0.93)):
            out = Path(tmp) / f"f{i}.png"
            subprocess.run([exe, "-y", "-loglevel", "error", "-ss", f"{dur * frac:.2f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=270:480", str(out)],
                           capture_output=True, timeout=60)
            if out.exists():
                frames.append(Image.open(out).convert("RGB"))
    if not frames:
        raise ContentError("não consegui tirar quadros do vídeo")
    strip = Image.new("RGB", (270 * len(frames), 480), "white")
    for i, f in enumerate(frames):
        strip.paste(f, (i * 270, 0))
    buf = io.BytesIO()
    strip.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def _downscale(data: bytes, width: int = 720) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    img = img.resize((width, round(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def review_assets(session: Session, creative_id: int) -> dict:
    """Imagens (pequenas) e fatos para o agente conferir o criativo e o slideshow. Só leitura."""
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise ContentError(f"criativo {creative_id} não encontrado")
    product = session.get(Product, creative.product_id) if creative.product_id else None
    pieces = [d for d in aistudio.deliverables(creative) if d.get("kind") == "image"]
    main = next((d for d in pieces if d.get("aspect_ratio") == "4:5"), pieces[0] if pieces else None)
    if main is None:
        raise ContentError("o criativo não tem imagem pronta")
    images = []
    data, _ = aistudio.fetch_file(session, creative, main["id"])
    images.append({"name": "criativo 4:5 (a imagem que vai para o feed)", "jpeg_b64": base64.b64encode(_downscale(data)).decode()})
    reel = reels.reel_path(creative_id)
    if reel.exists():
        images.append({"name": "slideshow: 4 quadros (início, 35%, 65%, fim)", "jpeg_b64": base64.b64encode(_frames_strip(reel)).decode()})
    copy = next((d.get("content") for d in aistudio.deliverables(creative) if d.get("kind") == "copy"), None) or {}
    cfg = storefront.load_config(session)
    return {"creative_id": creative_id, "images": images,
            "facts": {"produto": product.title if product else None, "preco_atual": product.price if product else None,
                      "preco_original": product.original_price if product else None, "marketplace": product.marketplace.value if product else None,
                      "titulo_do_criativo": copy.get("headline"), "texto_do_criativo": copy.get("caption"),
                      "slideshow_pronto": reel.exists(), "foto_original_do_produto": (product.images or [None])[0] if product else None,
                      "site": cfg.public_url if cfg else None, "parecer_anterior": _review_out(_latest_review(session, creative_id, "image")),
                      "o_que_conferir": CHECKLIST}}


def _review_out(r: CreativeReview | None) -> dict | None:
    return None if r is None else {"tipo": r.kind, "parecer": r.verdict, "motivo": r.notes, "quando": _aware(r.created_at).isoformat() if r.created_at else None}


# --------------------------------------------------------------------- fila e publicação ---------


def pending_content(session: Session) -> list[dict]:
    """Criativos ao vivo, prontos e visíveis que ainda não têm post de imagem ou Reel publicado."""
    published = {(p.creative_campaign_id, p.kind) for p in session.scalars(select(SocialPost).where(SocialPost.status == "published"))}
    out = []
    for c in session.scalars(select(CreativeCampaign).where(CreativeCampaign.hidden.is_(False), CreativeCampaign.mode == "live",
                                                            CreativeCampaign.status.in_(("completed", "partial"))).order_by(CreativeCampaign.id.desc())):
        missing = [k for k in KINDS if (c.id, k) not in published]
        if not missing:
            continue
        product = session.get(Product, c.product_id) if c.product_id else None
        out.append({"creative_id": c.id, "product_id": c.product_id, "product": (product.title[:60] if product else None), "missing": missing})
    return out


def check_can_publish(session: Session, creative_id: int, kind: str, caption: str, now: datetime | None = None) -> None:
    cfg = get_settings(session)
    if not cfg["enabled"]:
        raise ContentError("a publicação automática está desligada: o operador liga em Criativos e anúncios.")
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None or creative.mode != "live" or creative.hidden:
        raise ContentError("só dá para publicar criativo ao vivo e visível")
    if kind not in KINDS:
        raise ContentError("tipo: image ou reel")
    if any(p.creative_campaign_id == creative_id and p.kind == kind and p.status == "published" for p in session.scalars(select(SocialPost))):
        raise ContentError("este criativo já foi publicado desse jeito")
    review = _latest_review(session, creative_id, kind)
    if review is None or review.verdict != "approved":
        raise ContentError("falta o seu parecer APROVADO (`creative_review_submit`) depois de olhar as imagens (`creative_review`).")
    when = _aware(review.created_at) or datetime.now(UTC)
    if (now or datetime.now(UTC)) - when > REVIEW_VALID:
        raise ContentError("o parecer tem mais de 48 h: confira de novo e registre outro.")
    text = caption or ""
    store = storefront.load_config(session)
    site = (store.public_url if store else "").replace("https://", "")
    if "afiliado" not in text.lower() or (site and site not in text):
        raise ContentError("o texto precisa do aviso de divulgação (link de afiliado) e do endereço do Mural: use o texto sugerido.")
    if published_today(session, now) >= cfg["max_per_day"]:
        raise ContentError(f"o teto de {cfg['max_per_day']} publicação(ões) por dia já foi atingido: tente amanhã.")


def auto_publish(session: Session, creative_id: int, kind: str, *, caption: str | None, actor: str, now: datetime | None = None) -> SocialPost:
    if kind not in KINDS:
        raise ContentError("tipo: image ou reel")
    try:
        text = caption or instagram.default_caption(session, creative_id)["caption"]
        check_can_publish(session, creative_id, kind, text, now)
        if kind == "image":
            return instagram.publish_image(session, creative_id, caption=text, actor=actor)
        return instagram.publish_reel(session, creative_id, caption=text, actor=actor)
    except instagram.InstagramError as exc:
        raise ContentError(str(exc)) from exc
