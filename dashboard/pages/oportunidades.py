"""Oportunidades: cruzamento de tendências, produtos e copy para priorizar ações."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.orchestrator import AgentController

DATA = Path(__file__).resolve().parent.parent.parent / "data"
st.set_page_config(page_title="Oportunidades", layout="wide", page_icon="💡")

st.markdown("# 💡 Oportunidades")
st.caption("Ideias priorizadas a partir de tendências + produtos + copy.")

controller = st.session_state.get("controller")
if controller is None:
    st.info("Abra o Controle da Operação primeiro para inicializar os agentes.")
    st.stop()

controller.load_memory()

try:
    trends = pd.read_csv(DATA / "trend_alerts.csv")
    stale_trends = _stale(trends, "collected_at", hours=24)
except Exception as e:  # noqa: BLE001
    trends = pd.DataFrame()
    stale_trends = []
    st.caption(f"trend_alerts indisponível agora: {e}")

try:
    products = pd.read_csv(DATA / "products" / "product_hunter_latest.csv")
    stale_products = _stale(products, "collected_at", hours=24)
except Exception as e:  # noqa: BLE001
    products = pd.DataFrame()
    stale_products = []
    st.caption(f"product_hunter_latest indisponível agora: {e}")

try:
    copies = pd.read_csv(DATA / "copy_variants.csv")
    stale_copies = _stale(copies, "generated_at", hours=24)
except Exception as e:  # noqa: BLE001
    copies = pd.DataFrame()
    stale_copies = []
    st.caption(f"copy_variants indisponível agora: {e}")

if trends.empty and products.empty:
    st.info("Sem dados suficientes. Inicie o orquestrador na página Controle.")
else:
    st.subheader("Top keywords em alta")
    if not trends.empty:
        show = trends.copy()
        show["alert"] = show["alert"].fillna("STABLE").astype(str)
        st.dataframe(show.head(20), use_container_width=True)
    else:
        st.caption("Sem tendências agora.")

    st.subheader("Produtos priorizados")
    if not products.empty:
        show = products.drop(columns=[c for c in products.columns if c.startswith("Unnamed:")], errors="ignore")
        show = show.head(50)
        st.dataframe(show, use_container_width=True)
    else:
        st.caption("Sem produtos priorizados agora.")

    st.subheader("Copys gerados")
    if not copies.empty:
        st.dataframe(copies.head(50), use_container_width=True)
    else:
        st.caption("Sem copys agora.")

st.markdown("---")

st.subheader("Alertas de idade")
st.caption("Itens com dados mais velhos que 24h merecem atualização.")

st.write(f"Tendências velhas: {len(stale_trends)}/{len(trends)}")
st.write(f"Produtos velhos: {len(stale_products)}/{len(products)}")
st.write(f"Copys velhos: {len(stale_copies)}/{len(copies)}")


def _stale(df: pd.DataFrame, time_col: str, *, hours: int) -> list[int]:
    if df.empty or time_col not in df.columns:
        return []
    try:
        now = datetime.now()
        times = pd.to_datetime(df[time_col], errors="coerce")
        diff = (now - times).dt.total_seconds().div(3600).fillna(0)
        return [int(i) for i in diff[diff > hours].index.tolist()]
    except Exception:  # noqa: BLE001
        return []
