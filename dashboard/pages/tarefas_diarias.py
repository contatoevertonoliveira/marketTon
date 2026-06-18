"""Tarefas Diárias: checklist operacional com aprovação de agentes."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.orchestrator import AgentController

DATA = Path(__file__).resolve().parent.parent.parent / "data"
TODO_PATH = DATA / "daily_tasks.csv"
TODO_PATH.parent.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Tarefas Diárias", layout="wide", page_icon="✅")

st.markdown("# ✅ Tarefas Diárias")
st.caption("Checklist operacional, aprovação de agentes e follow-up.")

if "controller" not in st.session_state:
    st.session_state.controller = AgentController()
controller: AgentController = st.session_state.controller
controller.load_memory()

status = controller.status
st.metric("Status do operação", status.upper())

with st.form("add_task"):
    col1, col2, col3 = st.columns(3)
    with col1:
        owner = st.text_input("Responsável (agente)", value="growth_analyst")
    with col2:
        title = st.text_input("Tarefa")
    with col3:
        priority = st.selectbox("Prioridade", ["alta", "média", "baixa"], index=1)
    due = st.date_input("Vencimento", value=datetime.now().date())
    submitted = st.form_submit_button("Adicionar")
    if submitted and title.strip() and owner.strip():
        row = {
            "title": title.strip(),
            "owner": owner.strip(),
            "priority": priority,
            "due": str(due),
            "created_at": datetime.now().isoformat(),
            "status": "aberta",
            "approved_by_agent": False,
        }
        _save_row(row)
        st.success("Tarefa adicionada.")
        st.rerun()

st.subheader("Aprovação de agentes")
st.caption("Antes de rodar uma ação real, aprove aqui o plano gerado pelos agentes.")

with st.expander("Aprovar produto/copy"):
    plan_name = st.text_input("Nome do plano / campanha", value="campanha_mala_direta")
    plan_type = st.selectbox("Tipo", ["copy", "produto", "ads", "promocao"])
    approve = st.button("Aprovar execução")
    if approve:
        _approve_plan(plan_name, plan_type)
        st.success("Aprovado e registrado.")

st.markdown("---")

st.subheader("Fila de tarefas")
tasks = _load_tasks()
if tasks:
    st.dataframe(pd.DataFrame(tasks), use_container_width=True)
else:
    st.info("Sem tarefas ainda.")


def _load_tasks() -> list[dict]:
    if not TODO_PATH.exists():
        return []
    try:
        return json.loads(TODO_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _save_row(row: dict) -> None:
    tasks = _load_tasks()
    tasks.append(row)
    TODO_PATH.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def _approve_plan(plan_name: str, plan_type: str) -> None:
    approved_path = DATA / "approved_plans.jsonl"
    record = {
        "plan_name": plan_name,
        "type": plan_type,
        "approved_at": datetime.now().isoformat(),
        "status": "approved",
    }
    with approved_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
