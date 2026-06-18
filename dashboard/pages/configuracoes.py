"""Configurações gerais do Marketing Digital — chaves de marketplaces e regras operacionais."""
import streamlit as st
from pathlib import Path
import json
from datetime import datetime

st.set_page_config(page_title="Configurações", layout="wide", page_icon="⚙️")

st.markdown("# ⚙️ Configurações do Sistema")
st.markdown("---")

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "settings.json"
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "max_delivery_days": 15,
    "require_national_supplier": True,
    "require_own_stock": True,
    "marketplaces": {
        "mercadolivre": {"enabled": True, "api_key": "", "secret_key": ""},
        "shopee": {"enabled": True, "api_key": "", "secret_key": ""},
        "amazon": {"enabled": True, "api_key": "", "secret_key": ""},
        "tiktok_shop": {"enabled": True, "api_key": "", "secret_key": ""},
        "aliexpress": {"enabled": False, "api_key": "", "secret_key": ""},
        "shopify": {"enabled": False, "api_key": "", "secret_key": ""},
        "magazineluiza": {"enabled": False, "api_key": "", "secret_key": ""},
        "casasbahia": {"enabled": False, "api_key": "", "secret_key": ""},
        "kabum": {"enabled": False, "api_key": "", "secret_key": ""},
    },
    "agent_rules": {
        "focus_delivery_days": True,
        "focus_national_suppliers": True,
        "focus_own_stock_only": True,
        "min_margin_pct": 20,
        "min_trend_score": 65,
    }
}

if CONFIG_PATH.exists():
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        config = DEFAULT_CONFIG.copy()
else:
    config = DEFAULT_CONFIG.copy()


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# --------------------------
# Marketplaces
# --------------------------
st.subheader("🔑 Chaves de Acesso — Marketplaces")

marketplaces_cfg = config.get("marketplaces", DEFAULT_CONFIG["marketplaces"])
grid_cols = st.columns(3)

for idx, key in enumerate(list(marketplaces_cfg.keys())):
    col = grid_cols[idx % 3]
    mp = marketplaces_cfg[key]
    with col:
        st.markdown(f"### {key.replace('_', ' ').title()}")
        mp["enabled"] = st.checkbox("Habilitado", value=bool(mp.get("enabled", False)), key=f"mp_enable_{key}")
        mp["api_key"] = st.text_input("api_key", value=str(mp.get("api_key", "")), key=f"mp_{key}_api_key")
        mp["secret_key"] = st.text_input("secret_key", value=str(mp.get("secret_key", "")), type="password", key=f"mp_{key}_secret_key")
        marketplaces_cfg[key] = mp
        if st.button("Salvar", key=f"mp_save_{key}"):
            config["marketplaces"] = marketplaces_cfg
            save_config(config)
            st.success(f"{key.replace('_', ' ').title()} salvo.")


st.markdown("---")

# --------------------------
# Regras operacionais
# --------------------------
st.subheader("📦 Regras Operacionais")

c1, c2, c3 = st.columns(3)
with c1:
    config["max_delivery_days"] = st.number_input("Prazo máximo de entrega (dias)", min_value=1, max_value=90, value=int(config.get("max_delivery_days", 15)))
with c2:
    config["require_national_supplier"] = st.checkbox("Somente fornecedores nacionais", value=bool(config.get("require_national_supplier", True)))
with c3:
    config["require_own_stock"] = st.checkbox("Apenas fornecedores com estoque próprio", value=bool(config.get("require_own_stock", True)))

st.markdown("---")

# --------------------------
# Regras dos agentes
# --------------------------
st.subheader("🤖 Regras dos Agentes")

agent_rules = config.get("agent_rules", DEFAULT_CONFIG["agent_rules"])
a1, a2, a3, a4 = st.columns(4)
with a1:
    agent_rules["focus_delivery_days"] = st.checkbox("Filtrar por prazo de entrega", value=bool(agent_rules.get("focus_delivery_days", True)))
    agent_rules["max_delivery_days"] = int(config["max_delivery_days"])
with a2:
    agent_rules["focus_national_suppliers"] = st.checkbox("Filtrar por fornecedor nacional", value=bool(agent_rules.get("focus_national_suppliers", True)))
with a3:
    agent_rules["focus_own_stock_only"] = st.checkbox("Somente estoque próprio", value=bool(agent_rules.get("focus_own_stock_only", True)))
with a4:
    agent_rules["min_margin_pct"] = st.number_input("Margem mínima (%)", min_value=0, max_value=100, value=int(agent_rules.get("min_margin_pct", 20)))

b1, b2 = st.columns(2)
with b1:
    agent_rules["min_trend_score"] = st.slider("Score mínimo de tendência", min_value=0, max_value=100, value=int(agent_rules.get("min_trend_score", 65)))
config["agent_rules"] = agent_rules

st.markdown("---")

save_all, reset_btn = st.columns(2)
with save_all:
    if st.button("💾 Salvar todas as configurações"):
        config["updated_at"] = datetime.now().isoformat()
        save_config(config)
        st.success("Configurações salvas com sucesso.")

with reset_btn:
    if st.button("♻️ Restaurar padrões"):
        config = DEFAULT_CONFIG.copy()
        save_config(config)
        st.info("Configurações restauradas para o padrão.")

st.caption("As configurações são usadas automaticamente pelos agentes e pelo pipeline de aprovação.")
