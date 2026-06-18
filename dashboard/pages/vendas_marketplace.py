"""Vendas e Marketplace: visão consolidada de pedidos, marketplace e desempenho."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from integrations.marketplaces.registry import list_adapter_names, resolve
from core.roles import RoleManager

DATA = Path(__file__).resolve().parent.parent.parent / "data"
REPORTS = DATA / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Vendas e Marketplace", layout="wide", page_icon="🛒")

st.markdown("# 🛒 Vendas e Marketplace")
st.caption("Pedidos, marketplaces e desempenho por canal.")

if "role_manager" not in st.session_state:
    rm_path = DATA / "user_roles.jsonl"
    st.session_state.role_manager = RoleManager(path=str(rm_path))

rm = st.session_state.role_manager

adapter_names = list_adapter_names()
summary = []
for name in adapter_names:
    adapter = resolve(name)
    if adapter is None:
        continue
    try:
        products = adapter.fetch_products()
        sales = adapter.fetch_sales()
        product_count = int(len(products)) if products is not None else 0
        sales_count = int(len(sales)) if sales is not None else 0
    except Exception:  # noqa: BLE001
        product_count = -1
        sales_count = -1
    summary.append({
        "marketplace": name,
        "produtos_cadastrados": product_count,
        "vendas_30d": sales_count,
        "saude": "ok" if product_count >= 0 else "erro",
    })

st.subheader("Resumo por marketplace")
st.table(pd.DataFrame(summary))

st.subheader("Alertas de catálogo")
health_files = sorted(REPORTS.glob("marketplace_health_*.csv"))
if health_files:
    latest = health_files[-1]
    try:
        health = pd.read_csv(latest)
        watch = health[health["role"] == "watch"] if "role" in health.columns else pd.DataFrame()
        if not watch.empty:
            st.dataframe(watch.head(20), use_container_width=True)
        else:
            st.info("Sem alertas de saúde agora.")
    except Exception as e:
        st.warning(f"Não foi possível ler {latest.name}: {e}")
else:
    st.info("Sem relatórios de saúde gerados ainda.")
