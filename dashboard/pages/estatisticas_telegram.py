"""Página de estatísticas do Telegram, sem conteúdo textual sensível."""
from __future__ import annotations

from collections import Counter
from datetime import datetime

import pandas as pd
import streamlit as st

from integrations.telegram_stats import active_users, event_counts, load_events, user_events_summary

st.set_page_config(page_title="Estatísticas Telegram", layout="wide", page_icon="📡")

st.markdown("# 📡 Estatísticas Telegram")
st.caption("Métricas operacionais sem exposicão de conteúdo textual.")

col1, col2, col3 = st.columns(3)
col1.metric("Eventos totais", sum(event_counts().values()))
col2.metric("Usuários ativos (24h)", active_users(minutes=1440))
col3.metric("Eventos únicos", len(event_counts()))

st.subheader("Distribuição de eventos")
counts = event_counts()
if counts:
    st.bar_chart(pd.Series(counts))
else:
    st.info("Sem eventos registrados.")

st.subheader("Eventos recentes")
recent = load_events(limit=50)
if recent:
    frame = pd.DataFrame(recent)
    drop = [c for c in frame.columns if c in {"text", "payload_text", "body"}]
    frame = frame.drop(columns=drop, errors="ignore")
    st.dataframe(frame.head(100), use_container_width=True)
else:
    st.caption("Sem eventos recentes.")

with st.expander("Detalhe por usuário"):
    user_id = st.text_input("User ID", value="")
    if user_id.strip().isdigit():
        user_events, user_counts = user_events_summary(int(user_id.strip()))
        st.write("Contagem de eventos:")
        st.json(user_counts)
        st.write("Eventos recentes:")
        frame = pd.DataFrame(user_events)
        drop = [c for c in frame.columns if c in {"text", "payload_text", "body"}]
        frame = frame.drop(columns=drop, errors="ignore")
        st.dataframe(frame.head(100), use_container_width=True)
