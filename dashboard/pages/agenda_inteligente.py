"""Agenda Inteligente: agendamentos de ações operacionais."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from integrations.marketplaces.registry import list_adapter_names

DATA = Path(__file__).resolve().parent.parent.parent / "data"
AGENDA_PATH = DATA / "agenda.jsonl"
AGENDA_PATH.parent.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Agenda Inteligente", layout="wide", page_icon="📅")

st.markdown("# 📅 Agenda Inteligente")
st.caption("Agende ações de marketing, monitoramento de anúncios e revisões de catálogo.")

col1, col2 = st.sidebar.columns(2)

with col1.form("add_task"):
    title = st.text_input("Tarefa")
    category = st.selectbox("Categoria", ["Meta Ads", "Comparação de preços", "Catálogo", "Oportunidade/Desafio", "Outros"], index=4)
    marketplace = st.selectbox("Marketplace", options=["Todos", *list_adapter_names()])
    when = st.date_input("Data", value=datetime.now().date())
    submitted = st.form_submit_button("Adicionar")
    if submitted and title.strip():
        _append({
            "id": str(uuid.uuid4()),
            "title": title.strip(),
            "category": category,
            "marketplace": marketplace,
            "when": str(when),
            "status": "pendente",
            "created_at": datetime.now().isoformat(),
        })
        st.success("Tarefa adicionada.")
        st.rerun()

with st.expander("Ações rápidas"):
    col_a, col_b, col_c = st.columns(3)
    if col_a.button("Agendar hoje"):
        _append({
            "id": str(uuid.uuid4()),
            "title": "Revisão de anúncios Meta Ads",
            "category": "Meta Ads",
            "marketplace": "Todos",
            "when": str(datetime.now().date()),
            "status": "pendente",
            "created_at": datetime.now().isoformat(),
        })
        st.success("Agendado.")
        st.rerun()
    if col_b.button("Agendar comparação de preços"):
        _append({
            "id": str(uuid.uuid4()),
            "title": "Comparar preços versus concorrência",
            "category": "Comparação de preços",
            "marketplace": "Todos",
            "when": str(datetime.now().date()),
            "status": "pendente",
            "created_at": datetime.now().isoformat(),
        })
        st.success("Agendado.")
        st.rerun()
    if col_c.button("Agendar revisão de catálogo"):
        _append({
            "id": str(uuid.uuid4()),
            "title": "Revisão de saúde do catálogo",
            "category": "Catálogo",
            "marketplace": "Todos",
            "when": str(datetime.now().date()),
            "status": "pendente",
            "created_at": datetime.now().isoformat(),
        })
        st.success("Agendado.")
        st.rerun()
    with col_d:
        if st.button("Analisar oportunidade ou desafio"):
            _append({
                "id": str(uuid.uuid4()),
                "title": "Analisar oportunidade/desafio de mercado",
                "category": "Oportunidade/Desafio",
                "marketplace": "Todos",
                "when": str(datetime.now().date()),
                "status": "pendente",
                "created_at": datetime.now().isoformat(),
            })
            st.success("Agendado.")
            st.rerun()

tasks = _load()
if not tasks:
    st.info("Sem tarefas agendadas.")
    st.stop()

df = pd.DataFrame(tasks)
df = df.sort_values(["when", "created_at"], ascending=[True, True]).reset_index(drop=True)

for idx, row in df.iterrows():
    with st.container():
        left, center, right = st.columns([6, 4, 6])
        with left:
            st.write(f"**{row['title']}**")
            st.caption(f"{row['category']} • {row['marketplace']}")
        with center:
            st.write(row["when"])
            st.caption(row["status"])
        with right:
            if st.button("Concluir", key=f"done-{idx}") and row["status"] != "Concluída":
                _update(idx, status="Concluída")
                st.success("Concluída.")
                st.rerun()
            if st.button("Remover", key=f"del-{idx}"):
                _delete(idx)
                st.warning("Removida.")
                st.rerun()

st.subheader("Visão geral")
if not df.empty:
    st.bar_chart(df.groupby("category").size().reset_index(name="count").set_index("category")["count"])


def _load() -> list[dict]:
    if not AGENDA_PATH.exists():
        return []
    lines = AGENDA_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def _append(task: dict) -> None:
    with AGENDA_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(task, ensure_ascii=False) + "\n")


def _update(idx: int, **kwargs):
    tasks = _load()
    if idx >= len(tasks):
        return
    tasks[idx] = {**tasks[idx], **kwargs}
    AGENDA_PATH.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in tasks), encoding="utf-8")


def _delete(idx: int):
    tasks = _load()
    if idx >= len(tasks):
        return
    tasks.pop(idx)
    AGENDA_PATH.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in tasks), encoding="utf-8")
