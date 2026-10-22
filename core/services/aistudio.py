"""Cliente do AI Studio (API de Campanhas, contrato v1): criativos de anúncio (vídeos, imagens e textos) para os produtos da vitrine.

Regras (as do contrato e as do operador):

* **Sandbox por padrão.** `mode="live"` gasta créditos de verdade e só é aceito quando o operador liga "Permitir geração ao vivo" no cartão
  do AI Studio; mesmo assim, sempre com `budget.max_usd` dentro do teto do cartão.
* **Idempotente:** `external_ref` e `Idempotency-Key` são gerados antes da chamada e guardados; repetir não duplica gasto.
* **Webhook é o caminho principal** (assinatura HMAC-SHA256 conferida, ±5 min, deduplicado por `event_id`); `refresh()` reconcilia por GET.
* **Nunca** registra a chave de API nem o segredo do webhook em log. O produto vai com a foto real; preço, cupom, CTA e logo são
  aplicados pelo AI Studio na montagem. Alegações proibidas seguem a lista do marketTon.
* Os motores por trás (Kie, Fal…) não importam aqui: não se depende de `engine_summary`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.app_settings import AppSetting
from core.db.catalog import Product
from core.db.creatives import FINAL_STATUSES, CreativeCampaign, CreativeEvent
from core.db.service_credentials import ServiceCredential
from core.services import storefront

logger = logging.getLogger(__name__)

SERVICE = "aistudio"
TIMEOUT = 40
DEFAULT_MAX_USD = 2.0
LOGO_KEY = "aistudio_logo_asset"
LOGO_PATH = Path(__file__).resolve().parents[2] / "docs" / "marca" / "logo.png"
FORBIDDEN_CLAIMS = ["cura", "garantia de resultado", "milagre", "emagrece", "o mais barato", "melhor do Brasil", "100% garantido"]
BANNED_WORDS = ["milagre", "grátis para sempre"]
QUALITIES = ("economy", "standard", "premium")
ANGLES = ("problem_solution", "demo", "comparison", "offer", "unboxing", "ugc_style")


class AIStudioError(RuntimeError):
    """Falha do AI Studio. A mensagem é segura para exibir ao operador."""

    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


@dataclass
class AIStudioConfig:
    base_url: str
    api_key: str
    webhook_secret: str
    callback_url: str
    allow_live: bool
    max_usd: float


def load_config(session: Session) -> AIStudioConfig | None:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == SERVICE))
    if row is None or not row.enabled:
        return None
    v = row.values or {}
    base, key = str(v.get("base_url") or "").strip().rstrip("/"), str(v.get("api_key") or "").strip()
    if not base or not key:
        return None
    try:
        cap = float(str(v.get("max_usd") or DEFAULT_MAX_USD).replace(",", "."))
    except ValueError:
        cap = DEFAULT_MAX_USD
    return AIStudioConfig(base, key, str(v.get("webhook_secret") or "").strip(), str(v.get("callback_url") or "").strip(),
                          str(v.get("allow_live") or "").strip().lower() in ("sim", "s", "yes", "true", "1"), max(0.1, min(cap, 25.0)))


def _require(session: Session) -> AIStudioConfig:
    cfg = load_config(session)
    if cfg is None:
        raise AIStudioError("o AI Studio não está configurado: preencha o cartão em Integrações (endereço e chave) e teste.")
    return cfg


def _call(cfg: AIStudioConfig, method: str, path: str, *, idempotency_key: str | None = None, **kwargs) -> dict:
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        response = requests.request(method, f"{cfg.base_url}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise AIStudioError(f"sem conexão com o AI Studio: {exc}", retryable=True) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code == 401:
        raise AIStudioError("o AI Studio recusou a chave (confira em Integrações)", code="unauthorized")
    if not response.ok:
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        raise AIStudioError(str(err.get("message") or f"HTTP {response.status_code}")[:300], code=err.get("code"),
                            retryable=bool(err.get("retryable")) or response.status_code >= 500 or response.status_code == 429)
    return body


def check(cfg: AIStudioConfig) -> str:
    caps = _call(cfg, "GET", "/capabilities")
    quals = caps.get("qualities") or caps.get("quality") or []
    live = "geração ao vivo LIGADA" if cfg.allow_live else "somente sandbox (sem gasto)"
    return f"conectado ao AI Studio ({live}; teto US$ {cfg.max_usd:g} por campanha" + (f"; qualidades: {', '.join(map(str, quals))}" if quals else "") + ")"


# ------------------------------------------------------------------------------ payload ----------


def ensure_logo_asset(session: Session, cfg: AIStudioConfig) -> str | None:
    """Envia a logo uma vez (`POST /assets`) e guarda o `asset_id`. Sem logo no disco, segue sem ela."""
    row = session.scalar(select(AppSetting).where(AppSetting.key == LOGO_KEY))
    if row and row.value.get("asset_id"):
        return row.value["asset_id"]
    if not LOGO_PATH.exists():
        return None
    body = _call(cfg, "POST", "/assets", files={"file": ("logo.png", LOGO_PATH.read_bytes(), "image/png")})
    asset_id = body.get("asset_id") or body.get("id")
    if asset_id:
        if row is None:
            row = AppSetting(key=LOGO_KEY, value={})
            session.add(row)
        row.value, row.changed_at = {"asset_id": asset_id}, datetime.now(UTC)
        session.flush()
    return asset_id


def build_payload(session: Session, product: Product, *, external_ref: str, mode: str, quality: str, budget_usd: float,
                  angle: str, hook_variants: int, callback_url: str, logo_asset: str | None, store_url: str | None) -> dict:
    row = None
    for p, r, _ in storefront._candidates(session):
        if p.id == product.id:
            row = r
    title = row.display_title if row and row.display_title else storefront.clean_title(product.title, 90)
    facts = []
    if product.rating:
        facts.append(f"nota {str(round(product.rating, 1)).replace('.', ',')}")
    if product.sold_quantity:
        facts.append(f"{product.sold_quantity} vendidos")
    market = storefront.MARKETPLACE_NAMES.get(product.marketplace.value, product.marketplace.value)
    description = (row.blurb if row and row.blurb else f"{title}, à venda na {market}" + (f" ({', '.join(facts)})" if facts else "") + ".")[:500]
    price = {"amount": round(float(product.price), 2), "currency": "BRL"} if product.price else None
    if price and product.original_price and product.original_price > product.price:
        price["compare_at"] = round(float(product.original_price), 2)
    payload = {
        "external_ref": external_ref, "mode": mode, "quality": quality, "language": "pt-BR", "budget": {"max_usd": budget_usd},
        "approval": {"mode": "none"},
        "product": {"id": str(product.id), "name": title, "category": storefront.guess_category(product.title, product.marketplace.value),
                    "description": description, "images": [{"url": storefront._first_image(product), "role": "main"}],
                    "forbidden_claims": FORBIDDEN_CLAIMS, **({"price": price} if price else {}), **({"url": store_url} if store_url else {})},
        "brand": {"name": storefront.get_meta(session)["name"], "colors": {"primary": "#A71920", "secondary": "#171923", "text": "#FFFFFF"},
                  "font": "Montserrat", "voice_tone": ["direto", "amigável"], "banned_words": BANNED_WORDS,
                  **({"logo": {"asset_id": logo_asset}} if logo_asset else {})},
        "audience": {"locale": "BR", "age_range": [20, 50]},
        "creative": {"objective": "consideration", "angle": angle, "hook_variants": hook_variants, "presenter": {"type": "none"},
                     "voice": {"style": "warm_male"}, "music": {"mood": "upbeat_modern", "enabled": True},
                     "cta": {"text": "Ver na loja", **({"url": store_url} if store_url else {})},
                     "notes": "Mostrar só o produto da foto de referência. Sem pessoas reais identificáveis e sem promessas de resultado."},
        "deliverables": [
            {"kind": "video", "channel": "instagram_reels", "aspect_ratio": "9:16", "duration_s": 15, "variants": hook_variants},
            {"kind": "video", "channel": "feed", "aspect_ratio": "1:1", "duration_s": 15, "derive_from": "instagram_reels"},
            {"kind": "image", "channel": "feed", "aspect_ratio": "4:5"},
            {"kind": "copy", "channel": "instagram", "fields": ["caption", "hashtags", "headline"]},
        ],
        "compliance": {"platforms": ["meta"], "ai_disclosure": True, "sensitive_category": None},
    }
    if callback_url:
        payload["callback"] = {"url": callback_url}
    return payload


# ------------------------------------------------------------------------------ operações --------


def _product_for(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise AIStudioError(f"produto {product_id} não encontrado")
    reason = storefront._eligibility(product, None, None)
    if reason and reason != "oculto na vitrine" or storefront._SENSITIVE.search(product.title or ""):
        raise AIStudioError(f"este produto não pode virar anúncio: {reason or 'conteúdo sensível'}")
    return product


def _store_url(session: Session, product_id: int) -> str | None:
    cfg = storefront.load_config(session)
    return f"{cfg.public_url}/#p{product_id}" if cfg else None


def estimate(session: Session, product_id: int, *, quality: str = "economy", angle: str = "problem_solution", hook_variants: int = 2) -> dict:
    cfg = _require(session)
    product = _product_for(session, product_id)
    payload = build_payload(session, product, external_ref=f"estimate-{product_id}", mode="sandbox", quality=quality, budget_usd=cfg.max_usd,
                            angle=angle, hook_variants=hook_variants, callback_url="", logo_asset=None, store_url=_store_url(session, product_id))
    return _call(cfg, "POST", "/campaigns/estimate", json=payload)


def create(session: Session, product_id: int, *, mode: str = "sandbox", quality: str = "economy", angle: str = "problem_solution",
           hook_variants: int = 2, budget_usd: float | None = None, actor: str = "agent") -> CreativeCampaign:
    cfg = _require(session)
    if mode not in ("sandbox", "live") or quality not in QUALITIES or angle not in ANGLES:
        raise AIStudioError(f"parâmetros inválidos (modo sandbox|live; qualidade {', '.join(QUALITIES)}; ângulo {', '.join(ANGLES)})")
    if mode == "live" and not cfg.allow_live:
        raise AIStudioError("geração ao vivo gasta créditos e está desligada: o operador precisa ligar \"Permitir geração ao vivo\" no cartão do AI Studio. "
                            "Use mode=sandbox para testar sem gastar.")
    budget = float(budget_usd if budget_usd is not None else cfg.max_usd)
    if budget <= 0 or budget > cfg.max_usd:
        raise AIStudioError(f"o orçamento da campanha (US$ {budget:g}) passa do teto do operador (US$ {cfg.max_usd:g})")
    product = _product_for(session, product_id)
    n = session.query(CreativeCampaign).filter(CreativeCampaign.product_id == product_id).count() + 1
    ref = f"mural-p{product_id}-{mode[0]}{n}-{datetime.now(UTC):%y%m%d%H%M}"
    record = CreativeCampaign(product_id=product_id, external_ref=ref, mode=mode, status="requested", quality=quality, angle=angle,
                              budget_usd=budget, created_by=actor[:64])
    session.add(record)
    session.flush()  # o external_ref fica guardado ANTES da chamada: retentar nunca duplica
    payload = build_payload(session, product, external_ref=ref, mode=mode, quality=quality, budget_usd=budget, angle=angle,
                            hook_variants=hook_variants, callback_url=cfg.callback_url, logo_asset=ensure_logo_asset(session, cfg),
                            store_url=_store_url(session, product_id))
    record.request = payload
    try:
        body = _call(cfg, "POST", "/campaigns", idempotency_key=ref[:80], json=payload)
    except AIStudioError as exc:
        record.status, record.error = "failed", str(exc)[:500]
        session.flush()
        raise
    record.campaign_id, record.status = body.get("campaign_id"), body.get("status") or "queued"
    session.flush()
    return record


def _apply(record: CreativeCampaign, data: dict) -> None:
    """Copia o estado de um `GET /campaigns/{id}` ou do `data` de um webhook para o registro."""
    if data.get("status"):
        record.status = data["status"]
    cost = (data.get("cost") or {}).get("spent_usd")
    if cost is not None:
        record.cost_usd = float(cost)
    if data.get("manifest"):
        record.manifest = data["manifest"]
    err = data.get("error")
    if err:
        record.error = (err.get("message") if isinstance(err, dict) else str(err))[:500]
    if record.status in FINAL_STATUSES and record.finished_at is None:
        record.finished_at = datetime.now(UTC)


def refresh(session: Session, record: CreativeCampaign) -> CreativeCampaign:
    """Reconcilia por GET (use quando um webhook pode ter se perdido)."""
    if not record.campaign_id:
        return record
    _apply(record, _call(_require(session), "GET", f"/campaigns/{record.campaign_id}"))
    session.flush()
    return record


def reconcile(session: Session) -> int:
    pending = list(session.scalars(select(CreativeCampaign).where(CreativeCampaign.status.notin_(FINAL_STATUSES + ("requested",)))))
    for record in pending:
        try:
            refresh(session, record)
        except AIStudioError as exc:
            logger.info("reconciliação do AI Studio falhou para %s: %s", record.external_ref, exc)
    return len(pending)


def deliverables(record: CreativeCampaign) -> list[dict]:
    """As peças prontas do manifesto (sem as refeitas), resumidas para o agente e para a tela."""
    out = []
    for d in (record.manifest or {}).get("deliverables", []):
        if d.get("status") == "ready":
            out.append({k: d.get(k) for k in ("id", "kind", "channel", "variant", "aspect_ratio", "duration_s", "content", "expires_at") if d.get(k) is not None}
                       | ({"download": (d.get("url_signed") or {}).get("href") or d.get("url")} if d.get("kind") != "copy" else {}))
    return out


# ------------------------------------------------------------------------------ webhook ----------


def verify_signature(raw: bytes, headers: dict, secret: str, *, tolerance_s: int = 300, now: float | None = None) -> bool:
    """HMAC-SHA256 de `timestamp.corpo` (Anexo B do contrato), com janela anti-replay e comparação em tempo constante."""
    low = {k.lower(): v for k, v in headers.items()}
    try:
        ts = int(low.get("x-aistudio-timestamp", ""))
    except ValueError:
        return False
    if not secret or abs((now if now is not None else time.time()) - ts) > tolerance_s:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    got = str(low.get("x-aistudio-signature", "")).removeprefix("v1=")
    return len(got) == len(expected) and hmac.compare_digest(got, expected)


def handle_webhook(session: Session, raw: bytes, headers: dict, *, now: float | None = None) -> str:
    """Processa um webhook. Devolve "ok", "duplicate" ou "ignored"; levanta `AIStudioError(code="bad_signature")` se a assinatura falhar."""
    cfg = load_config(session)
    if cfg is None or not verify_signature(raw, headers, cfg.webhook_secret, now=now):
        raise AIStudioError("assinatura inválida", code="bad_signature")
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise AIStudioError("corpo inválido", code="bad_body") from exc
    event_id = str(body.get("event_id") or headers.get("X-AIStudio-Event-Id") or "")[:80]
    if not event_id:
        raise AIStudioError("evento sem id", code="bad_body")
    if session.scalar(select(CreativeEvent.id).where(CreativeEvent.event_id == event_id)):
        return "duplicate"
    session.add(CreativeEvent(event_id=event_id, event=str(body.get("event") or "")[:48], campaign_id=str(body.get("campaign_id") or "")[:64] or None))
    record = session.scalar(select(CreativeCampaign).where(CreativeCampaign.campaign_id == body.get("campaign_id")))
    if record is None:
        record = session.scalar(select(CreativeCampaign).where(CreativeCampaign.external_ref == body.get("external_ref")))
    if record is None:
        session.flush()
        return "ignored"
    data = body.get("data") or {}
    event = str(body.get("event") or "")
    if event == "campaign.deliverable_ready" and data.get("deliverable"):
        manifest = dict(record.manifest or {"deliverables": []})
        items = [d for d in manifest.get("deliverables", []) if d.get("id") != data["deliverable"].get("id")]
        manifest["deliverables"] = items + [data["deliverable"]]
        record.manifest = manifest
    elif event.startswith("campaign.") and event not in ("campaign.progress", "campaign.needs_approval", "campaign.deliverable_failed"):
        _apply(record, {**data, "status": data.get("status") or event.removeprefix("campaign.")})
    elif event == "campaign.progress":
        _apply(record, {"cost": data.get("cost")})
    elif event == "budget.warning":
        record.error = f"aviso: gasto de US$ {data.get('spent_usd')} chegou a 80% do teto (US$ {data.get('budget_usd')})"
    session.flush()
    return "ok"
