import React, { useState } from "react";
import { postJSON } from "../lib/apiClient";
import ProductDetailDrawer from "./ProductDetail";
import { logisticSpeedRank, sellerLocation, shipsFromBrazil } from "../lib/productSignals";

function fmtMoney(v, currency) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("pt-BR", { style: "currency", currency: currency || "BRL" });
}

// Quick-view de um produto do catálogo ainda fora (ou já dentro) do
// portfólio. Fora: mostra os dados reais extraídos do marketplace + o botão
// de afiliação. Dentro: abre direto o drawer de gestão do funil, que já sabe
// quais transições de estado são válidas a partir de onde o item está.
export default function ProductCardModal({ product, portfolioItem, onClose, onChanged }) {
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [justAdded, setJustAdded] = useState(null);

  if (portfolioItem || justAdded) {
    return (
      <ProductDetailDrawer
        portfolioItem={portfolioItem || justAdded}
        onClose={onClose}
        onChanged={() => {
          onChanged();
          onClose();
        }}
      />
    );
  }

  async function affiliate() {
    setAdding(true);
    setError("");
    try {
      const item = await postJSON("/portfolio/items", { product_id: product.id });
      setJustAdded(item);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setAdding(false);
    }
  }

  const image = product.images?.[0];

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(23,43,77,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 200,
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 16,
          width: "min(640px, 100%)",
          maxHeight: "88vh",
          overflowY: "auto",
          boxShadow: "0 20px 60px rgba(23,43,77,.35)",
        }}
      >
        <div style={{ display: "flex", gap: 16, padding: 20 }}>
          <div style={{ width: 160, flexShrink: 0, borderRadius: 10, overflow: "hidden", background: "#f6f9fc", aspectRatio: "1 / 1" }}>
            {image ? (
              <img src={image} alt={product.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            ) : (
              <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#c1c9d6", fontSize: 12 }}>
                sem foto
              </div>
            )}
          </div>

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div style={{ fontSize: 11, color: "#8898aa", textTransform: "uppercase" }}>{product.marketplace}</div>
              <button onClick={onClose} style={{ border: "none", background: "transparent", fontSize: 20, cursor: "pointer", color: "#8898aa" }}>
                ×
              </button>
            </div>
            <h5 style={{ margin: "2px 0 8px", color: "#32325d" }}>{product.title}</h5>

            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span style={{ fontSize: 22, fontWeight: 700, color: "#32325d" }}>{fmtMoney(product.price, product.currency)}</span>
              {product.original_price > product.price && (
                <span style={{ fontSize: 13, color: "#8898aa", textDecoration: "line-through" }}>
                  {fmtMoney(product.original_price, product.currency)}
                </span>
              )}
              {product.discount_pct > 0 && (
                <span style={{ fontSize: 12, fontWeight: 700, color: "#f5365c" }}>-{Math.round(product.discount_pct)}%</span>
              )}
            </div>

            <div style={{ fontSize: 12, color: "#525f7f", marginTop: 8, display: "flex", gap: 14, flexWrap: "wrap" }}>
              <span>{product.rating != null ? `⭐ ${product.rating.toFixed(1)} (${product.review_count ?? 0})` : "sem avaliação"}</span>
              <span>{product.sold_quantity ? `${product.sold_quantity} vendido(s)` : "sem dado de vendas"}</span>
              {product.scores?.OPPORTUNITY != null && <span>Oportunidade: {product.scores.OPPORTUNITY.toFixed(0)}/100</span>}
            </div>

            <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {product.affiliate_commission_pct != null ? (
                <span style={{ background: "#e5faf1", color: "#1a7a54", fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "3px 10px" }}>
                  comissão {product.affiliate_commission_pct.toFixed(0)}%
                </span>
              ) : (
                <span style={{ fontSize: 12, color: "#8898aa" }}>comissão não informada pela API deste marketplace</span>
              )}
              {product.seller_is_official_store && (
                <span style={{ background: "#eef2ff", color: "#5e72e4", fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "3px 10px" }}>
                  loja oficial
                </span>
              )}
              {logisticSpeedRank(product) === 3 && (
                <span style={{ background: "#fff4e5", color: "#b8720a", fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "3px 10px" }}>
                  ⚡ entrega rápida
                </span>
              )}
            </div>

            <div style={{ fontSize: 12, color: "#525f7f", marginTop: 8 }}>
              Vendedor: {product.seller_nickname || "não identificado"}
              {product.seller_reputation_level && ` · reputação ${product.seller_reputation_level}`}
              {sellerLocation(product) && ` · ${sellerLocation(product)}`}
              {shipsFromBrazil(product) && " · despacha do Brasil"}
            </div>

            {(product.affiliate_url || product.product_url) && (
              <a
                href={product.affiliate_url || product.product_url}
                target="_blank"
                rel="noreferrer"
                style={{ display: "inline-block", marginTop: 10, fontSize: 12, color: "#5e72e4" }}
              >
                {product.affiliate_url ? "abrir link de afiliado ↗" : "abrir anúncio ↗"}
              </a>
            )}

            {error && <div style={{ fontSize: 12, color: "#f5365c", marginTop: 8 }}>{error}</div>}

            <button
              onClick={affiliate}
              disabled={adding}
              style={{
                marginTop: 16,
                width: "100%",
                background: "#2dce89",
                color: "#fff",
                border: "none",
                borderRadius: 8,
                padding: "10px 16px",
                fontSize: 14,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {adding ? "Adicionando…" : "Afiliar-se a este produto"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
