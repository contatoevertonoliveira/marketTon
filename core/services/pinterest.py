"""Pinterest do Mural na Web: o pin nasce como RASCUNHO (texto, imagem e link prontos), o operador aprova e só então ele sai.

Ideia (vídeo "Como ganhar dinheiro no Mercado Livre usando IA"): um pin com imagem bonita do produto, título e descrição com palavra-chave
(SEO do Pinterest) e o link de afiliado leva visitas por semanas; quem clica e compra QUALQUER item na sessão rende comissão. Aqui o fluxo é
o do marketTon: produto da vitrine -> rascunho -> aprovação -> publicação -> métricas.

* Regra do operador: tudo que vira publicação nas redes tem que estar na vitrine (`storefront.ensure_listed`).
* O link do pin é a página do produto no Mural (domínio nosso, com UTM) ou o link rastreado direto à compra; escolha no cartão da integração.
* A imagem vai em base64 (não precisa de endereço público). A imagem vem do AI Studio (criativo `image`) ou da foto do produto.
* Sem a chave da API (ou com a chave em teste/sandbox) dá para usar o "kit": a tela entrega imagem, título, descrição, palavras-chave e link
  prontos para você postar à mão no Pinterest.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.db.catalog import Product
from core.db.creatives import CreativeCampaign
from core.db.pinterest import PinterestPin
from core.db.service_credentials import ServiceCredential
from core.db.storefront import StorefrontItem
from core.services import aistudio, categories, instagram, link_shortener, storefront

logger = logging.getLogger(__name__)
SERVICE = "pinterest"
DEFAULT_BASE = "https://api.pinterest.com/v5"
TIMEOUT = 60
TITLE_MAX = 100
DESC_MAX = 800
MIN_GAP = timedelta(minutes=60)  # entre um pin e outro (o Pinterest não gosta de rajada)
DISCLOSURE = "Divulgação: link de afiliado, posso receber comissão se você comprar."
STOP = {"para", "com", "sem", "uma", "uns", "umas", "dos", "das", "que", "por", "mais", "kit", "frete", "gratis", "grátis", "original", "novo", "nova", "de", "do", "da", "em"}


class PinterestError(RuntimeError):
    """Falha ao preparar ou publicar um pin. A mensagem é segura para exibir."""


@dataclass
class PinterestConfig:
    token: str
    base: str = DEFAULT_BASE
    link_mode: str = "page"  # page | direct
    max_per_day: int = 3
    default_board: str = ""

    @property
    def sandbox(self) -> bool:
        return "sandbox" in self.base


def config_from(values: dict) -> PinterestConfig | None:
    token = str((values or {}).get("access_token") or "").strip()
    if not token:
        return None
    mode = str(values.get("link_mode") or "page").strip().lower()
    try:
        cap = int(str(values.get("max_per_day") or "3").strip())
    except ValueError:
        cap = 3
    return PinterestConfig(token, str(values.get("api_base") or DEFAULT_BASE).strip().rstrip("/") or DEFAULT_BASE, mode if mode in ("page", "direct") else "page",
                           max(1, min(cap, 15)), str(values.get("default_board") or "").strip())


def settings(session: Session) -> dict:
    """Preferências que valem mesmo sem a chave da API (modo do link, teto por dia, quadro padrão)."""
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == SERVICE))
    values = dict(row.values or {}) if row and row.enabled else {}
    cfg = config_from({**values, "access_token": values.get("access_token") or "x"})
    return {"link_mode": cfg.link_mode, "max_per_day": cfg.max_per_day, "default_board": cfg.default_board, "api_base": cfg.base,
            "token_set": bool(values.get("access_token")), "sandbox": cfg.sandbox}


def load_config(session: Session) -> PinterestConfig | None:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == SERVICE))
    if row is None or not row.enabled:
        return None
    return config_from(row.values or {})


def _require(session: Session) -> PinterestConfig:
    cfg = load_config(session)
    if cfg is None:
        raise PinterestError("o Pinterest não está conectado: preencha a chave de acesso no cartão Pinterest em Integrações (ou use o kit e poste à mão).")
    return cfg


def _call(cfg: PinterestConfig, method: str, path: str, **kwargs) -> dict:
    try:
        response = requests.request(method, f"{cfg.base}{path}", headers={"Authorization": f"Bearer {cfg.token}"}, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise PinterestError(f"sem conexão com o Pinterest: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        msg = str((body or {}).get("message") or response.text[:200] or "erro")[:240]
        hint = {401: " (chave inválida ou vencida)", 403: " (a chave não tem a permissão pins:write/boards:write, ou o app ainda está em teste)",
                429: " (limite de chamadas: tente mais tarde)"}.get(response.status_code, "")
        raise PinterestError(f"o Pinterest recusou ({response.status_code}){hint}: {msg}")
    return body if isinstance(body, dict) else {}


def check(values: dict) -> str:
    cfg = config_from(values)
    if cfg is None:
        raise PinterestError("falta a chave de acesso do Pinterest.")
    info = _call(cfg, "GET", "/user_account")
    who = info.get("username") or info.get("account_type") or "conta"
    env = "SANDBOX (os pins de teste só você vê)" if cfg.sandbox else "produção"
    return f"Conectado ao Pinterest como {who} · modo {env} · link do pin: {'página do Mural' if cfg.link_mode == 'page' else 'link rastreado direto'}."


def boards(cfg: PinterestConfig) -> list[dict]:
    out, bookmark = [], None
    for _ in range(5):
        data = _call(cfg, "GET", "/boards", params={"page_size": 100, **({"bookmark": bookmark} if bookmark else {})})
        out += [{"id": b["id"], "name": b.get("name")} for b in data.get("items", [])]
        bookmark = data.get("bookmark")
        if not bookmark:
            break
    return out


def ensure_board(cfg: PinterestConfig, name: str) -> str:
    for b in boards(cfg):
        if (b["name"] or "").strip().lower() == name.strip().lower():
            return b["id"]
    return _call(cfg, "POST", "/boards", json={"name": name[:50], "privacy": "PUBLIC"})["id"]


# ------------------------------------------------------------------ texto e imagem ---------


def _clean_title(title: str) -> str:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", title or "")  # [Frete Grátis], (Kit com 2)
    t = re.sub(r"[^\w\s%/+\-.,&ªº]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\b20\d\d\b", " ", t)
    return re.sub(r"\s+", " ", t).strip(" -.,")


def _fit(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" -,.;:")
    return cut or text[:limit]


def _keywords(title: str, department: str) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", title)]
    seen, out = set(), []
    for w in [department.lower()] + words:
        if w and w not in STOP and w not in seen and not w.startswith("categoria") and w != "sem categoria":
            seen.add(w)
            out.append(w)
    return out[:8]


def suggest_copy(product: Product, department: str, blurb: str | None = None) -> dict:
    """Texto determinístico e honesto (sem inventar característica): título com a palavra-chave, descrição natural, aviso de divulgação.

    O operador (ou o agente) pode melhorar o texto depois, antes de aprovar."""
    base = _clean_title(product.title) or product.title
    title = _fit(base, TITLE_MAX)
    kws = _keywords(base, department)
    price = f"R$ {float(product.price):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if product.price else ""
    lines = [base + (f" por {price}" if price else "") + "."]
    if blurb:
        lines.append(blurb.strip())
    lines.append("Veja detalhes, fotos e avaliações no link." if not department.startswith(("Categoria", "Sem")) else "Veja detalhes e avaliações no link.")
    tags = " ".join("#" + re.sub(r"\W", "", k) for k in kws[:5])
    desc = _fit(" ".join(lines), DESC_MAX - len(DISCLOSURE) - len(tags) - 4) + f"\n{DISCLOSURE}\n{tags}"
    return {"title": title, "description": desc[:DESC_MAX], "keywords": ", ".join(kws), "alt_text": _fit(f"Foto do produto: {base}", 480)}


def pick_image(session: Session, product: Product) -> tuple[str, int | None]:
    """A melhor imagem: peça `image` pronta de um criativo do produto (2:3 > 4:5 > 9:16 > qualquer); senão a foto do produto."""
    best, rank = None, 99
    order = {"2:3": 0, "4:5": 1, "9:16": 2}
    for c in session.scalars(select(CreativeCampaign).where(CreativeCampaign.product_id == product.id, CreativeCampaign.hidden.is_(False),
                                                           CreativeCampaign.mode == "live", CreativeCampaign.status.in_(("completed", "partial")))
                             .order_by(CreativeCampaign.id.desc())):
        for d in aistudio.deliverables(c):
            if d.get("kind") == "image" and d.get("download"):
                r = order.get(d.get("aspect_ratio"), 5)
                if r < rank:
                    best, rank = (c.id, d["id"]), r
    if best:
        return f"creative:{best[0]}:{best[1]}", best[0]
    photo = next((u for u in (product.images or []) if isinstance(u, str) and u.startswith("https://")), None)
    if not photo:
        raise PinterestError("o produto não tem foto nem imagem de criativo para o pin.")
    return f"product:{photo}", None


def fetch_image(session: Session, image_ref: str) -> bytes:
    kind, _, rest = image_ref.partition(":")
    try:
        if kind == "creative":
            cid, _, did = rest.partition(":")
            creative = session.get(CreativeCampaign, int(cid))
            if creative is None:
                raise PinterestError("o criativo da imagem não existe mais.")
            data, _ = aistudio.fetch_file(session, creative, did)
        else:
            response = requests.get(rest, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.content
    except (aistudio.AIStudioError, requests.RequestException, ValueError) as exc:
        raise PinterestError(f"não consegui baixar a imagem do pin: {exc}") from exc
    return instagram.to_jpeg(data)


# ------------------------------------------------------------------ rascunhos ---------


def _link(session: Session, product: Product, mode: str, pin_id: int) -> str:
    if mode == "direct":
        try:
            return link_shortener.create_tracked_link(session, product_id=product.id, channel="pinterest", campaign=f"pin{pin_id}").affiliate_url
        except link_shortener.ShortenerError as exc:
            raise PinterestError(str(exc)) from exc
    cfg = storefront.load_config(session)
    if cfg is None:
        raise PinterestError("a vitrine não está configurada (preciso do endereço público do Mural).")
    return f"{cfg.public_url}/p/p{product.id}?utm_source=pinterest&utm_medium=organic&utm_campaign=pin{pin_id}"


def candidates(session: Session, limit: int = 10) -> list[Product]:
    """Produtos da vitrine, com link de afiliado e foto, que ainda não têm pin ativo (rascunho, aprovado ou publicado). Destaques primeiro."""
    busy = {pid for (pid,) in session.execute(select(PinterestPin.product_id).where(PinterestPin.status.in_(("draft", "approved", "published"))))}
    rows = session.execute(select(Product, StorefrontItem).join(StorefrontItem, StorefrontItem.product_id == Product.id)
                           .where(StorefrontItem.hidden.is_(False), Product.is_active.is_(True), Product.affiliate_url.like("https://%"))
                           .order_by(StorefrontItem.highlight.desc(), StorefrontItem.position, Product.id)).all()
    out = []
    for product, _item in rows:
        if product.id in busy or not any(isinstance(u, str) and u.startswith("https://") for u in (product.images or [])):
            continue
        out.append(product)
        if len(out) >= limit:
            break
    return out


def create_draft(session: Session, product_id: int, *, actor: str, board: str | None = None, link_mode: str | None = None) -> PinterestPin:
    product = session.get(Product, product_id)
    if product is None:
        raise PinterestError(f"produto {product_id} não encontrado")
    try:
        storefront.ensure_listed(session, product_id, actor=actor)
    except storefront.StorefrontError as exc:
        raise PinterestError(str(exc)) from exc
    cfg = settings(session)
    mode = link_mode or cfg["link_mode"]
    if mode not in ("page", "direct"):
        raise PinterestError("modo do link deve ser page ou direct")
    item = session.scalar(select(StorefrontItem).where(StorefrontItem.product_id == product_id))
    dept = categories.department_name(product.marketplace.value, product.category_id)
    copy = suggest_copy(product, dept, item.blurb if item else None)
    ref, creative_id = pick_image(session, product)
    pin = PinterestPin(product_id=product_id, creative_campaign_id=creative_id, board_name=(board or cfg["default_board"] or (dept if not dept.startswith(("Categoria", "Sem")) else "Achadinhos"))[:120],
                       title=copy["title"], description=copy["description"], alt_text=copy["alt_text"], keywords=copy["keywords"], link_url="pendente", link_mode=mode,
                       image_ref=ref, status="draft", created_by=actor[:64])
    session.add(pin)
    session.flush()
    pin.link_url = _link(session, product, mode, pin.id)
    session.flush()
    return pin


def create_drafts(session: Session, *, actor: str, count: int = 3, product_ids: list[int] | None = None, board: str | None = None) -> list[PinterestPin]:
    ids = product_ids or [p.id for p in candidates(session, count)]
    made, errors = [], []
    for pid in ids[: max(1, min(count if not product_ids else len(product_ids), 20))]:
        try:
            made.append(create_draft(session, pid, actor=actor, board=board))
        except PinterestError as exc:
            errors.append(f"produto {pid}: {exc}")
    if not made and errors:
        raise PinterestError("; ".join(errors)[:480])
    return made


EDITABLE = {"title": TITLE_MAX, "description": DESC_MAX, "alt_text": 500, "keywords": 300, "board_name": 120}


def update(session: Session, pin_id: int, fields: dict) -> PinterestPin:
    pin = _get(session, pin_id)
    if pin.status == "published":
        raise PinterestError("o pin já foi publicado: não dá mais para editar aqui.")
    for key, limit in EDITABLE.items():
        if key in fields and fields[key] is not None:
            value = str(fields[key]).strip()
            if key in ("title", "description", "board_name") and not value:
                raise PinterestError(f"{key} não pode ficar vazio.")
            if len(value) > limit:
                raise PinterestError(f"{key}: no máximo {limit} caracteres.")
            setattr(pin, key, value)
            if key == "board_name":
                pin.board_id = None
    if "scheduled_for" in fields:
        pin.scheduled_for = fields["scheduled_for"]
    session.flush()
    return pin


def _get(session: Session, pin_id: int) -> PinterestPin:
    pin = session.get(PinterestPin, pin_id)
    if pin is None:
        raise PinterestError(f"pin {pin_id} não encontrado")
    return pin


def approve(session: Session, pin_id: int, scheduled_for: datetime | None = None) -> PinterestPin:
    pin = _get(session, pin_id)
    if pin.status not in ("draft", "failed", "approved"):
        raise PinterestError(f"o pin está “{pin.status}”: só rascunho ou pin com erro pode ser aprovado.")
    pin.status, pin.error = "approved", None
    if scheduled_for is not None:
        pin.scheduled_for = scheduled_for
    session.flush()
    return pin


def reject(session: Session, pin_id: int) -> PinterestPin:
    pin = _get(session, pin_id)
    if pin.status == "published":
        raise PinterestError("o pin já foi publicado.")
    pin.status = "rejected"
    session.flush()
    return pin


# ------------------------------------------------------------------ publicar ---------


def published_last_24h(session: Session, now: datetime | None = None) -> int:
    since = (now or datetime.now(UTC)) - timedelta(hours=24)
    return session.scalar(select(func.count()).select_from(PinterestPin).where(PinterestPin.status == "published", PinterestPin.published_at >= since)) or 0


def publish(session: Session, pin_id: int, *, actor: str, now: datetime | None = None) -> PinterestPin:
    """Publica o pin agora (o operador aprovou ou clicou em publicar). Falha deixa o pin como `failed`, com o motivo, e pode ser refeita."""
    pin = _get(session, pin_id)
    if pin.status in ("published", "rejected"):
        raise PinterestError(f"o pin está “{pin.status}”.")
    cfg = _require(session)
    try:
        storefront.ensure_listed(session, pin.product_id, actor=actor)
        image = fetch_image(session, pin.image_ref)
        if not pin.board_id:
            pin.board_id = ensure_board(cfg, pin.board_name)
        body = {"board_id": pin.board_id, "title": pin.title[:TITLE_MAX], "description": pin.description[:DESC_MAX], "link": pin.link_url,
                "media_source": {"source_type": "image_base64", "content_type": "image/jpeg", "data": base64.b64encode(image).decode()}}
        if pin.alt_text:
            body["alt_text"] = pin.alt_text[:500]
        made = _call(cfg, "POST", "/pins", json=body)
    except (PinterestError, storefront.StorefrontError) as exc:
        pin.status, pin.error = "failed", str(exc)[:500]
        session.flush()
        raise PinterestError(str(exc)) from exc
    pin.pinterest_id = str(made.get("id"))
    pin.permalink = f"https://www.pinterest.com/pin/{pin.pinterest_id}/"
    pin.status, pin.error, pin.published_at = "published", None, now or datetime.now(UTC)
    session.flush()
    return pin


def publish_due(session: Session, *, now: datetime | None = None, actor: str = "agendador") -> list[int]:
    """Publica os pins APROVADOS que já podem sair: dentro do teto por dia e com intervalo entre um e outro. Sem a chave, não faz nada."""
    now = now or datetime.now(UTC)
    cfg = load_config(session)
    if cfg is None:
        return []
    done = []
    pending = list(session.scalars(select(PinterestPin).where(PinterestPin.status == "approved", (PinterestPin.scheduled_for.is_(None)) | (PinterestPin.scheduled_for <= now))
                                   .order_by(PinterestPin.scheduled_for, PinterestPin.id)))
    for pin in pending:
        if published_last_24h(session, now) >= cfg.max_per_day:
            break
        last = session.scalar(select(func.max(PinterestPin.published_at)).where(PinterestPin.status == "published"))
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last is not None and now - last < MIN_GAP:
            break
        try:
            publish(session, pin.id, actor=actor, now=now)
            done.append(pin.id)
        except PinterestError as exc:
            logger.warning("pin %s não saiu: %s", pin.id, exc)
    return done


# ------------------------------------------------------------------ métricas ---------


def sync_metrics(session: Session, *, limit: int = 30, now: datetime | None = None) -> int:
    """Lê impressões, salvamentos e cliques dos pins publicados (leitura; ignora o que o Pinterest não devolver)."""
    cfg = load_config(session)
    if cfg is None:
        return 0
    now = now or datetime.now(UTC)
    n = 0
    for pin in session.scalars(select(PinterestPin).where(PinterestPin.status == "published", PinterestPin.pinterest_id.is_not(None))
                               .order_by(PinterestPin.published_at.desc()).limit(limit)):
        start = max(pin.published_at or now - timedelta(days=89), now - timedelta(days=89)).date()
        try:
            data = _call(cfg, "GET", f"/pins/{pin.pinterest_id}/analytics", params={"start_date": start.isoformat(), "end_date": now.date().isoformat(),
                                                                                     "metric_types": "IMPRESSION,SAVE,PIN_CLICK,OUTBOUND_CLICK", "app_types": "ALL"})
        except PinterestError as exc:
            logger.info("métricas do pin %s indisponíveis: %s", pin.id, exc)
            continue
        m = ((data.get("all") or {}).get("summary_metrics")) or ((data.get("all") or {}).get("lifetime_metrics")) or {}
        pin.impressions, pin.saves = int(m.get("IMPRESSION", 0) or 0), int(m.get("SAVE", 0) or 0)
        pin.pin_clicks, pin.outbound_clicks = int(m.get("PIN_CLICK", 0) or 0), int(m.get("OUTBOUND_CLICK", 0) or 0)
        pin.metrics_at = now
        n += 1
    session.flush()
    return n


def out(pin: PinterestPin, product: Product | None = None) -> dict:
    return {"id": pin.id, "product_id": pin.product_id, "product_title": product.title if product else None, "creative_id": pin.creative_campaign_id,
            "board_name": pin.board_name, "title": pin.title, "description": pin.description, "alt_text": pin.alt_text, "keywords": pin.keywords,
            "link_url": pin.link_url, "link_mode": pin.link_mode, "status": pin.status, "scheduled_for": pin.scheduled_for.isoformat() if pin.scheduled_for else None,
            "published_at": pin.published_at.isoformat() if pin.published_at else None, "permalink": pin.permalink, "error": pin.error,
            "image_file": f"/pinterest/pins/{pin.id}/image", "impressions": pin.impressions, "saves": pin.saves, "pin_clicks": pin.pin_clicks,
            "outbound_clicks": pin.outbound_clicks, "created_by": pin.created_by}


def list_pins(session: Session, status: str | None = None, limit: int = 60) -> list[dict]:
    q = select(PinterestPin, Product).join(Product, Product.id == PinterestPin.product_id).order_by(PinterestPin.id.desc()).limit(max(1, min(limit, 200)))
    if status:
        q = q.where(PinterestPin.status == status)
    return [out(p, prod) for p, prod in session.execute(q).all()]
