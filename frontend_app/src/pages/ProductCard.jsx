import React from "react";
import { approvalVerdict, logisticSpeedRank, priceCompetitiveness, shipsFromBrazil } from "../lib/productSignals";

function fmtMoney(v, currency) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("pt-BR", { style: "currency", currency: currency || "BRL" });
}

// Card no estilo dos marketplaces (foto real, badge de desconto, preço,
// vendidos) — a mesma linguagem visual que o operador já reconhece de lá.
export default function ProductCard({ product, onClick }) {
  const image = product.images?.[0];
  const opportunity = product.scores?.OPPORTUNITY;
  const verdict = approvalVerdict(product);

  return (
    <button
      onClick={onClick}
      title={verdict.approved ? `Aprovado: ${verdict.passed.join(", ")}` : `Não aprovado ainda: falta ${verdict.failed.join(", ")}`}
      style={{
        display: "flex",
        flexDirection: "column",
        textAlign: "left",
        background: "#fff",
        border: verdict.approved ? "1px solid #2dce89" : "1px solid #eef0f5",
        borderRadius: 12,
        overflow: "hidden",
        cursor: "pointer",
        padding: 0,
        boxShadow: "0 0 1.5rem 0 rgba(136,152,170,.12)",
      }}
    >
      {verdict.approved && (
        <div
          style={{
            background: "#2dce89",
            color: "#fff",
            fontSize: 11,
            fontWeight: 700,
            textAlign: "center",
            padding: "4px 0",
          }}
        >
          ✓ Aprovado pelo sistema
        </div>
      )}
      <div style={{ position: "relative", background: "#f6f9fc", aspectRatio: "1 / 1" }}>
        {image ? (
          <img
            src={image}
            alt={product.title}
            loading="lazy"
            style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
          />
        ) : (
          <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#c1c9d6", fontSize: 12 }}>
            sem foto
          </div>
        )}
        {product.discount_pct > 0 && (
          <span
            style={{
              position: "absolute",
              top: 8,
              right: 8,
              background: "#f5365c",
              color: "#fff",
              fontSize: 11,
              fontWeight: 700,
              borderRadius: 6,
              padding: "2px 6px",
            }}
          >
            -{Math.round(product.discount_pct)}%
          </span>
        )}
        {opportunity != null && (
          <span
            style={{
              position: "absolute",
              top: 8,
              left: 8,
              background: opportunity >= 70 ? "#2dce89" : opportunity >= 40 ? "#f6c944" : "#8898aa",
              color: "#fff",
              fontSize: 11,
              fontWeight: 700,
              borderRadius: 6,
              padding: "2px 6px",
            }}
          >
            {Math.round(opportunity)} pts
          </span>
        )}
      </div>

      <div style={{ padding: 10, flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
        <div
          style={{
            fontSize: 13,
            color: "#32325d",
            lineHeight: 1.3,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            minHeight: 34,
          }}
        >
          {product.title}
        </div>

        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 2 }}>
          <span style={{ fontSize: 17, fontWeight: 700, color: "#32325d" }}>{fmtMoney(product.price, product.currency)}</span>
          {product.original_price > product.price && (
            <span style={{ fontSize: 12, color: "#8898aa", textDecoration: "line-through" }}>
              {fmtMoney(product.original_price, product.currency)}
            </span>
          )}
        </div>

        {priceCompetitiveness(product) && (
          <div style={{ fontSize: 11, color: priceCompetitiveness(product).isLowest ? "#2dce89" : "#8898aa" }}>
            {priceCompetitiveness(product).isLowest ? "✓ menor preço" : "não é o menor preço"} entre{" "}
            {priceCompetitiveness(product).offers} {priceCompetitiveness(product).confirmed ? "vendedores" : "ofertas parecidas"}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#8898aa", marginTop: 2 }}>
          <span>{product.rating != null ? `⭐ ${product.rating.toFixed(1)}` : "sem avaliação"}</span>
          <span>{product.sold_quantity ? `${product.sold_quantity} vendido(s)` : ""}</span>
        </div>

        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>
          {product.affiliate_commission_pct != null && (
            <span style={{ background: "#e5faf1", color: "#1a7a54", fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "2px 8px" }}>
              comissão {product.affiliate_commission_pct.toFixed(0)}%
            </span>
          )}
          {product.seller_is_official_store && (
            <span style={{ background: "#eef2ff", color: "#5e72e4", fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "2px 8px" }}>
              loja oficial
            </span>
          )}
          {logisticSpeedRank(product) === 3 && (
            <span style={{ background: "#fff4e5", color: "#b8720a", fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "2px 8px" }}>
              ⚡ entrega rápida
            </span>
          )}
          {shipsFromBrazil(product) && logisticSpeedRank(product) !== 3 && (
            <span style={{ background: "#f6f9fc", color: "#525f7f", fontSize: 11, borderRadius: 999, padding: "2px 8px" }}>
              🇧🇷 estoque nacional
            </span>
          )}
        </div>
      </div>
    </button>
  );
}
