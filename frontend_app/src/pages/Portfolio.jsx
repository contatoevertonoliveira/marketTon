import React, { useEffect, useState } from "react";
import { getJSON, postJSON } from "../lib/intelApi";
import ProductDetailDrawer from "./ProductDetail";

const STATE_ORDER = [
  "DISCOVERED",
  "ANALYZING",
  "WATCHLIST",
  "RECOMMENDED",
  "AFFILIATION_PENDING",
  "AFFILIATED",
  "PORTFOLIO_ACTIVE",
  "CREATIVE_PENDING",
  "READY_TO_PUBLISH",
  "PUBLISHED",
  "MONITORING",
  "OPTIMIZATION_REQUIRED",
  "SCALING",
  "PAUSED",
  "REMOVED",
];

export default function Portfolio() {
  const [products, setProducts] = useState([]);
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);

  function load() {
    Promise.all([getJSON("/products/?"), getJSON("/portfolio/")])
      .then(([p, i]) => {
        setProducts(p.results || []);
        setItems(i.results || []);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  async function addToPortfolio(productId) {
    await postJSON("/portfolio/", { product: productId });
    load();
  }

  const catalogOnly = products.filter((p) => !p.portfolio_state);
  const byState = STATE_ORDER.reduce((acc, s) => {
    acc[s] = items.filter((i) => i.state === s);
    return acc;
  }, {});

  if (error) {
    return (
      <p style={{ color: "#f5365c" }}>
        Não foi possível falar com o backend de inteligência (porta 8001): {error}
      </p>
    );
  }

  return (
    <div>
      <div style={{ background: "#fff", borderRadius: 10, padding: 16, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)" }}>
        <h6 style={{ color: "#32325d", margin: 0 }}>Catálogo (ainda fora do portfólio)</h6>
        <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
          {catalogOnly.length === 0 && (
            <span style={{ fontSize: 12, color: "#8898aa" }}>
              Nenhum produto no catálogo ainda. Rode <code>manage.py ingest_mercadolivre</code> com credenciais
              configuradas para popular.
            </span>
          )}
          {catalogOnly.map((p) => (
            <div
              key={p.id}
              style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: "1px solid #f6f9fc" }}
            >
              <div>
                <div style={{ fontSize: 13, color: "#32325d" }}>{p.title}</div>
                <div style={{ fontSize: 11, color: "#8898aa" }}>
                  {p.marketplace} · R$ {Number(p.price ?? 0).toFixed(2)} · opportunity{" "}
                  {p.latest_opportunity_score != null ? p.latest_opportunity_score.toFixed(0) : "—"}
                </div>
              </div>
              <button
                onClick={() => addToPortfolio(p.id)}
                style={{ fontSize: 12, background: "#5e72e4", color: "#fff", border: "none", borderRadius: 6, padding: "6px 10px", cursor: "pointer" }}
              >
                + portfólio
              </button>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 18, display: "flex", gap: 12, overflowX: "auto", paddingBottom: 8 }}>
        {STATE_ORDER.map((state) => (
          <div key={state} style={{ minWidth: 220, flex: "0 0 auto" }}>
            <div style={{ fontSize: 11, color: "#8898aa", textTransform: "uppercase", marginBottom: 6 }}>
              {state} ({byState[state].length})
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {byState[state].map((item) => (
                <div
                  key={item.id}
                  onClick={() => setSelected(item)}
                  style={{
                    background: "#fff",
                    borderRadius: 8,
                    padding: 10,
                    boxShadow: "0 0 1.5rem 0 rgba(136,152,170,.15)",
                    cursor: "pointer",
                    fontSize: 12,
                    color: "#32325d",
                  }}
                >
                  {item.product_title}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <ProductDetailDrawer
          portfolioItem={selected}
          onClose={() => setSelected(null)}
          onChanged={() => {
            load();
            setSelected(null);
          }}
        />
      )}
    </div>
  );
}
