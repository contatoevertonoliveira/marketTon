import React, { useEffect, useState } from "react";
import { getJSON } from "../lib/apiClient";

const SITES = [
  { id: "MLM", country: "México" },
  { id: "MCO", country: "Colômbia" },
  { id: "MLC", country: "Chile" },
];

const STORAGE_KEY = "trending-abroad:sites";

function loadSavedSites() {
  const all = SITES.map((x) => x.id);
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (Array.isArray(saved)) return all.filter((id) => saved.includes(id));
  } catch {
    // localStorage indisponível ou valor corrompido: cai no padrão (todos)
  }
  return all;
}

function fmtMoney(v, currency) {
  if (v === null || v === undefined) return "—";
  try {
    return Number(v).toLocaleString("pt-BR", { style: "currency", currency: currency || "USD" });
  } catch {
    return `${currency || ""} ${Number(v).toFixed(2)}`;
  }
}

export default function TrendingAbroad() {
  const [sites, setSites] = useState(loadSavedSites);
  const [products, setProducts] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function load() {
    if (sites.length === 0) {
      setProducts([]);
      return;
    }
    setLoading(true);
    setError("");
    getJSON(`/catalog/trending-abroad?sites=${sites.join(",")}&limit_per_site=15`)
      .then(setProducts)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleSite(id) {
    const next = sites.includes(id) ? sites.filter((s) => s !== id) : [...sites, id];
    setSites(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // sem persistência: o filtro só vale nesta sessão
    }
  }

  return (
    <div>
      <p style={{ color: "#525f7f", fontSize: 13 }}>
        Mais vendidos de outros países da Mercado Livre, com o mesmo token que você já conectou — sem credencial
        nova. Não fica salvo no catálogo, é consultado ao vivo. "Já no catálogo BR" compara título e marca exatos com
        o que já coletamos no Brasil; título em espanhol quase nunca bate com o mesmo produto em português, então
        "não" aqui não garante que é inédito — é só o que conseguimos confirmar com certeza.
      </p>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
        {SITES.map((s) => (
          <label
            key={s.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: 13,
              color: "#525f7f",
              background: "#fff",
              padding: "6px 12px",
              borderRadius: 8,
              boxShadow: "0 0 1.5rem 0 rgba(136,152,170,.12)",
              cursor: "pointer",
            }}
          >
            <input type="checkbox" checked={sites.includes(s.id)} onChange={() => toggleSite(s.id)} />
            {s.country}
          </label>
        ))}
        <button
          onClick={load}
          disabled={loading || sites.length === 0}
          style={{
            background: "#5e72e4",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "7px 16px",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          {loading ? "Buscando…" : "Atualizar"}
        </button>
      </div>

      {error && <p style={{ color: "#f5365c" }}>{error}</p>}
      {!error && products === null && <p style={{ color: "#8898aa" }}>Carregando...</p>}
      {!error && products && products.length === 0 && (
        <div style={{ background: "#fff", borderRadius: 10, padding: 20, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", fontSize: 13, color: "#8898aa" }}>
          Nenhum resultado — marque pelo menos um país e clique em Atualizar.
        </div>
      )}

      {!error && products && products.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 190px)", gap: 14 }}>
          {products.map((p) => (
            <div
              key={`${p.site_id}-${p.external_id}`}
              style={{
                background: "#fff",
                border: "1px solid #eef0f5",
                borderRadius: 12,
                overflow: "hidden",
                boxShadow: "0 0 1.5rem 0 rgba(136,152,170,.12)",
              }}
            >
              <div style={{ position: "relative", background: "#f6f9fc", aspectRatio: "1 / 1" }}>
                {p.images?.[0] ? (
                  <img src={p.images[0]} alt={p.title} loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                ) : (
                  <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#c1c9d6", fontSize: 12 }}>
                    sem foto
                  </div>
                )}
                <span
                  style={{
                    position: "absolute",
                    top: 8,
                    left: 8,
                    background: "#5e72e4",
                    color: "#fff",
                    fontSize: 10,
                    fontWeight: 700,
                    borderRadius: 6,
                    padding: "2px 6px",
                  }}
                >
                  {p.country}
                </span>
                {p.ranking_position != null && (
                  <span
                    style={{
                      position: "absolute",
                      top: 8,
                      right: 8,
                      background: "#f6c944",
                      color: "#fff",
                      fontSize: 10,
                      fontWeight: 700,
                      borderRadius: 6,
                      padding: "2px 6px",
                    }}
                  >
                    #{p.ranking_position}
                  </span>
                )}
              </div>
              <div style={{ padding: 10 }}>
                <div
                  style={{
                    fontSize: 12,
                    color: "#32325d",
                    lineHeight: 1.3,
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                    overflow: "hidden",
                    minHeight: 32,
                  }}
                >
                  {p.title}
                </div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#32325d", marginTop: 4 }}>
                  {fmtMoney(p.price, p.currency)}
                </div>
                <div style={{ marginTop: 6 }}>
                  {p.already_in_brazil_catalog ? (
                    <span style={{ fontSize: 10, background: "#f6f9fc", color: "#8898aa", borderRadius: 999, padding: "2px 8px" }}>
                      já no catálogo BR
                    </span>
                  ) : (
                    <span style={{ fontSize: 10, background: "#e5faf1", color: "#1a7a54", borderRadius: 999, padding: "2px 8px" }}>
                      sem correspondência no BR
                    </span>
                  )}
                </div>
                {p.product_url && (
                  <a
                    href={p.product_url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ display: "inline-block", marginTop: 6, fontSize: 11, color: "#5e72e4" }}
                  >
                    ver anúncio original ↗
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
