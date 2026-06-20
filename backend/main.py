"""Backend FastAPI para Marketing Digital — porta 8000."""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, List, Optional
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from agents.core.mcp_state import MCPState
from scanner.scanner import scan_all, load_rules, save_rules, MarketRules
from integrations.marketplaces.mercado_livre import MercadoLivreAdapter, MLConfig
from integrations.marketplaces.config_api import apply_config

app = FastAPI(title="Marketing Digital API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.sqlite3"


class FeedbackIn(BaseModel):
    channel: str
    user_id: int
    username: Optional[str] = None
    text: str
    sentiment: Optional[str] = None
    tags: Optional[str] = None


class PreferenceIn(BaseModel):
    user_id: int
    chat_id: Optional[int] = None
    username: Optional[str] = None
    language: str = "pt-BR"
    notify_alerts: bool = True
    notify_daily_report: bool = True
    notify_opportunities: bool = True
    muted: bool = False
    extra: Optional[dict] = None


class MarketRulesIn(BaseModel):
    min_commission_pct: float = 5.0
    target_ticket_min: float = 97.0
    target_ticket_max: float = 297.0
    min_orders: int = 50
    score_weights: dict[str, float] = {"commission": 0.4, "orders": 0.3, "ticket": 0.2, "competition": 0.1}


class MarketplaceConfigIn(BaseModel):
    marketplace: str
    enabled: bool = True
    mode: str = "affiliate"  # affiliate | dropshipping | both
    scope: str = "national,international"
    api_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    redirect_uri: Optional[str] = None
    country: Optional[str] = "BR"
    currency: Optional[str] = "BRL"
    extra: Optional[dict] = None


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


@app.get("/health")
def health() -> dict[str, Any]:
    ok = DB_PATH.exists()
    return {"status": "ok" if ok else "initializing", "db": str(DB_PATH)}


@app.get("/feedback")
def list_feedback(limit: int = 50) -> List[dict[str, Any]]:
    c = conn()
    rows = c.execute("SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.post("/feedback")
def add_feedback(item: FeedbackIn) -> dict[str, int | None]:
    c = conn()
    cur = c.execute(
        "INSERT INTO feedback (channel, user_id, username, text, sentiment, tags) VALUES (?, ?, ?, ?, ?, ?)",
        (item.channel, item.user_id, item.username, item.text, item.sentiment, item.tags),
    )
    c.commit()
    c.close()
    return {"id": cur.lastrowid}


@app.get("/preferences")
def get_preferences() -> List[dict[str, Any]]:
    c = conn()
    rows = c.execute("SELECT * FROM user_preferences ORDER BY updated_at DESC").fetchall()
    c.close()
    out = []
    for r in rows:
        row = dict(r)
        row["extra"] = json.loads(row["extra"]) if row.get("extra") else None
        out.append(row)
    return out


@app.put("/preferences/{user_id}")
def upsert_preference(user_id: int, item: PreferenceIn) -> dict[str, bool]:
    c = conn()
    c.execute(
        "INSERT INTO user_preferences (user_id, chat_id, username, language, notify_alerts, notify_daily_report, notify_opportunities, muted, extra, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) ON CONFLICT(user_id) DO UPDATE SET"
        " chat_id=excluded.chat_id, username=excluded.username, language=excluded.language, notify_alerts=excluded.notify_alerts,"
        " notify_daily_report=excluded.notify_daily_report, notify_opportunities=excluded.notify_opportunities, muted=excluded.muted, extra=excluded.extra, updated_at=datetime('now')",
        (
            user_id,
            item.chat_id,
            item.username,
            item.language,
            1 if item.notify_alerts else 0,
            1 if item.notify_daily_report else 0,
            1 if item.notify_opportunities else 0,
            1 if item.muted else 0,
            json.dumps(item.extra, ensure_ascii=False) if item.extra else None,
        ),
    )
    c.commit()
    c.close()
    return {"ok": True}


@app.get("/alerts/trends")
def trend_alerts(limit: int = 20) -> List[dict[str, Any]]:
    c = conn()
    rows = c.execute("SELECT * FROM trend_alerts ORDER BY collected_at DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/payments")
def payments(limit: int = 50) -> List[dict[str, Any]]:
    c = conn()
    rows = c.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/agenda")
def agenda(limit: int = 50) -> List[dict[str, Any]]:
    c = conn()
    rows = c.execute("SELECT * FROM agenda ORDER BY when_date DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/groups")
def groups() -> List[dict[str, Any]]:
    c = conn()
    rows = c.execute("SELECT * FROM groups ORDER BY updated_at DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.post("/groups/{group_id}/status")
def set_group_status(group_id: int, payload: dict) -> dict[str, bool]:
    c = conn()
    c.execute(
        "INSERT INTO groups (group_id, status, reason, updated_by, updated_at) VALUES (?, ?, ?, ?, datetime('now')) ON CONFLICT(group_id) DO UPDATE SET status=excluded.status, reason=excluded.reason, updated_at=excluded.updated_at",
        (group_id, payload.get("status"), payload.get("reason"), payload.get("updated_by")),
    )
    c.commit()
    c.close()
    return {"ok": True}


@app.get("/reports/kpis")
def kpis(days: int = 30) -> dict[str, Any]:
    c = conn()
    start = (datetime.now() - timedelta(days=days)).isoformat()
    payments_rows = c.execute("SELECT * FROM payments WHERE created_at >= ?", (start,)).fetchall()
    orders = len(payments_rows)
    revenue = sum(float(r["amount"] or 0) for r in payments_rows)
    c.close()
    return {
        "period_days": days,
        "orders": orders,
        "revenue": round(revenue, 2),
        "ticket_average": round(revenue / orders, 2) if orders else 0,
    }


@app.get("/methodology/badge")
def methodology_badge() -> dict[str, Any]:
    state = MCPState()
    return {
        "badge": state.methodology.get("badge"),
        "active_influencer": state.methodology.get("active_influencer"),
        "daily_sales_target": state.methodology.get("daily_sales_target"),
    }


@app.get("/market/products")
def market_products(limit: int = 50, marketplace: Optional[str] = None) -> List[dict[str, Any]]:
    df = scan_all()
    if df is None or df.empty:
        return []
    if marketplace:
        df = df[df["marketplace"] == marketplace]
    out: List[dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        out.append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "price": row.get("price"),
                "stock": row.get("stock"),
                "orders": row.get("orders"),
                "commission_pct": row.get("commission_pct"),
                "score": row.get("score"),
                "marketplace": row.get("marketplace"),
                "url": row.get("url"),
                "category": row.get("category"),
                "collected_at": row.get("collected_at"),
            }
        )
    return out


@app.get("/market/rules")
def market_rules() -> dict[str, Any]:
    rules = load_rules()
    return rules.__dict__


@app.put("/market/rules")
def put_market_rules(payload: MarketRulesIn) -> dict[str, Any]:
    save_rules(MarketRules(**payload.dict()))
    return {"ok": True, "rules": payload.dict()}


@app.get("/market/config")
def get_market_config() -> dict[str, Any]:
    data: dict[str, dict[str, Any]] = {}
    mapping = {
        "mercado_livre": [
            "MARKETPLACE_MERCADOLIVRE_CLIENT_ID",
            "MARKETPLACE_MERCADOLIVRE_CLIENT_SECRET",
            "MARKETPLACE_MERCADOLIVRE_REDIRECT_URI",
            "MARKETPLACE_MERCADOLIVRE_ACCESS_TOKEN",
            "MARKETPLACE_MERCADOLIVRE_REFRESH_TOKEN",
            "MARKETPLACE_MERCADOLIVRE_COUNTRY",
            "MARKETPLACE_MERCADOLIVRE_MODE",
            "MARKETPLACE_MERCADOLIVRE_SCOPE",
            "MARKETPLACE_MERCADOLIVRE_API_URL",
        ],
        "shopee": [
            "MARKETPLACE_SHOPEE_PARTNER_ID",
            "MARKETPLACE_SHOPEE_PARTNER_KEY",
            "MARKETPLACE_SHOPEE_ACCESS_TOKEN",
            "MARKETPLACE_SHOPEE_COUNTRY",
            "MARKETPLACE_SHOPEE_MODE",
            "MARKETPLACE_SHOPEE_SCOPE",
            "MARKETPLACE_SHOPEE_API_URL",
        ],
        "amazon": [
            "MARKETPLACE_AMAZON_ACCESS_KEY",
            "MARKETPLACE_AMAZON_SECRET_KEY",
            "MARKETPLACE_AMAZON_ASSOCIATE_TAG",
            "MARKETPLACE_AMAZON_REGION",
            "MARKETPLACE_AMAZON_COUNTRY",
            "MARKETPLACE_AMAZON_MODE",
            "MARKETPLACE_AMAZON_SCOPE",
            "MARKETPLACE_AMAZON_API_URL",
        ],
    }

    def env(name: str) -> str:
        return os.getenv(name, "")

    def mode_for_prefix(prefix: str) -> str:
        mode_env = os.getenv(f"{prefix.upper()}_MODE", "affiliate")
        return mode_env if mode_env in {"affiliate", "dropshipping", "both"} else "affiliate"

    for mp, keys in mapping.items():
        enabled_env = os.getenv(f"{mp.upper()}_ENABLED", "true")
        data[mp] = {
            "enabled": str(enabled_env).lower() != "false",
            "mode": mode_for_prefix(mp),
            "scope": os.getenv(f"{mp.upper()}_SCOPE", "national,international"),
            "values": {k.split("_", 1)[1].lower(): env(k) for k in keys},
        }
    return data


@app.put("/market/config")
def put_market_config(payload: MarketplaceConfigIn) -> dict[str, Any]:
    if payload.marketplace not in {"mercado_livre", "shopee", "amazon"}:
        return {"ok": False, "error": "marketplace_invalid"}
    try:
        result = apply_config({
            payload.marketplace: {
                "enabled": payload.enabled,
                "mode": payload.mode,
                "scope": payload.scope,
                "values": payload.values or {},
            }
        })
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "saved": result}


@app.post("/market/ml/auth-url")
def ml_auth_url(payload: dict) -> dict[str, Any]:
    cid = os.getenv("MARKETPLACE_MERCADOLIVRE_CLIENT_ID", "")
    redirect = os.getenv("MARKETPLACE_MERCADOLIVRE_REDIRECT_URI", "")
    if not cid or not redirect:
        return {"ok": False, "error": "client_id_or_redirect_uri_missing"}
    state = payload.get("state") or "state"
    url = (
        f"https://auth.mercadolivre.com.br/authorization?response_type=code&client_id={cid}"
        f"&redirect_uri={redirect}&state={state}"
    )
    return {"ok": True, "url": url}


@app.post("/market/ml/token")
def ml_exchange_token(payload: dict) -> dict[str, Any]:
    client_id = os.getenv("MARKETPLACE_MERCADOLIVRE_CLIENT_ID", "")
    client_secret = os.getenv("MARKETPLACE_MERCADOLIVRE_CLIENT_SECRET", "")
    redirect_uri = os.getenv("MARKETPLACE_MERCADOLIVRE_REDIRECT_URI", "")
    code = payload.get("code", "")
    if not client_id or not client_secret or not redirect_uri or not code:
        return {"ok": False, "error": "missing_required_fields"}
    adapter = MercadoLivreAdapter(
        MLConfig(
            client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri,
        )
    )
    data = adapter.exchange_code_for_token(code)
    if not data:
        return {"ok": False, "error": "exchange_failed"}
    return {"ok": True, "token": data}
