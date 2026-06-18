"""Gerencia preferências por usuário/grupo no Telegram (sem texto sensível)."""
from __future__ import annotations

import datetime
from typing import Any

from integrations.user_preferences import find_by_user, list_preferences, save_preference, UserPref

try:
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:  # pragma: no cover - telethon optional import may not import on this env
    InlineKeyboardMarkup = InlineKeyboardButton = None


def upsert_pref(
    user_id: int,
    chat_id: int | None,
    username: str | None,
    language: str = "pt-BR",
    notify_alerts: bool = True,
    notify_daily_report: bool = True,
    notify_opportunities: bool = True,
    muted: bool = False,
    extra: dict[str, Any] | None = None,
) -> str:
    pref = UserPref(
        user_id=user_id,
        chat_id=chat_id,
        username=username,
        language=language,
        notify_alerts=notify_alerts,
        notify_daily_report=notify_daily_report,
        notify_opportunities=notify_opportunities,
        muted=muted,
        extra=extra or {},
    )
    return save_preference(pref)


def toggle_mute(user_id: int) -> dict | None:
    current = find_by_user(user_id)
    if not current:
        return None
    muted = not bool(current.get("muted"))
    user_id_int = int(user_id) if not isinstance(user_id, int) else user_id
    save_preference(
        UserPref(
            user_id=user_id_int,
            chat_id=current.get("chat_id"),
            username=current.get("username"),
            language=current.get("language", "pt-BR"),
            notify_alerts=current.get("notify_alerts", True),
            notify_daily_report=current.get("notify_daily_report", True),
            notify_opportunities=current.get("notify_opportunities", True),
            muted=muted,
            extra=current.get("extra") or {},
        )
    )
    return find_by_user(user_id)


def preferences_markup(user_id: int) -> Any:
    current = find_by_user(user_id) or {}
    if InlineKeyboardMarkup is None or InlineKeyboardButton is None:
        return None
    toggle_label = "Unmute" if current.get("muted") else "Mute"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(toggle_label, callback_data=f"toggle_mute:{user_id}")],
            [InlineKeyboardButton("Toggle alerts", callback_data=f"toggle_alerts:{user_id}")],
        ]
    )
