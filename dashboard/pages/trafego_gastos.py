"""Trafego e gastos: ingestão e visualização de desempenho de ads e custos."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from integrations.ads_meta.client import ad_account_insights
from integrations.marketplaces.registry import list_adapter_names, resolve
from core.orchestrator import AgentController

st.set_page_config(page_title="Traéfego e Gastos", layout="wide", page_icon="📣")

st.markdown("# 📣 Trafego e Gastos")
st.markdown("Monitoramento de investimentos e desempenho.")

with st.sidebar:
    st.subheader("Período")
    days = st.slider("Dias", 1, 90, 30)
    account = st.text_input("Conta Meta (opcional)", help="Ex.: act_12345")
    refresh = st.button("Atualizar agora")
    st.caption("Dados caem em data/meta_ads_insights.csv")

status = st.empty()
try:
    insights = ad_account_insights(account or "", date_preset=f"last_{days}d") if account or refresh else []
    st.session_state["last_meta_insights"] = datetime.now().isoformat()
except Exception as e:  # noqa: BLE001
    insights = []
    status.warning(f"Meta indisponível: {e}")
    st.session_state["last_meta_insights"] = None

df = pd.DataFrame(insights)
metricas = []
if df.empty:
    st.info("Sem dados de Meta Ads para o período. Configure a conta.")
else:
    metricas = [
        st.metric("Impressões", f"{int(df['impressions'].sum()):,}"),
        st.metric("Cliques", f"{int(df['clicks'].sum()):,}"),
        st.metric("Gasto", f"R$ {float(df['spend'].sum()):.2f}"),
        st.metric("CPC médio", f"R$ {float(df['cpc'].mean()):.2f}"),
        st.metric("CTR médio", f"{float(df['ctr'].mean())*100:.2f}%"),
    ]

st.markdown("---")

st.subheader("Adapters e marketplaces")
rows = []
for name in list_adapter_names():
    adapter = resolve(name)
    if adapter is None:
        continue
    try:
        prods = adapter.fetch_products()
        count = int(len(prods)) if prods is not None else 0
    except Exception as e:  # noqa: BLE001
        count = -1
    rows.append({"marketplace": name, "produtos": count})
st.table(pd.DataFrame(rows))
