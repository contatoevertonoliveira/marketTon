"""Slideshow vertical (Reels, TikTok, Shorts) montado das imagens do produto e do criativo, por código, sem IA e sem custo de crédito.

Ordem: o criativo 9:16 (título, preço e botão) abre; seguem até 4 fotos reais do produto; o criativo fecha. Cada imagem entra em 1080x1920
com o fundo desfocado da própria foto (nada fica esticado nem cortado), com zoom lento e transição suave. 3 s por imagem: 15 a 20 s no total.
Sem texto desenhado por nós (o texto vem do criativo). O vídeo sai com faixa de áudio **muda**: a música é escolhida no app do Instagram/TikTok
(biblioteca comercial), porque a API não deixa escolher música.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests
from sqlalchemy.orm import Session

from core.db.catalog import Product
from core.db.creatives import CreativeCampaign
from core.services import aistudio

logger = logging.getLogger(__name__)

W, H = 1080, 1920
SLIDE_S = 3.0
FADE_S = 0.5
FPS = 30
MAX_PHOTOS = 4
MAX_DOWNLOAD = 8 * 1024 * 1024


class ReelError(RuntimeError):
    """Falha ao montar o vídeo. A mensagem é segura para exibir."""


def reels_dir() -> Path:
    path = Path(os.environ.get("REELS_DIR") or (Path.home() / ".marketton-reels"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def reel_path(creative_id: int) -> Path:
    return reels_dir() / f"creative-{creative_id}.mp4"


def _download(url: str) -> bytes | None:
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException:
        return None
    if not response.ok or "image" not in response.headers.get("Content-Type", "") or len(response.content) > MAX_DOWNLOAD:
        return None
    return response.content


def canvas(data: bytes) -> bytes:
    """A imagem inteira, centralizada em 1080x1920, sobre o fundo desfocado dela mesma. Devolve JPEG."""
    from PIL import Image, ImageEnhance, ImageFilter

    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    cover = max(W / img.width, H / img.height)
    bg = img.resize((round(img.width * cover), round(img.height * cover)))
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.6)
    fit = min(W / img.width, H / img.height)
    fg = img.resize((max(1, round(img.width * fit)), max(1, round(img.height * fit))))
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    out = io.BytesIO()
    bg.save(out, "JPEG", quality=90)
    return out.getvalue()


def command(ffmpeg: str, slides: list[Path], out: Path, *, slide_s: float = SLIDE_S, fade_s: float = FADE_S) -> list[str]:
    """Linha de comando do ffmpeg: zoom lento em cada imagem, transição suave entre elas e áudio mudo."""
    n = len(slides)
    if n < 2:
        raise ReelError("preciso de pelo menos 2 imagens para montar o vídeo")
    frames = int(round(slide_s * FPS))
    parts = [f"[{i}:v]zoompan=z='min(zoom+0.0005,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
             f"setsar=1,format=yuv420p[v{i}]" for i in range(n)]
    last = "v0"
    for i in range(1, n):
        offset = round(i * (slide_s - fade_s), 3)
        parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={fade_s}:offset={offset}[x{i}]")
        last = f"x{i}"
    total = round(n * slide_s - (n - 1) * fade_s, 3)
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for s in slides:
        cmd += ["-i", str(s)]
    cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex", ";".join(parts), "-map", f"[{last}]", "-map", f"{n}:a",
            "-t", str(total), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "23", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)]
    return cmd


def collect(session: Session, creative: CreativeCampaign, *, download=_download) -> list[bytes]:
    """Imagens na ordem do vídeo: criativo 9:16, fotos do produto e o criativo de novo no fim."""
    pieces = [d for d in aistudio.deliverables(creative) if d.get("kind") == "image"]
    if not pieces:
        raise ReelError("o criativo não tem imagem pronta")
    by_ratio = {d.get("aspect_ratio"): d for d in pieces}
    hero = by_ratio.get("9:16") or pieces[0]

    def creative_bytes(d):
        data, _ = aistudio.fetch_file(session, creative, d["id"])
        return data

    hero_bytes = creative_bytes(hero)
    product = session.get(Product, creative.product_id) if creative.product_id else None
    photos = []
    for url in (product.images or [])[:8] if product else []:
        data = download(str(url))
        if data:
            photos.append(data)
        if len(photos) >= MAX_PHOTOS:
            break
    if photos:
        return [hero_bytes, *photos, hero_bytes]
    others = [creative_bytes(d) for d in pieces if d is not hero]  # sem foto do produto: usa os outros formatos do criativo
    return [hero_bytes, *others, hero_bytes] if others else [hero_bytes, hero_bytes]


def build(session: Session, creative_id: int, *, runner=subprocess.run, ffmpeg: str | None = None, download=_download) -> dict:
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise ReelError(f"criativo {creative_id} não encontrado")
    exe = ffmpeg or shutil.which("ffmpeg")
    if not exe:
        raise ReelError("o ffmpeg não está instalado neste servidor")
    images = collect(session, creative, download=download)
    with tempfile.TemporaryDirectory() as tmp:
        slides = []
        for i, data in enumerate(images):
            path = Path(tmp) / f"s{i}.jpg"
            path.write_bytes(canvas(data))
            slides.append(path)
        out = Path(tmp) / "reel.mp4"
        proc = runner(command(exe, slides, out), capture_output=True, text=True, timeout=240)
        if proc.returncode != 0 or not out.exists():
            raise ReelError(f"o ffmpeg falhou: {(proc.stderr or '')[-300:]}")
        final = reel_path(creative_id)
        shutil.move(str(out), final)
    n = len(images)
    return {"creative_id": creative_id, "slides": n, "seconds": round(n * SLIDE_S - (n - 1) * FADE_S, 1), "size_kb": final.stat().st_size // 1024}
