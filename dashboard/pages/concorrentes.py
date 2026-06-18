"""Concorrentes: busca em anúncios/marketplaces e visualização de diferenciais."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from integrations.marketplaces.registry import list_adapter_names, resolve
from integrations.ads_meta.client import ads_library_adsearch as meta_search
from integrations.ads_tiktok.client import search_ads as tiktok_search

st.set_page_config(page_title="Concorrentes", layout="wide", page_icon="🕵️")

st.markdown("# 🕵️ Concorrentes")
st.markdown("Pesquise concorrentes em plataformas de anúncios e marketplaces ativos.")

with st.sidebar:
    st.subheader("Fontes")
    source_meta = st.checkbox("Meta Ads Library", value=True)
    source_tiktok = st.checkbox("TikTok Ads Library", value=True)
    source_marketplaces = st.checkbox("Marketplaces parceiros", value=True)
    st.markdown("---")
    country = st.text_input("País (código)", value="BR")
    limit = st.slider("Limite por fonte", min_value=5, max_value=50, value=20)

query = st.text_input("Buscar termo (produto, nicho, concorrente)", value="calça legging")

frames: list[pd.DataFrame] = []
try:
    if source_meta and query:
        rows = meta_search(query, country=country, limit=limit)
        frames.append(pd.DataFrame(rows).assign(source="meta") if rows else pd.DataFrame())
except Exception as e:  # noqa: BLE001
    st.info(f"Meta indisponível agora: {e}")

try:
    if source_tiktok and query:
        rows = tiktok_search(query, country=country, limit=limit)
        frames.append(pd.DataFrame(rows).assign(source="tiktok") if rows else pd.DataFrame())
except Exception as e:  # noqa: BLE001
    st.info(f"TikTok indisponível agora: {e}")

try:
    if source_marketplaces and query:
        adapter_frames = []
        for name in list_adapter_names():
            adapter = resolve(name)
            if adapter is None:
                continue
            try:
                products = adapter.fetch_products()
                if products is None or products.empty:
                    continue
                matches = _keyword_match(products, query)
                if not matches.empty:
                    adapter_frames.append(matches.assign(source=name))
            except Exception as e:  # noqa: BLE001
                st.warning(f"[marketplace:{name}] {e}")
        if adapter_frames:
            frames.append(pd.concat(adapter_frames, ignore_index=True))
except Exception as e:  # noqa: BLE001
    st.warning(f"Falha em marketplaces: {e}")

if not frames:
    st.info("Aguardando fontes habilitadas e termo de busca.")
else:
    combined = pd.concat(frames, ignore_index=True)
    if combined.empty:
        st.info("Sem concorrentes encontrados para esse termo.")
    else:
        st.subheader("Ads encontradas")
        st.dataframe(combined.head(limit), use_container_width=True)
        st.download_button(
            "Exportar CSV",
            combined.to_csv(index=False).encode("utf-8"),
            f"concorrentes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "text/csv",
        )


def _keyword_match(frame: pd.DataFrame, query: str):
    cols = [c for c in frame.columns if frame[c].dtype == object]
    if not cols:
        return pd.DataFrame()
    mask = frame[cols].astype(str).apply(lambda col: col.str.contains(query, case=False, na=False)).any(axis=1)
    return frame[mask]
