"""Slideshow vertical: ordem das imagens, comando do ffmpeg e (se houver ffmpeg) um vídeo de verdade.

* cada imagem vira 1080x1920 sobre o próprio fundo desfocado (nada esticado);
* o comando faz N-1 transições, soma a duração certa e leva áudio mudo;
* sem foto do produto, usa os outros formatos do criativo; sem imagem nenhuma, recusa.
"""
from __future__ import annotations

import io
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.db  # noqa: F401
from core.db import Base
from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.db.creatives import CreativeCampaign
from core.services import aistudio, reels

NOW = datetime.now(UTC)


def _img(w, h, color):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


@pytest.fixture(autouse=True)
def reels_home(tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_DIR", str(tmp_path / "reels"))


def _creative(session, images=None):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x",
                          external_id="p1", collected_at=NOW)
    session.add(source)
    session.flush()
    product = Product(marketplace=Marketplace.SHOPEE, external_id="p1", title="Garrafa", price=50.0, images=images, source_record_id=source.id,
                      first_seen_at=NOW, last_seen_at=NOW)
    session.add(product)
    session.flush()
    manifest = {"deliverables": [
        {"id": "a", "kind": "image", "status": "ready", "aspect_ratio": "4:5", "url_signed": {"href": "https://s/a"}},
        {"id": "b", "kind": "image", "status": "ready", "aspect_ratio": "9:16", "url_signed": {"href": "https://s/b"}},
    ]}
    c = CreativeCampaign(product_id=product.id, external_ref="mural-p1", campaign_id="c", mode="live", status="completed", quality="economy",
                         budget_usd=1.0, manifest=manifest)
    session.add(c)
    session.flush()
    return c


@pytest.fixture
def files(monkeypatch):
    data = {"a": _img(1080, 1350, "red"), "b": _img(1080, 1920, "navy")}
    monkeypatch.setattr(aistudio, "fetch_file", lambda session, creative, dlv: (data[dlv], "image/png"))
    return data


def test_canvas_is_always_1080x1920_and_keeps_the_whole_image():
    for size in ((800, 800), (1080, 1350), (500, 1600), (3000, 1000)):
        out = Image.open(io.BytesIO(reels.canvas(_img(*size, "green"))))
        assert out.size == (1080, 1920) and out.format == "JPEG"


def test_command_has_n_minus_1_transitions_right_duration_and_silent_audio(tmp_path):
    slides = [tmp_path / f"s{i}.jpg" for i in range(5)]
    cmd = reels.command("ffmpeg", slides, tmp_path / "o.mp4")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph.count("xfade") == 4 and cmd[cmd.index("-t") + 1] == "13.0"  # 5 x 3 s - 4 x 0,5 s
    assert any("anullsrc" in c for c in cmd) and f"{len(slides)}:a" in cmd
    assert "offset=2.5" in graph and "offset=10.0" in graph
    with pytest.raises(reels.ReelError):
        reels.command("ffmpeg", slides[:1], tmp_path / "o.mp4")


def test_order_is_creative_then_photos_then_creative_again(session, files):
    c = _creative(session, images=["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg", "https://x/4.jpg", "https://x/5.jpg", "https://x/ruim"])
    photos = {f"https://x/{i}.jpg": _img(600, 600, "yellow") for i in range(1, 6)}
    got = reels.collect(session, c, download=lambda url: photos.get(url))
    assert len(got) == 6 and got[0] == files["b"] == got[-1] and got[1:-1] == [photos[f"https://x/{i}.jpg"] for i in range(1, 5)]  # no máximo 4 fotos


def test_without_product_photos_it_uses_the_other_creative_formats(session, files):
    c = _creative(session, images=None)
    got = reels.collect(session, c, download=lambda url: None)
    assert got == [files["b"], files["a"], files["b"]]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg nesta máquina")
def test_a_real_video_is_made_with_the_right_size_and_duration(session, files):
    c = _creative(session, images=["https://x/1.jpg", "https://x/2.jpg"])
    info = reels.build(session, c.id, download=lambda url: _img(800, 600, "orange"))
    path = reels.reel_path(c.id)
    assert info["slides"] == 4 and info["seconds"] == 10.5 and path.exists() and path.stat().st_size > 1000
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_name:format=duration", "-of", "default=nw=1", str(path)],
                           capture_output=True, text=True)
    assert "width=1080" in probe.stdout and "height=1920" in probe.stdout and "codec_name=h264" in probe.stdout and "codec_name=aac" in probe.stdout
    assert abs(float(probe.stdout.split("duration=")[-1].split()[0]) - 10.5) < 0.6
