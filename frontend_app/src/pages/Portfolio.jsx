import React, { useEffect, useState } from "react";
import { getJSON } from "../lib/apiClient";
import ProductDetailDrawer from "./ProductDetail";
import ProductCard from "./ProductCard";
import ProductCardModal from "./ProductCardModal";

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

const MARKETPLACES = {
  mercado_livre: { name: "Mercado Livre", icon: "🛒" },
  shopee: { name: "Shopee", icon: "🛍️" },
  amazon: { name: "Amazon", icon: "📦" },
  tiktok_shop: { name: "TikTok Shop", icon: "🎵" },
};

export default function Portfolio() {
  const [enabled, setEnabled] = useState(null); // null = carregando
  const [active, setActive] = useState(null);
  const [products, setProducts] = useState([]);
  const [items, setItems] = useState([]);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [selectedBoardItem, setSelectedBoardItem] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getJSON("/marketplaces/credentials")
      .then((data) => {
        const on = data.filter((c) => c.enabled).map((c) => c.marketplace);
        setEnabled(on);
        setActive((prev) => (prev && on.includes(prev) ? prev : on[0] || null));
      })
      .catch((e) => setError(e.message));
  }, []);

  function load() {
    if (!active) return;
    Promise.all([
      getJSON(`/catalog/products?marketplace=${active}&limit=100`),
      getJSON(`/portfolio/items?marketplace=${active}&limit=500`),
    ])
      .then(([p, i]) => {
        setProducts(Array.isArray(p) ? p : p.items || []);
        setItems(Array.isArray(i) ? i : i.items || []);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }

  useEffect(load, [active]);

  if (error) {
    return <p style={{ color: "#f5365c" }}>Não foi possível falar com o backend ({error}). Confira se você está logado e se a API está no ar.</p>;
  }
  if (enabled === null) {
    return <p style={{ color: "#8898aa" }}>Carregando...</p>;
  }
  if (enabled.length === 0) {
    return (
      <div style={{ background: "#fff", borderRadius: 10, padding: 24, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)" }}>
        <strong style={{ color: "#32325d" }}>Nenhum marketplace ativado</strong>
        <p style={{ color: "#525f7f", fontSize: 13, marginTop: 8 }}>
          Ative pelo menos um marketplace em Integrações para ver produtos aqui.
        </p>
      </div>
    );
  }

  const itemByProductId = Object.fromEntries(items.map((i) => [i.product_id, i]));
  const byState = STATE_ORDER.reduce((acc, s) => {
    acc[s] = items.filter((i) => i.state === s);
    return acc;
  }, {});
  const productById = Object.fromEntries(products.map((p) => [p.id, p]));

  const sorted = [...products].sort((a, b) => (b.scores?.OPPORTUNITY ?? -1) - (a.scores?.OPPORTUNITY ?? -1));

  return (
    <div>
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e9ecef", marginBottom: 18 }}>
        {enabled.map((slug) => {
          const meta = MARKETPLACES[slug] || { name: slug, icon: "🔌" };
          const isActive = slug === active;
          return (
            <button
              key={slug}
              onClick={() => setActive(slug)}
              style={{
                border: "none",
                background: "transparent",
                padding: "10px 16px",
                fontSize: 14,
                fontWeight: isActive ? 700 : 500,
                color: isActive ? "#5e72e4" : "#8898aa",
                borderBottom: isActive ? "2px solid #5e72e4" : "2px solid transparent",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span>{meta.icon}</span> {meta.name}
            </button>
          );
        })}
      </div>

      <h6 style={{ color: "#32325d", margin: "0 0 12px" }}>
        Produtos sugeridos {MARKETPLACES[active]?.name ? `— ${MARKETPLACES[active].name}` : ""}
      </h6>
      {sorted.length === 0 ? (
        <div style={{ background: "#fff", borderRadius: 10, padding: 20, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", fontSize: 13, color: "#8898aa" }}>
          Nenhum produto no catálogo ainda para este marketplace. Rode <code>scripts/ingest.py --marketplace {active}</code> para coletar.
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 190px)", gap: 14 }}>
          {sorted.map((p) => (
            <ProductCard key={p.id} product={p} onClick={() => setSelectedProduct(p)} />
          ))}
        </div>
      )}

      <div style={{ marginTop: 28, display: "flex", gap: 12, overflowX: "auto", paddingBottom: 8 }}>
        {STATE_ORDER.map((state) => (
          <div key={state} style={{ minWidth: 220, flex: "0 0 auto" }}>
            <div style={{ fontSize: 11, color: "#8898aa", textTransform: "uppercase", marginBottom: 6 }}>
              {state} ({byState[state].length})
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {byState[state].map((item) => (
                <div
                  key={item.id}
                  onClick={() => setSelectedBoardItem(item)}
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
                  {item.label || productById[item.product_id]?.title || `Produto #${item.product_id}`}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {selectedProduct && (
        <ProductCardModal
          product={selectedProduct}
          portfolioItem={itemByProductId[selectedProduct.id]}
          onClose={() => setSelectedProduct(null)}
          onChanged={load}
        />
      )}

      {selectedBoardItem && (
        <ProductDetailDrawer
          portfolioItem={selectedBoardItem}
          onClose={() => setSelectedBoardItem(null)}
          onChanged={() => {
            load();
            setSelectedBoardItem(null);
          }}
        />
      )}
    </div>
  );
}
