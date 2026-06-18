"""Feedback channels: opiniões, sugestões, reclamações, elogios."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

DATA = Path(__file__).resolve().parent.parent.parent / "data"
FEEDBACK_PATH = DATA / "feedback.jsonl"
FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)

Channel = Literal["opiniao", "sugestao", "reclamacao", "elogio"]


@dataclass
class FeedbackRecord:
    channel: Channel
    user_id: int
    username: str | None
    text: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    sentiment: str | None = None
    tags: list[str] = field(default_factory=list)


def save_feedback(record: FeedbackRecord) -> str:
    with FEEDBACK_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.__dict__, ensure_ascii=False) + "\n")
    return str(FEEDBACK_PATH)


def load_feedback(limit: int = 100) -> list[dict]:
    if not FEEDBACK_PATH.exists():
        return []
    lines = FEEDBACK_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines[-limit:]]


def stats_by_channel() -> dict[str, int]:
    items = load_feedback(limit=1000)
    counts: dict[str, int] = {"opiniao": 0, "sugestao": 0, "reclamacao": 0, "elogio": 0}
    for item in items:
        ch = item.get("channel")
        if ch in counts:
            counts[ch] += 1
    return counts


def stats_by_user(limit: int = 50) -> list[dict]:
    items = load_feedback(limit=1000)
    by_user: dict[str, dict] = {}
    for item in items:
        key = str(item.get("user_id"))
        if key not in by_user:
            by_user[key] = {"user_id": key, "username": item.get("username"), "count": 0, "channels": {}}
        by_user[key]["count"] += 1
        ch = item.get("channel")
        by_user[key]["channels"][ch] = by_user[key]["channels"].get(ch, 0) + 1
    return sorted(by_user.values(), key=lambda x: x["count"], reverse=True)[:limit]
