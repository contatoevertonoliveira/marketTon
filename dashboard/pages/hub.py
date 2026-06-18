"""Hub do dashboard com visão geral, execução em tempo real e operação."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core.orchestrator import AgentController
from integrations.marketplaces.registry import list_adapter_names
from integrations.ads_meta.client import get_status as meta_get_status
from collectors.google_trends.client import fetch_compare_interest
from integrations.marketplaces.base import MarketplaceAdapter

st.set_page_config(page_title="Marketing Digital — Hub", layout="wide", page_icon="📈")

st.markdown("# 📈 Marketing Digital — Hub")
st.markdown("### Operação unificada: marketplaces, ads, tendências, agentes e lucro planejado.")
st.markdown("---")

if "controller" not in st.session_state:
    st.session_state.controller = AgentController()

controller: AgentController = st.session_state.controller
controller.load_memory()

status = controller.status
c1, c2, c3 = st.columns(3)
c1.metric("Status", status.upper())
c2.metric("Agentes", "6")
c3.metric("Marketplaces", ", ".join(controller.memory.get("adapter_names", list_adapter_names()) or ["auto"]))

st.subheader("Execução e controle")
start, pause, resume, stop = st.columns(4)
with start:
    if status == "stopped" and st.button("Iniciar"):
        controller.start(controller.tasks)
        st.rerun()
with pause:
    if status == "running" and st.button("Pausar"):
        controller.pause()
        st.rerun()
with resume:
    if status == "paused" and st.button("Continuar"):
        controller.resume()
        st.rerun()
with stop:
    if status != "stopped" and st.button("Parar"):
        controller.stop()
        st.rerun()

st.markdown("---")

st.subheader("Métricas rápidas")
history_path = controller.memory.get("reports_dir", "data/reports")
try:
    meta_status = meta_get_status()
except Exception as e:  # noqa: BLE001
    meta_status = {"status": "error", "error": str(e)}

if meta_status.get("status") == "ready":
    st.success("Meta Ads API conectada.")
else:
    st.warning(f"Meta Ads API: {meta_status.get('status', 'error')} - {meta_status.get('error')}")

try:
    compare = fetch_compare_interest(["garrafa térmica", "luminária led", "calça legging"], geo="BR", window_days=15)
    if not compare.empty:
        st.line_chart(compare.set_index("date")[[c for c in compare.columns if c not in {"date", "geo", "window_days"}]])
except Exception as e:  # noqa: BLE001
    st.info(f"Google Trends indisponível no momento: {e}")

adapter_names = controller.memory.get("adapter_names") or list_adapter_names()
summary_rows = []
for name in adapter_names:
    adapter = _resolve(name)
    if adapter is None:
        continue
    try:
        products = adapter.fetch_products()
        count = int(len(products)) if products is not None else 0
    except Exception as e:  # noqa: BLE001
        count = -1
    summary_rows.append({"marketplace": name, "products": count})
summary_df = pd.DataFrame(summary_rows)
st.subheader("Marketplaces")
if not summary_df.empty:
    st.table(summary_df)

st.subheader("Lucro planejado")
base_price = st.number_input("Preço de venda", min_value=0.0, value=79.9)
cogs = st.number_input("Custo produto + frete", min_value=0.0, value=39.0)
margin = base_price - cogs
st.metric("Margem por unidade", f"R$ {margin:.2f}")
st.caption("Use para validar se vale a pena rodar tráfego pago em um produto antes de lançar.")

st.session_state.hub_last_refresh = datetime.now().isoformat()


def _resolve(name: str):
    from integrations.marketplaces.registry import resolve
    return resolve(name)
