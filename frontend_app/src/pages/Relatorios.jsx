import React, { useCallback, useEffect, useState } from "react";
import { getJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", marginBottom: 16 };
const KIND = {
  monitor: ["#eef0f6", "#525f7f", "verificação"], resumo: ["#eef2ff", "#3b4fb8", "resumo"], achado: ["#fff4e5", "#b8720a", "achado"],
  acao: ["#e5faf1", "#1a7a54", "ação"], ideia: ["#f3ecff", "#6b3fb8", "ideia"], alerta: ["#fef1f4", "#c31e3f", "alerta"],
};
const when = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");

function Chip({ k }) {
  const [bg, fg, label] = KIND[k] || ["#eef0f6", "#525f7f", k];
  return <span style={{ background: bg, color: fg, fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "2px 9px", whiteSpace: "nowrap" }}>{label}</span>;
}

export default function Relatorios() {
  const [items, setItems] = useState(null);
  const [kind, setKind] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    getJSON(`/agent/reports?limit=150${kind ? `&kind=${kind}` : ""}`).then((d) => { setItems(d.items); setError(""); }).catch((e) => setError(e.message));
  }, [kind]);
  useEffect(() => { load(); const id = setInterval(load, 60000); return () => clearInterval(id); }, [load]);

  const chip = (value, label) => (
    <button key={value} onClick={() => setKind(value)}
      style={{ border: "1px solid #dee2e6", borderRadius: 999, padding: "4px 12px", fontSize: 12, cursor: "pointer",
        background: kind === value ? "#5e72e4" : "#fff", color: kind === value ? "#fff" : "#525f7f" }}>{label}</button>
  );

  return (
    <div>
      <p style={{ fontSize: 12, color: "#8898aa", marginTop: 4 }}>
        O que o agente verificou, fez, encontrou e sugere. Quatro verificações por dia: se nada mudou, ela termina sem gastar token e aparece aqui como “tudo normal”.
      </p>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {chip("", "Tudo")}
        {Object.entries(KIND).map(([k, v]) => chip(k, v[2]))}
      </div>
      {error && <div style={{ ...card, color: "#c31e3f", fontSize: 12 }}>{error}</div>}
      <div style={{ ...card, padding: 0, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "#8898aa", fontSize: 11, textTransform: "uppercase" }}>
              <th style={{ padding: "10px 14px" }}>Quando</th><th>Tipo</th><th>O quê</th><th>Detalhes</th>
            </tr>
          </thead>
          <tbody>
            {(items || []).map((r) => (
              <tr key={r.id} style={{ borderTop: "1px solid #f0f2f5", verticalAlign: "top" }}>
                <td style={{ padding: "10px 14px", whiteSpace: "nowrap", color: "#525f7f" }}>{when(r.created_at)}</td>
                <td style={{ padding: "10px 8px" }}><Chip k={r.kind} /></td>
                <td style={{ padding: "10px 8px", fontWeight: 600, color: "#32325d" }}>{r.title}</td>
                <td style={{ padding: "10px 8px", color: "#525f7f", whiteSpace: "pre-wrap", maxWidth: 520 }}>{r.body || "—"}</td>
              </tr>
            ))}
            {items && items.length === 0 && (
              <tr><td colSpan={4} style={{ padding: 20, color: "#8898aa", textAlign: "center" }}>Ainda não há relatórios. A primeira verificação aparece aqui.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
