"""Dashboard page: bloqueador de grupos."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from integrations.group_blocker.models import GroupBlockManager, GroupStatus
from integrations.group_blocker.repository import get_manager

DATA = Path(__file__).resolve().parent.parent.parent / "data"
st.set_page_config(page_title="Bloqueador de Grupos", layout="wide", page_icon="🔒")

st.markdown("# 🔒 Bloqueador de Grupos")
st.caption("Gerencie quais grupos podem ou não usar os recursos do bot.")

with st.sidebar:
    search = st.text_input("Buscar por título/ID", value="")
    status_filter = st.selectbox("Filtrar status", ["Todos", "allowed", "blocked"])
    st.markdown("---")
    st.subheader("Ações rápidas")
    with st.form("quick_actions"):
        group_id = st.text_input("ID do grupo", placeholder="Ex: -100123456789")
        action = st.selectbox("Ação", ["allow", "block"])
        reason = st.text_input("Motivo (opcional)")
        submit = st.form_submit_button("Aplicar")
        if submit and group_id.strip().lstrip("-").isdigit():
            mgr = get_manager()
            gid = int(group_id.strip())
            if action == "allow":
                mgr.set_status(gid, GroupStatus.ALLOWED, reason=reason or None)
                st.success("Grupo permitido.")
            else:
                mgr.set_status(gid, GroupStatus.BLOCKED, reason=reason or None)
                st.success("Grupo bloqueado.")
            st.rerun()

with st.form("add_group"):
    c1, c2, c3 = st.columns(3)
    with c1:
        new_id = st.text_input("Novo ID de grupo", placeholder="-100123456789")
    with c2:
        new_title = st.text_input("Título (opcional)")
    with c3:
        new_status = st.selectbox("Status", ["allowed", "blocked"], index=0)
    new_reason = st.text_input("Motivo (opcional)")
    add = st.form_submit_button("Adicionar/atualizar")
    if add and new_id.strip().lstrip("-").isdigit():
        mgr = get_manager()
        gid = int(new_id.strip())
        mgr.set_status(gid, GroupStatus(new_status), reason=new_reason or None)
        st.success("Salvo.")
        st.rerun()

mgr = get_manager()
items = mgr.list_groups()
if status_filter == "allowed":
    items = [i for i in items if i.status == GroupStatus.ALLOWED]
elif status_filter == "blocked":
    items = [i for i in items if i.status == GroupStatus.BLOCKED]

if search.strip():
    q = search.strip().lower()
    items = [i for i in items if q in str(i.group_id) or (i.title and q in i.title.lower())]

if not items:
    st.info("Sem grupos cadastrados.")
    st.stop()

frame = pd.DataFrame([i.to_dict() for i in items])
st.dataframe(frame, use_container_width=True)
