"""Página de controle do orquestrador (start / pause / resume / stop)."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from core.orchestrator import AgentController
from core.tasks import Task
from integrations.marketplaces.registry import list_adapter_names
from agents.trend_hunter.agent import run as trend_hunter_run
from agents.product_hunter.agent import run as product_hunter_run
from agents.copy_chief.agent import run as copy_chief_run
from agents.marketplace_manager.agent import run as marketplace_manager_run
from agents.growth_analyst.agent import run as growth_analyst_run
from agents.master.agent import run as master_run

st.set_page_config(page_title="Controle da Operação", layout="wide", page_icon="🎮")

st.markdown("# 🎮 Controle da Operação")
st.caption("Inicie, pause ou pare a execução dos agentes de marketing digital.")

if "controller" not in st.session_state:
    st.session_state.controller = AgentController()
controller: AgentController = st.session_state.controller
controller.load_memory()

name_to_run = {
    "trend_hunter": trend_hunter_run,
    "product_hunter": product_hunter_run,
    "copy_chief": copy_chief_run,
    "marketplace_manager": marketplace_manager_run,
    "growth_analyst": growth_analyst_run,
    "master": master_run,
}
if not controller.tasks:
    controller.tasks = [
        Task(id=k, name=k.replace("_", " ").title(), run=v) for k, v in name_to_run.items()
    ]

status = controller.status
st.subheader(f"Status: {status.upper()}")

with st.sidebar:
    st.header("Configuração rápida")
    keywords_trend = st.text_area(
        "Palavras-chave (tendências)",
        value=", ".join(controller.memory.get("keywords_trend", ["fone bluetooth", "luminária led"])),
        help="Separe por vírgula.",
    )
    keywords_product = st.text_area(
        "Palavras-chave (produtos)",
        value=", ".join(controller.memory.get("keywords_product", ["tênis running", "calça legging"])),
        help="Separe por vírgula.",
    )
    adapter_names = st.multiselect(
        "Marketplaces ativos",
        options=list_adapter_names(),
        default=controller.memory.get("adapter_names", list_adapter_names()),
    )
    controller.memory["keywords_trend"] = [x.strip() for x in keywords_trend.split(",") if x.strip()]
    controller.memory["keywords_product"] = [x.strip() for x in keywords_product.split(",") if x.strip()]
    controller.memory["adapter_names"] = adapter_names
    controller.save_memory()

    st.markdown("---")
    st.subheader("Ações do agente")

    if status == "stopped":
        if st.button("▶️ Iniciar", key="start"):
            controller.start(controller.tasks)
            st.rerun()
    elif status == "running":
        if st.button("⏸️ Pausar", key="pause"):
            controller.pause()
            st.rerun()
        if st.button("⏹️ Parar", key="stop"):
            controller.stop()
            st.rerun()
    elif status == "paused":
        if st.button("▶️ Continuar", key="resume"):
            controller.resume()
            st.rerun()
        if st.button("⏹️ Parar", key="stop"):
            controller.stop()
            st.rerun()

    st.caption("O pipeline roda trend_hunter → product_hunter → marketplace_manager → growth_analyst → copy_chief → master.")

if status == "stopped":
    for task in controller.tasks:
        with st.expander(f"{task.name}: não executado"):
            st.info("Operação parada. Clique em Iniciar para executar o ciclo.")
else:
    st.subheader("Última execução")
    last = controller.memory.get("last_task") or controller.memory.get("last_error")
    if isinstance(last, dict):
        st.json(last)
    else:
        st.write(last)

    history_path = Path(__file__).resolve().parent.parent / "data" / "reports"
    if history_path.exists():
        csvs = sorted(history_path.glob("growth_report_*.csv"))
        if csvs:
            st.write("Relatórios de growth:")
            for csv in csvs[-5:]:
                try:
                    frame = pd.read_csv(csv)
                    st.write(f"`{csv.name}` — linhas: {len(frame)}")
                except Exception as e:  # noqa: BLE001
                    st.write(f"`{csv.name}` — erro: {e}")
