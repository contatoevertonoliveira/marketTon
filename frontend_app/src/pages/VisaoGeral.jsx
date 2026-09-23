import React, { useEffect, useState } from "react";
import { getJSON } from "../lib/apiClient";
import DailyOps from "./DailyOps";

const MARKETPLACES = {
  mercado_livre: { name: "Mercado Livre", icon: "🛒" },
  shopee: { name: "Shopee", icon: "🛍️" },
  amazon: { name: "Amazon", icon: "📦" },
  tiktok_shop: { name: "TikTok Shop", icon: "🎵" },
};

// Uma aba por marketplace ativado em Integrações, cada uma com o Daily Ops
// (briefing §9) filtrado só àquele marketplace — não um resumo à parte.
export default function VisaoGeral() {
  const [enabled, setEnabled] = useState(null); // null = carregando
  const [active, setActive] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getJSON("/marketplaces/credentials")
      .then((data) => {
        const on = data.filter((c) => c.enabled).map((c) => c.marketplace);
        setEnabled(on);
        setActive((prev) => (prev && on.includes(prev) ? prev : on[0] || null));
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error) {
    return <p style={{ color: "#f5365c" }}>Não foi possível carregar os marketplaces: {error}</p>;
  }
  if (enabled === null) {
    return <p style={{ color: "#8898aa" }}>Carregando...</p>;
  }
  if (enabled.length === 0) {
    return (
      <div style={{ background: "#fff", borderRadius: 10, padding: 24, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)" }}>
        <strong style={{ color: "#32325d" }}>Nenhum marketplace ativado</strong>
        <p style={{ color: "#525f7f", fontSize: 13, marginTop: 8 }}>
          Ative pelo menos um marketplace em Integrações para ver o dashboard aqui.
        </p>
      </div>
    );
  }

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
      <DailyOps key={active} marketplace={active} />
    </div>
  );
}
