"""User and group preferences, persisted on filesystem."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent.parent / "data"
PREF_PATH = DATA / "user_preferences.jsonl"
PREF_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class UserPref:
    user_id: int
    chat_id: int | None
    username: str | None
    language: str = "pt-BR"
    notify_alerts: bool = True
    notify_daily_report: bool = True
    notify_opportunities: bool = True
    muted: bool = False
    created_at: str = field(default_factory=datetime.now().isoformat)
    updated_at: str = field(default_factory=datetime.now().isoformat)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "username": self.username,
            "language": self.language,
            "notify_alerts": self.notify_alerts,
            "notify_daily_report": self.notify_daily_report,
            "notify_opportunities": self.notify_opportunities,
            "muted": self.muted,
            "created_at": self.created_at,
            "updated_at": datetime.now().isoformat(),
            "extra": self.extra,
        }


def save_preference(pref: UserPref) -> str:
    with PREF_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(pref.to_dict(), ensure_ascii=False) + "\n")
    return str(PREF_PATH)


def list_preferences(limit: int = 500) -> list[dict]:
    if not PREF_PATH.exists():
        return []
    lines = PREF_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines[-limit:]]


def find_by_user(user_id: int) -> dict | None:
    items = list_preferences(limit=2000)
    for item in reversed(items):
        if item.get("user_id") == user_id:
            return item
    return None
