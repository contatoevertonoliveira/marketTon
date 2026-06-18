"""Main dashboard page with performance overview, KPIs, trends, marketplaces, products, and AI status."""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="Marketing Digital Dashboard", layout="wide", page_icon="📊")

st.markdown("# 📊 Marketing Digital — Dashboard Executivo")
st.markdown("### Visão consolidada de vendas, tendências, marketplaces e agentes")
st.markdown("---")

# Sidebar filters
st.sidebar.header("Filtros")
days = st.sidebar.slider("Período (dias)", min_value=1, max_value=90, value=30)
regions = st.sidebar.multiselect("Regiões", ["Brasil", "USA", "Europa", "Ásia"], default=["Brasil", "USA", "Europa"])
marketplaces = st.sidebar.multiselect("Marketplaces", ["Shopee", "Mercado Livre", "TikTok Shop", "Amazon", "AliExpress", "Shopify"], default=["Shopee", "Mercado Livre", "TikTok Shop"])

end_date = datetime.now()
start_date = end_date - timedelta(days=days)

dates = pd.date_range(start=start_date, end=end_date, freq="D")
np.random.seed(42)

# Revenue
daily_revenue = np.random.normal(2500, 700, size=len(dates)).clip(min=800)
df = pd.DataFrame({"date": dates, "daily_revenue": daily_revenue})

# Additional metrics
df["expected_value"] = df["daily_revenue"] * np.random.uniform(1.05, 1.25, size=len(dates))
df["orders"] = (df["daily_revenue"] / np.random.uniform(80, 180, size=len(dates))).round().astype(int)
df["ctr"] = np.random.uniform(0.012, 0.045, size=len(dates))
df["cpa"] = np.random.uniform(8, 35, size=len(dates))
df["roas"] = df["daily_revenue"] / (df["cpa"] * df["orders"].clip(lower=1))
df["conversion_rate"] = np.random.uniform(0.01, 0.06, size=len(dates))
df["ticket_medium"] = df["daily_revenue"] / df["orders"].replace(0, 1)

# Marketplace split
market_df = pd.DataFrame({
    "marketplace": marketplaces,
    "revenue": [float(np.random.randint(1200, 4000, size=1)[0]) for _ in marketplaces],
    "orders": [int(np.random.randint(40, 180, size=1)[0]) for _ in marketplaces],
})
market_df["ticket_medium"] = (market_df["revenue"] / market_df["orders"].replace(0, 1)).round(2)

# Trends
df_br = df.copy()
df_br["trend_score"] = np.random.normal(78, 10, size=len(df_br)).clip(0, 100)
df_br["region"] = "Brasil"

df_us = df.copy()
df_us["trend_score"] = np.random.normal(85, 12, size=len(df_us)).clip(0, 100)
df_us["region"] = "USA"

df_eu = df.copy()
df_eu["trend_score"] = np.random.normal(72, 9, size=len(df_eu)).clip(0, 100)
df_eu["region"] = "Europa"

trends = pd.concat([df_br, df_us, df_eu], ignore_index=True)
trends = trends[trends["region"].isin(regions)]

# Products ranking
products = [
    "Mini Prancha Dobrável Pro",
    "Fone ANC Lite 2025",
    "Kit Ferramentas 112 peças",
    "Garrafa Térmica 1L LED",
    "Luminária Mesa Touch RGB",
    "Capa Anti-Reflexo Phone",
    "Fone Sport Clip Pro",
    "Forno Elétrico 12L",
    "Organizador Carrinho Baby",
    "Suporte Notebook Alumínio",
]
products_df = pd.DataFrame({
    "product": products,
    "trend_score": np.random.randint(55, 99, size=10),
    "revenue_30d": np.random.randint(800, 3500, size=10),
    "margin_pct": np.random.randint(25, 75, size=10),
    "competition": np.random.choice(["Baixa", "Média", "Alta"], size=10, p=[0.4, 0.35, 0.25]),
}).sort_values(by=["trend_score", "revenue_30d"], ascending=False).reset_index(drop=True)

# KPIs
st.sidebar.markdown("---")
st.sidebar.subheader("KPIs principais (período selecionado)")
kpi_total_revenue = df["daily_revenue"].sum()
kpi_expected = df["expected_value"].sum()
kpi_orders = df["orders"].sum()
kpi_ticket = df["daily_revenue"].sum() / df["orders"].replace(0, 1).sum()
kpi_roas = df["daily_revenue"].sum() / (df["cpa"].sum())
kpi_cpa = df["cpa"].mean()

st.sidebar.metric("💰 Valor Vendido", f"R$ {kpi_total_revenue:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
st.sidebar.metric("🎯 Valor Esperado", f"R$ {kpi_expected:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
st.sidebar.metric("🧾 Pedidos", f"{kpi_orders:,}".replace(",", "."))
st.sidebar.metric("🎟 Ticket Médio", f"R$ {kpi_ticket:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
st.sidebar.metric("📈 ROAS", f"{kpi_roas:,.2f}x")
st.sidebar.metric("💸 CPA", f"R$ {kpi_cpa:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

# Layout
a1, a2, a3, a4 = st.columns(4)
a1.metric("Faturamento", f"R$ {kpi_total_revenue:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
a2.metric("Valor Esperado", f"R$ {kpi_expected:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
a3.metric("Pedidos", f"{kpi_orders:,}".replace(",", "."))
a4.metric("Ticket Médio", f"R$ {kpi_ticket:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), delta=f"{(kpi_ticket - 120):.2f}".replace(".", ",") + " vs base")

# Revenue chart
st.subheader("Receita e Valor Esperado")
st.line_chart(df.set_index("date")[["daily_revenue", "expected_value"]])

# Marketplace bars
st.subheader("Marketplaces")
marketplace_sorted = market_df.sort_values("revenue", ascending=True)
st.bar_chart(marketplace_sorted.set_index("marketplace")[["revenue"]])

# Trends line
st.subheader("Tendências (score por região)")
trends_pivot = trends.pivot_table(index="date", columns="region", values="trend_score")
st.line_chart(trends_pivot)

# Daily KPIs
st.subheader("Métricas diárias (30d)")
kpi_daily = df[["date", "ctr", "conversion_rate", "cpa", "roas"]].set_index("date")
st.line_chart(kpi_daily)

# Top products
st.subheader("Top Produtos do Portfólio (simulado)")
st.table(products_df)

st.caption("Dashboard gerado com dados simulados. Evolua para integração real conectando as fontes em collectors/ e atualizando o on_ready_event.")
