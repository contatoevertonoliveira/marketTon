import React, { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", marginBottom: 16 };
const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${String(v).replace(".", ",")}%`);
const color = (v) => (v == null ? "#8898aa" : v >= 25 ? "#1a7a54" : v <= -15 ? "#c31e3f" : "#525f7f");

export default function TrendRadar() {
  const [data, setData] = useState(null);
  const [word, setWord] = useState("");
  const [msg, setMsg] = useState("");
  const [onlyRising, setOnlyRising] = useState(false);
  const load = useCallback(() => getJSON(`/trends/radar?limit=40${onlyRising ? "&only_rising=true" : ""}`).then(setData).catch((e) => setMsg(e.message)), [onlyRising]);
  useEffect(() => { load(); }, [load]);

  async function add() {
    setMsg("");
    try { await postJSON("/trends/radar/watch", { add: [word] }); setWord(""); setMsg("Palavra adicionada: entra no próximo retrato diário."); load(); } catch (e) { setMsg(e.message); }
  }
  async function remove(k) {
    try { await postJSON("/trends/radar/watch", { remove: [k] }); load(); } catch (e) { setMsg(e.message); }
  }

  return (
    <div style={card}>
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
        <div style={{ fontWeight: 700, color: "#32325d" }}>Radar de tendências (retrato diário, medido pelo sistema)</div>
        <label style={{ fontSize: 12, color: "#525f7f" }}><input type="checkbox" checked={onlyRising} onChange={(e) => setOnlyRising(e.target.checked)} /> só as que sobem</label>
      </div>
      <div style={{ fontSize: 12, color: "#8898aa", margin: "4px 0 8px" }}>
        Crescimento da busca no Google contra o período anterior do mesmo tamanho. O sistema olha 12 palavras por dia e avisa o agente só quando uma começa a subir.
        {data ? ` Vigiando ${data.watching} palavra(s); ${data.rising} em alta.` : ""}
      </div>
      {data && data.items.length === 0 && <div style={{ fontSize: 12, color: "#8898aa" }}>Ainda sem retratos: o primeiro sai no próximo ciclo do sistema.</div>}
      {data && data.items.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse", minWidth: 620 }}>
            <thead><tr style={{ textAlign: "left", color: "#8898aa" }}>{["Palavra", "7 dias", "15 dias", "30 dias", "Buscas/mês", "CPC", "Disputa", "Estado", ""].map((h) => <th key={h} style={{ padding: "4px 8px 4px 0", fontWeight: 600 }}>{h}</th>)}</tr></thead>
            <tbody>
              {data.items.map((i) => (
                <tr key={i.keyword} style={{ borderTop: "1px solid #f6f9fc" }}>
                  <td style={{ padding: "6px 8px 6px 0", fontWeight: 600, color: "#32325d" }}>{i.keyword}</td>
                  <td style={{ color: color(i.growth_7d), fontWeight: 600 }}>{pct(i.growth_7d)}</td>
                  <td style={{ color: color(i.growth_15d), fontWeight: 600 }}>{pct(i.growth_15d)}</td>
                  <td style={{ color: color(i.growth_30d), fontWeight: 600 }}>{pct(i.growth_30d)}</td>
                  <td>{i.monthly_volume == null ? "—" : i.monthly_volume.toLocaleString("pt-BR")}</td>
                  <td>{i.cpc_brl == null ? "—" : i.cpc_brl.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}</td>
                  <td>{i.competition || "—"}</td>
                  <td>{i.error ? <span title={i.error} style={{ color: "#b8720a" }}>sem dado</span> : i.rising ? <span style={{ color: "#1a7a54", fontWeight: 700 }}>▲ em alta</span> : "—"}</td>
                  <td><button onClick={() => remove(i.keyword)} title="Parar de vigiar" style={{ border: "none", background: "transparent", color: "#8898aa", cursor: "pointer" }}>✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
        <input value={word} onChange={(e) => setWord(e.target.value)} onKeyDown={(e) => e.key === "Enter" && word.trim() && add()} placeholder="Vigiar uma palavra (ex.: tênis running)" style={{ padding: "5px 8px", border: "1px solid #dee2e6", borderRadius: 6, minWidth: 240 }} />
        <button onClick={add} disabled={!word.trim()} style={{ border: "none", background: "#5e72e4", color: "#fff", borderRadius: 6, padding: "5px 14px", fontSize: 12, cursor: "pointer" }}>Adicionar</button>
        {msg && <span style={{ fontSize: 11, color: "#525f7f" }}>{msg}</span>}
      </div>
    </div>
  );
}
