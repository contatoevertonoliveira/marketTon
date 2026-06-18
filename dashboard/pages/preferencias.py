"""Preferências por usuário/grupo no Telegram."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from integrations.user_preferences import list_preferences, find_by_user

DATA = Path(__file__).resolve().parent.parent.parent / "data"
PREFERENCES_PATH = DATA / "user_preferences.jsonl"
PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Preferências", layout="wide", page_icon="⚙️")

st.markdown("# ⚙️ Preferências por usuário/grupo")

user_id_input = st.text_input("User ID do Telegram", placeholder="Ex: 1234567")
if not user_id_input.strip():
    st.info("Sem User ID informado.")
    st.stop()

user_id = int(user_id_input.strip())
current = find_by_user(user_id)

with st.form("preferences_form"):
    col1, col2 = st.columns(2)
    with col1:
        language = st.text_input("Idioma", value=(current.get("language") if current else "pt-BR"))
        notify_alerts = st.checkbox("Alertas de tendências", value=bool(current.get("notify_alerts", True)))
        notify_daily_report = st.checkbox("Relatório diário", value=bool(current.get("notify_daily_report", True)))
    with col2:
        notify_opportunities = st.checkbox("Oportunidades", value=bool(current.get("notify_opportunities", True)))
        muted = st.checkbox("Silenciado", value=bool(current.get("muted", False)))

    chat_id = st.text_input("Chat ID", value=str(current.get("chat_id", "")) if current else "")
    username = st.text_input("Username (opcional)", value=(current.get("username") or "") if current else "")
    extra_raw = st.text_area("Extra (JSON)", value=json.dumps((current.get("extra") or {}) if current else {}, ensure_ascii=False, indent=2))

    submitted = st.form_submit_button("Salvar preferências")

if not submitted:
    st.caption("Ainda não salvo.")
    st.stop()

extra = {}
try:
    extra = json.loads(extra_raw or "{}")
except Exception as e:  # noqa: BLE001
    st.error(f"Extra inválido: {e}")

from integrations.user_preferences import upsert_pref

upsert_pref(
    user_id=user_id,
    chat_id=int(chat_id.strip()) if str(chat_id).strip().isdigit() else None,
    username=username.strip() or None,
    language=language.strip() or "pt-BR",
    notify_alerts=notify_alerts,
    notify_daily_report=notify_daily_report,
    notify_opportunities=notify_opportunities,
    muted=muted,
    extra=extra,
)
st.success("Preferências salvas.")
st.rerun()
