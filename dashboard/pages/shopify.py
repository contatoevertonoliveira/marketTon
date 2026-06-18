"""Adiciona a página do Shopify em pages/1_shopify.py para focar na visão do usuário para Shopify."""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import numpy as np

st.set_page_config(page_title="Shopify — Visão da Loja", layout="wide", page_icon="🛍️")

st.markdown("# 🛍️ Shopify — Visão da Loja")
st.markdown("Monitoramento de desempenho, catálogo e oportunidades na Shopify.")
st.markdown("---")

period_days = st.slider("Período (dias)", min_value=1, max_value=90, value=30)
end_date = datetime.now()
start_date = end_date - timedelta(days=period_days)
dates = pd.date_range(start=start_date, end=end_date, freq="D")

np.random.seed(2024)
df = pd.DataFrame({
    "date": dates,
    "visits": np.random.randint(250, 900, size=len(dates)),
    "sessions": np.random.randint(200, 800, size=len(dates)),
    "orders": np.random.randint(2, 35, size=len(dates)),
    "revenue": np.random.normal(2000, 650, size=len(dates)).clip(min=300),
    "bounce_rate": np.random.uniform(0.28, 0.75, size=len(dates)),
    "avg_session_seconds": np.random.randint(90, 420, size=len(dates)),
})

df["conversion_rate"] = (df["orders"] / df["sessions"].replace(0, 1))
df["aov"] = df["revenue"] / df["orders"].replace(0, 1)
df["items_per_session"] = np.random.uniform(1.05, 3.20, size=len(dates))

# Sidebar KPIs
st.sidebar.header("KPIs Shopify")
kpi_visits = int(df["visits"].sum())
kpi_orders = int(df["orders"].sum())
kpi_revenue = float(df["revenue"].sum())
kpi_conv = float(df["conversion_rate"].mean())
kpi_aov = float(df["aov"].replace([float("inf"), float("nan")], 0).mean())
kpi_bounce = float(df["bounce_rate"].mean())

st.sidebar.metric("👀 Visitas", f"{kpi_visits:,}".replace(",", "."))
st.sidebar.metric("🧾 Pedidos", f"{kpi_orders:,}".replace(",", "."))
st.sidebar.metric("💰 Faturamento", f"R$ {kpi_revenue:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
st.sidebar.metric("🎯 Conversão", f"{kpi_conv*100:.2f}%")
st.sidebar.metric("🎟 Ticket Médio", f"R$ {kpi_aov:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
st.sidebar.metric("📉 Bounce Rate", f"{kpi_bounce*100:.2f}%")

# Métricas principais
c1, c2, c3, c4 = st.columns(4)
c1.metric("Visitas", f"{kpi_visits:,}".replace(",", "."))
c2.metric("Pedidos", f"{kpi_orders:,}".replace(",", "."))
c3.metric("Conversão Média", f"{kpi_conv*100:.2f}%", delta=f"{(kpi_conv - 0.025)*100:.2f}%")
c4.metric("Faturamento", f"R$ {kpi_revenue:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

# Gráficos principais
st.subheader("Sessões e Pedidos")
st.line_chart(df.set_index("date")[["sessions", "orders"]])

st.subheader("Faturamento Diário")
st.line_chart(df.set_index("date")[["revenue"]])

st.subheader("Ticket Médio Diário (AOV)")
st.line_chart(df.set_index("date")[["aov"]])

# Tabela de top produtos simulada
products = [
    "Camiseta Dry Fit Premium",
    "Calça Legging Power",
    "Tênis Runner Pro",
    "Garrafa Térmica 1L",
    "Relógio Fitness X",
    "Boné Trucker Classic",
    "Mochila Urban Lite",
    "Óculos Solar UV",
    "Fone Bluetooth V5",
    "Meias Pacote 3 pares",
]
products_df = pd.DataFrame({
    "Produto": products,
    "Estoque": np.random.randint(0, 200, size=len(products)),
    "Preço": np.random.uniform(49.9, 249.9, size=len(products)).round(2),
    "Vendas 30d": np.random.randint(5, 120, size=len(products)),
    "Receita 30d": np.random.randint(300, 9000, size=len(products)),
    "Margem %": np.random.randint(20, 70, size=len(products)),
})
products_df = products_df.sort_values(by="Receita 30d", ascending=False).reset_index(drop=True)

st.subheader("Top Produtos (Shopify)")
st.table(products_df)

st.caption("Dados simulados para validação do dashboard. Substitua por integração real com Shopify API quando disponível.")
