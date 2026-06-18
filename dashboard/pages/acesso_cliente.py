"""Acesso de cliente: login e visão própria do painel."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from integrations.white_label import BrandManager

DATA = Path(__file__).resolve().parent.parent.parent / "data"

st.set_page_config(page_title="Acesso do Cliente", layout="wide", page_icon="👤")

st.markdown("# 👤 Acesso do Cliente")
st.caption("Área de acesso e preferências de visual.")

c1, c2 = st.columns(2)
with c1:
    st.subheader("Entrar")
    customer = st.text_input("ID do cliente / Tenant", value="demo")
    st.button("Entrar", disabled=not customer.strip())
    st.caption("Use IDs retornados pelo white-label para entrar.")

with c2:
    st.subheader("Perfil")
    profiles = sorted(DATA.glob("user_preferences.jsonl"))
    if profiles:
        try:
            lines = profiles[-1].read_text(encoding="utf-8").strip().splitlines()
            rows = [__import__("json").loads(line) for line in lines]
            df = pd.DataFrame(rows)
            st.table(df.head(20))
        except Exception as e:
            st.warning(str(e))
    else:
        st.info("Sem preferências ainda.")

manager = BrandManager()
for brand in manager.list_brands()[:20]:
    with st.expander(brand.name):
        st.write(brand.to_dict())
