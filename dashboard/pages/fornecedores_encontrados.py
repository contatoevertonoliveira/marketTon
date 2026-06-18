"""Página de Fornecedores Encontrados — lista nacional com estoque, prazo e comissão."""
import streamlit as st
from pathlib import Path
import json

st.set_page_config(page_title="Fornecedores Encontrados", layout="wide", page_icon="🏭")

st.markdown("# 🏭 Fornecedores Encontrados")
st.markdown("---")

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "suppliers.json"

if not DATA_PATH.exists():
    st.warning("Nenhum fornecedor encontrado ainda. Os agentes ainda não indicaram fornecedores.")
    st.stop()

suppliers = json.loads(DATA_PATH.read_text(encoding="utf-8"))

# Sidebar filters
st.sidebar.header("Filtros")

max_prazo = st.sidebar.slider("Prazo máximo (dias)", min_value=1, max_value=30, value=15)
min_comissao = st.sidebar.slider("Comissão mínima (%)", min_value=0, max_value=50, value=15)
apenas_nacional = st.sidebar.checkbox("Apenas nacional com estoque próprio", value=True)
status_filter = st.sidebar.multiselect("Status", ["verificado", "pendente", "rejeitado"], default=["verificado"])
modalidade_filter = st.sidebar.multiselect("Modalidade", ["Dropshipping", "Revenda", "Afiliado"], default=["Dropshipping", "Revenda", "Afiliado"])
categoria_filter = st.sidebar.multiselect("Categorias", sorted({c for s in suppliers for c in s.get("categorias", [])}))

# Apply filters
filtered = []
for s in suppliers:
    if s.get("prazo_entrega_dias", 999) > max_prazo:
        continue
    if s.get("comissao_media_pct", 0) < min_comissao:
        continue
    if apenas_nacional and not s.get("estoque_proprio", False):
        continue
    if s.get("status") not in status_filter:
        continue
    if not any(m in s.get("modalidades", []) for m in modalidade_filter):
        continue
    if categoria_filter and not any(c in s.get("categorias", []) for c in categoria_filter):
        continue
    filtered.append(s)

st.caption(f"{len(filtered)} fornecedor(es) encontrado(s)")

# Rank suppliers by score
def score_supplier(s):
    return (
        s.get("comissao_media_pct", 0) * 0.4
        + (30 - s.get("prazo_entrega_dias", 30)) * 2
        + s.get("avaliacao", 0) * 5
    )

filtered.sort(key=score_supplier, reverse=True)

# Display cards
for s in filtered:
    with st.container():
        cols = st.columns([1, 3, 2, 2, 2, 2])
        with cols[0]:
            st.write(f"### 🏭")
        with cols[1]:
            st.subheader(s.get("nome", "Sem nome"))
            st.caption(f"{s.get('cidade', '')} - {s.get('estado', '')}")
            st.write(f"**CNPJ:** `{s.get('cnpj', '')}`")
            tags = []
            if s.get("estoque_proprio"):
                tags.append("✅ Estoque próprio")
            if s.get("prazo_entrega_dias", 999) <= 15:
                tags.append("🚚 Prazo <= 15d")
            st.write(" • ".join(tags))
        with cols[2]:
            st.metric("Prazo", f"{s.get('prazo_entrega_dias', '?')} dias")
            st.metric("Comissão", f"{s.get('comissao_media_pct', '?')}%")
        with cols[3]:
            st.metric("Avaliação", f"⭐ {s.get('avaliacao', '?')}/5")
            st.caption(f"{s.get('total_avaliacoes', '?')} avaliações")
        with cols[4]:
            st.write("**Categorias:**")
            st.write(", ".join(s.get("categorias", [])))
            st.write("**Modalidades:**")
            st.write(", ".join(s.get("modalidades", [])))
        with cols[5]:
            st.write("**Marketplaces:**")
            st.write(", ".join(s.get("marketplaces_parceiros", [])))
            st.write("**Status:**", s.get("status", "?"))
            if st.button("Ver detalhes", key=f"det_{s.get('id')}"):
                st.session_state[f"selected_supplier_{s.get('id')}"] = not st.session_state.get(f"selected_supplier_{s.get('id')}", False)
        st.markdown("---")

        if st.session_state.get(f"selected_supplier_{s.get('id')}", False):
            st.json(s)
            if st.button("Ocultar detalhes", key=f"hide_{s.get('id')}"):
                st.session_state[f"selected_supplier_{s.get('id')}"] = False
                st.rerun()

st.caption("Fornecedores indicados automaticamente pelos agentes. Revise antes de integrar ao fluxo de vendas.")
