"""Autenticação básica para proteger o dashboard."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.roles import RoleManager

DATA = Path(__file__).resolve().parent.parent.parent / "data"
USERS_PATH = DATA / "users.jsonl"
USERS_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_users() -> list[dict]:
    if not USERS_PATH.exists():
        return []
    lines = USERS_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [__import__("json").loads(line) for line in lines]


def save_user(user: dict) -> None:
    with USERS_PATH.open("a", encoding="utf-8") as f:
        f.write(__import__("json").dumps(user, ensure_ascii=False) + "\n")


def find_user(username: str) -> dict | None:
    for user in reversed(load_users()):
        if user.get("username") == username:
            return user
    return None


def login_page() -> dict | None:
    st.title("🔐 Login")
    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        user = find_user(username)
        if not user:
            st.error("Usuário ou senha inválidos.")
            return None
        if user.get("password") != password:
            st.error("Usuário ou senha inválidos.")
            return None
        return {"user_id": user["user_id"], "username": user["username"], "role": user.get("role", "viewer")}
    return None


def require_auth() -> dict:
    session = st.session_state.get("auth")
    if session:
        return session
    session = login_page()
    if session:
        st.session_state["auth"] = session
        st.success("Login efetuado.")
        st.rerun()
    st.stop()
    return {}


def admin_panel() -> None:
    st.subheader("Usuários cadastrados")
    users = load_users()
    if users:
        st.dataframe(pd.DataFrame(users).drop(columns=["password"], errors="ignore"), use_container_width=True)
    with st.expander("Novo usuário"):
        with st.form("new_user"):
            c1, c2, c3 = st.columns(3)
            with c1:
                username = st.text_input("Usuário")
            with c2:
                password = st.text_input("Senha", type="password")
            with c3:
                role = st.selectbox("Role", ["admin", "manager", "operator", "viewer"], index=3)
            user_id = st.number_input("User ID (Telegram)", min_value=0, value=0)
            add = st.form_submit_button("Criar")
            if add and username and password:
                from core.roles import Role
                rm = st.session_state.get("role_manager") or RoleManager()
                save_user({
                    "username": username,
                    "password": password,
                    "user_id": user_id,
                    "role": role,
                    "created_at": datetime.now().isoformat(),
                })
                rm.set_role(int(user_id), Role(role))
                st.success("Usuário criado.")
                st.rerun()
