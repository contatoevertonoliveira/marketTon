"""Feedback: visualização dos canais."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from integrations.feedback_channels import stats_by_channel, load_feedback, stats_by_user

st.set_page_config(page_title="Canais de Feedback", layout="wide", page_icon="📬")
st.markdown("# 📬 Canais de Feedback")

left, right = st.columns(2)
with left:
    st.subheader("Por canal")
    st.bar_chart(pd.Series(stats_by_channel()))
with right:
    st.subheader("Por usuário")
    by_user = pd.DataFrame(stats_by_user(limit=50))
    if not by_user.empty:
        st.table(by_user)

st.subheader("Registros recentes")
try:
    rows = load_feedback(limit=200)
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
except Exception as e:  # noqa: BLE001
    st.info(f"Feedback indisponível agora: {e}")
