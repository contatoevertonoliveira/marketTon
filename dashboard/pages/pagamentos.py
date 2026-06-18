"""Pagamentos: gestão de gateways e ledger."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from integrations.payments.ledger import PaymentLedger
from integrations.payments.mercadopago import MercadoPagoGateway
from integrations.payments.pagarme import PagarMeGateway

DATA = Path(__file__).resolve().parent.parent.parent / "data"
st.set_page_config(page_title="Pagamentos", layout="wide", page_icon="💳")

st.markdown("# 💳 Pagamentos")
st.caption("Ledger unificado e status de gateways.")

ledger = PaymentLedger()
mp = MercadoPagoGateway()
pg = PagarMeGateway()

with st.sidebar:
    st.subheader("Novo pagamento (stub)")
    gateway = st.selectbox("Gateway", [mp.name, pg.name])
    amount_reais = st.number_input("Valor (R$)", min_value=0.0, value=100.0, step=0.01)
    pay = st.button("Criar pagamento")
    if pay:
        g = mp if gateway == mp.name else pg
        result = g.create_payment(int(amount_reais * 100))
        rec = ledger.append(result, metadata={"gateway": gateway, "amount_reais": amount_reais})
        st.success(f"Criado {rec.tx_id} ({result.status})")
        st.rerun()

records = sorted(ledger._cache.values(), key=lambda x: x.created_at, reverse=True)
if records:
    st.subheader("Ledger")
    df = pd.DataFrame([r.to_dict() for r in records])
    st.dataframe(df, use_container_width=True)
else:
    st.info("Sem registros.")
