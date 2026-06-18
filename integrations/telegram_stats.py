"""Telegram integration utilities for stats without text content."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from integrations.feedback_channels import save_feedback

DATA = Path(__file__).resolve().parent.parent.parent / "data"
STATS_PATH = DATA / "telegram_stats.jsonl"
STATS_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class TelemetryEvent:
    user_id: int
    chat_id: int
    event_type: str
    payload: dict | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


def persist_event(event: TelemetryEvent) -> str:
    with STATS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event.__dict__, ensure_ascii=False) + "\n")
    return str(STATS_PATH)


def load_events(limit: int = 1000) -> list[dict]:
    if not STATS_PATH.exists():
        return []
    lines = STATS_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines[-limit:]]


def event_counts() -> dict[str, int]:
    items = load_events(limit=5000)
    counts: dict[str, int] = {}
    for item in items:
        key = item.get("event_type", "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def active_users(minutes: int = 1440) -> int:
    items = load_events(limit=5000)
    if not items:
        return 0
    cutoff = datetime.now() - timedelta(minutes=minutes)
    seen: set[int] = set()
    for item in items:
        try:
            ts = datetime.fromisoformat(item.get("created_at", ""))
            if ts >= cutoff:
                seen.add(item.get("user_id"))
        except Exception:  # noqa: BLE001
            continue
    return len(seen)


def user_events_summary(user_id: int, limit: int = 100) -> tuple[list[dict], dict[str, int]]:
    items = load_events(limit=5000)
    user_events = [x for x in items if x.get("user_id") == user_id][-limit:]
    counts: dict[str, int] = {}
    for item in user_events:
        key = item.get("event_type", "unknown")
        counts[key] = counts.get(key, 0) + 1
    return user_events, counts


def to_feedback(user_id: int, chat_id: int, text: str, channel: str = "opiniao", username: str | None = None) -> str:
    from integrations.feedback_channels import FeedbackRecord
    record = FeedbackRecord(channel=channel, user_id=user_id, username=username, text=text)
    save_feedback(record)
    return persist_event(
        TelemetryEvent(user_id=user_id, chat_id=chat_id, event_type="feedback.created", payload={"channel": channel})
    )
