import React, { useEffect, useMemo, useState } from "react";
import { getJSON } from "../lib/apiClient";
import ProductCard from "./ProductCard";
import ProductCardModal from "./ProductCardModal";

const MARKETPLACES = [
  { id: "mercado_livre", name: "Mercado Livre", icon: "🛒" },
  { id: "shopee", name: "Shopee", icon: "🛍️" },
  { id: "amazon", name: "Amazon", icon: "📦" },
  { id: "tiktok_shop", name: "TikTok Shop", icon: "🎵" },
];

const STATE_LABELS = {
  DISCOVERED: "Vinculado",
  ANALYZING: "Em análise",
  WATCHLIST: "Em observação",
  RECOMMENDED: "Recomendado",
  AFFILIATION_PENDING: "Afiliação pendente",
  AFFILIATED: "Afiliado",
  PORTFOLIO_ACTIVE: "No portfólio",
  CREATIVE_PENDING: "Criativo pendente",
  READY_TO_PUBLISH: "Pronto p/ publicar",
  PUBLISHED: "Publicado",
  MONITORING: "Monitorando",
  OPTIMIZATION_REQUIRED: "Otimizar",
  SCALING: "Escalando",
  PAUSED: "Pausado",
};

export default function Produtos() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [active, setActive] = useState(null);
  const [selected, setSelected] = useState(null);

  function load() {
    getJSON("/portfolio/affiliated")
      .then((data) => {
        setRows(data);
        setError("");
      })
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  const counts = useMemo(() => {
    const c = {};
    (rows || []).forEach((r) => {
      c[r.item.marketplace] = (c[r.item.marketplace] || 0) + 1;
    });
    return c;
  }, [rows]);

  useEffect(() => {
    if (rows && !active) {
      const first = MARKETPLACES.find((m) => counts[m.id]) || MARKETPLACES[0];
      setActive(first.id);
    }
  }, [rows, active, counts]);

  const sections = useMemo(() => {
    const groups = {};
    (rows || [])
      .filter((r) => r.item.marketplace === active)
      .forEach((r) => {
        (groups[r.category_group] = groups[r.category_group] || []).push(r);
      });
    return Object.entries(groups).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  }, [rows, active]);

  if (error) {
    return <p style={{ color: "#f5365c" }}>Não foi possível carregar os produtos ({error}).</p>;
  }
  if (rows === null) {
    return <p style={{ color: "#8898aa" }}>Carregando...</p>;
  }

  const selectedItem = selected ? selected.item : null;

  return (
    <div>
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e9ecef", marginBottom: 18 }}>
        {MARKETPLACES.map((m) => {
          const isActive = m.id === active;
          return (
            <button
              key={m.id}
              onClick={() => setActive(m.id)}
              style={{
                border: "none",
                background: "transparent",
                padding: "10px 16px",
                fontSize: 14,
                fontWeight: isActive ? 700 : 500,
                color: isActive ? "#5e72e4" : "#8898aa",
                borderBottom: isActive ? "2px solid #5e72e4" : "2px solid transparent",
                cursor: "pointer",
              }}
            >
              {m.icon} {m.name} ({counts[m.id] || 0})
            </button>
          );
        })}
      </div>

      {sections.length === 0 ? (
        <div style={{ background: "#fff", borderRadius: 10, padding: 20, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", fontSize: 13, color: "#8898aa" }}>
          Nenhum produto vinculado neste marketplace ainda. Abra um produto em Portfólio e clique em "Afiliar-se a este produto".
        </div>
      ) : (
        sections.map(([category, list]) => (
          <section key={category} style={{ marginBottom: 26 }}>
            <h6 style={{ color: "#32325d", margin: "0 0 10px" }}>
              {category} <span style={{ color: "#8898aa", fontWeight: 400 }}>({list.length})</span>
            </h6>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 190px)", gap: 14 }}>
              {list.map((r) => (
                <div key={r.item.id}>
                  <ProductCard product={r.product} onClick={() => setSelected(r)} />
                  <div style={{ marginTop: 4, fontSize: 11, fontWeight: 700, color: "#5e72e4", textAlign: "center" }}>
                    {STATE_LABELS[r.item.state] || r.item.state}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))
      )}

      {selected && (
        <ProductCardModal
          product={selected.product}
          portfolioItem={selectedItem}
          onClose={() => setSelected(null)}
          onChanged={load}
        />
      )}
    </div>
  );
}
