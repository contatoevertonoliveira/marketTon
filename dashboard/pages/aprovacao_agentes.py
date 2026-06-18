"""Página de Aprovação dos Agentes — carrega versão HTML two-column."""
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="Aprovação dos Agentes", layout="wide", page_icon="🧠")

st.markdown(
    """
    <style>
    /* Remove header/footer/sidebar do Streamlit para colar o conteúdo no topo */
    header[data-testid="stHeader"] { display: none !important; height: 0 !important; }
    div[data-testid="stToolbar"] { display: none !important; height: 0 !important; }
    footer { display: none !important; height: 0 !important; }
    .stApp { margin-top: -60px !important; }
    #MainMenu { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

html_path = Path(__file__).resolve().parents[1] / "marketplace.html"
html = html_path.read_text(encoding="utf-8")

st.components.v1.html(html, height=1200, scrolling=True)
