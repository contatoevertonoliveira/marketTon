"""Backend FastAPI para Marketing Digital — porta 8000."""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.sqlite3"

app = FastAPI(title="Marketing Digital API", version="0.1.0")


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


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


@app.get("/health")
def health():
    ok = DB_PATH.exists()
    return {"status": "ok" if ok else "initializing", "db": str(DB_PATH)}


@app.get("/feedback")
def list_feedback(limit: int = 50):
    c = conn()
    rows = c.execute("SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.post("/feedback")
def add_feedback(item: FeedbackIn):
    c = conn()
    cur = c.execute(
        "INSERT INTO feedback (channel, user_id, username, text, sentiment, tags) VALUES (?, ?, ?, ?, ?, ?)",
        (item.channel, item.user_id, item.username, item.text, item.sentiment, item.tags),
    )
    c.commit()
    c.close()
    return {"id": cur.lastrowid}


@app.get("/preferences")
def get_preferences():
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
def upsert_preference(user_id: int, item: PreferenceIn):
    c = conn()
    c.execute(
        """INSERT INTO user_preferences (user_id, chat_id, username, language, notify_alerts, notify_daily_report, notify_opportunities, muted, extra, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(user_id) DO UPDATE SET
             chat_id=excluded.chat_id,
             username=excluded.username,
             language=excluded.language,
             notify_alerts=excluded.notify_alerts,
             notify_daily_report=excluded.notify_daily_report,
             notify_opportunities=excluded.notify_opportunities,
             muted=excluded.muted,
             extra=excluded.extra,
             updated_at=datetime('now')""",
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
def trend_alerts(limit: int = 20):
    c = conn()
    rows = c.execute("SELECT * FROM trend_alerts ORDER BY collected_at DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/payments")
def payments(limit: int = 50):
    c = conn()
    rows = c.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/agenda")
def agenda(limit: int = 50):
    c = conn()
    rows = c.execute("SELECT * FROM agenda ORDER BY when_date DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/groups")
def groups():
    c = conn()
    rows = c.execute("SELECT * FROM groups ORDER BY updated_at DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.post("/groups/{group_id}/status")
def set_group_status(group_id: int, payload: dict):
    c = conn()
    c.execute(
        "INSERT INTO groups (group_id, status, reason, updated_by, updated_at) VALUES (?, ?, ?, ?, datetime('now')) ON CONFLICT(group_id) DO UPDATE SET status=excluded.status, reason=excluded.reason, updated_at=datetime('now')",
        (group_id, payload.get("status"), payload.get("reason"), payload.get("updated_by")),
    )
    c.commit()
    c.close()
    return {"ok": True}
