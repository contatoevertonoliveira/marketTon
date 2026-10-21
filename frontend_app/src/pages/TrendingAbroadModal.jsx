import React from "react";

function fmtMoney(v, currency) {
  if (v === null || v === undefined) return "—";
  try {
    return Number(v).toLocaleString("pt-BR", { style: "currency", currency: currency || "USD" });
  } catch {
    return `${currency || ""} ${Number(v).toFixed(2)}`;
  }
}

export default function TrendingAbroadModal({ product, onClose }) {
  const image = product.images?.[0];
  const isCheapest =
    product.competing_price_min != null && product.price != null && product.price <= product.competing_price_min + 0.01;

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
              <span style={{ fontSize: 11, color: "#8898aa", textTransform: "uppercase" }}>
                {product.country} · Mercado Livre {product.site_id}
              </span>
              <button onClick={onClose} style={{ border: "none", background: "transparent", fontSize: 20, cursor: "pointer", color: "#8898aa" }}>
                ×
              </button>
            </div>
            <h5 style={{ margin: "2px 0 8px", color: "#32325d" }}>{product.title}</h5>

            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span style={{ fontSize: 22, fontWeight: 700, color: "#32325d" }}>{fmtMoney(product.price, product.currency)}</span>
              {product.ranking_position != null && (
                <span style={{ fontSize: 12, color: "#8898aa" }}>#{product.ranking_position} mais vendido da categoria</span>
              )}
            </div>

            <div style={{ fontSize: 12, color: "#525f7f", marginTop: 8 }}>
              Vendedor: {product.seller_nickname || "não identificado"}
            </div>

            {product.competing_offers ? (
              <div
                style={{
                  fontSize: 12,
                  marginTop: 10,
                  padding: "8px 10px",
                  borderRadius: 8,
                  background: isCheapest ? "#e5faf1" : "#fef1f4",
                  color: isCheapest ? "#1a7a54" : "#c31e3f",
                }}
              >
                {product.competing_offers} vendedores anunciam este mesmo produto em {product.country}, de{" "}
                {fmtMoney(product.competing_price_min, product.currency)} a {fmtMoney(product.competing_price_max, product.currency)}.{" "}
                {isCheapest ? "Este é o menor preço encontrado lá." : "Este não é o menor preço encontrado lá."}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: "#8898aa", marginTop: 10 }}>
                Sem outras ofertas confirmadas do mesmo item de catálogo em {product.country}.
              </div>
            )}

            {product.product_url && (
              <a
                href={product.product_url}
                target="_blank"
                rel="noreferrer"
                style={{ display: "inline-block", marginTop: 10, fontSize: 12, color: "#5e72e4" }}
              >
                ver anúncio original ↗
              </a>
            )}
          </div>
        </div>

        <div style={{ padding: "0 20px 20px" }}>
          <h6 style={{ color: "#32325d", marginBottom: 8 }}>Correspondência no seu catálogo brasileiro</h6>
          {product.brazil_matches?.length > 0 ? (
            <div style={{ display: "grid", gap: 8 }}>
              {product.brazil_matches.map((m) => (
                <div
                  key={m.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    background: "#f6f9fc",
                    borderRadius: 8,
                    padding: "8px 12px",
                    fontSize: 12,
                  }}
                >
                  <span style={{ color: "#32325d" }}>{m.title}</span>
                  <span style={{ color: "#525f7f", fontWeight: 600 }}>{fmtMoney(m.price, m.currency)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: "#8898aa" }}>
              Nenhuma correspondência exata de título encontrada no catálogo brasileiro ainda. Como o título vem em
              espanhol, isso não significa que o produto seja inédito no Brasil — só que não conseguimos confirmar
              automaticamente.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
