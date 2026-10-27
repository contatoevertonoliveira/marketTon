import React, { useCallback, useEffect, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getJSON, postJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", marginBottom: 16 };
const brl = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
const day = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : "");
const when = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");
const GREEN = "#2dce89", AMBER = "#fb6340", BLUE = "#5e72e4", GRAY = "#8898aa";

function Kpi({ label, value, hint, color }) {
  return (
    <div title={hint} style={{ minWidth: 150 }}>
      <div style={{ fontSize: 10, color: GRAY, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: color || "#32325d" }}>{value}</div>
      {hint && <div style={{ fontSize: 11, color: GRAY }}>{hint}</div>}
    </div>
  );
}

function Wallets({ data, onSaved, canEdit }) {
  const [edit, setEdit] = useState(null); // { platform, value, note }
  const [msg, setMsg] = useState("");
  async function save() {
    setMsg("");
    try {
      const value = Number(String(edit.value).replace(/\./g, "").replace(",", "."));
      if (!Number.isFinite(value)) throw new Error("Informe um valor, como 123,45");
      await postJSON("/finance/wallets", { platform: edit.platform, balance_brl: value, note: edit.note || null });
      setEdit(null);
      onSaved();
    } catch (e) { setMsg(e.message); }
  }
  return (
    <div style={card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
        <div style={{ fontWeight: 700, color: "#32325d" }}>Carteiras</div>
        <div style={{ fontSize: 12, color: GRAY }}>Saldo total: <strong style={{ color: "#32325d", fontSize: 16 }}>{brl(data.total_brl)}</strong> · {data.known} de {data.of} carteiras com saldo informado</div>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 8 }}>
        <thead><tr style={{ textAlign: "left", color: GRAY, fontSize: 11, textTransform: "uppercase" }}><th style={{ padding: "6px 0" }}>Plataforma</th><th>Saldo</th><th>Informado em</th><th>Nota</th><th /></tr></thead>
        <tbody>
          {data.items.map((w) => (
            <tr key={w.platform} style={{ borderTop: "1px solid #f0f2f5" }}>
              <td style={{ padding: "8px 0", fontWeight: 600, color: "#32325d" }}>{w.label}</td>
              <td style={{ color: w.balance_brl == null ? GRAY : "#32325d" }}>{w.balance_brl == null ? "sem saldo informado" : brl(w.balance_brl)}</td>
              <td style={{ color: "#525f7f" }}>{when(w.as_of)}{w.source === "api" ? " (automático)" : ""}</td>
              <td style={{ color: "#525f7f" }}>{w.note || ""}</td>
              <td style={{ textAlign: "right" }}>
                {canEdit && <button onClick={() => setEdit({ platform: w.platform, value: w.balance_brl ?? "", note: "" })} style={{ border: "none", background: "transparent", color: BLUE, fontSize: 12, cursor: "pointer" }}>{w.balance_brl == null ? "informar" : "atualizar"}</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {edit && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 10, padding: 10, background: "#f6f9fc", borderRadius: 8 }}>
          <strong style={{ fontSize: 12 }}>{data.items.find((w) => w.platform === edit.platform)?.label}</strong>
          <input autoFocus value={edit.value} onChange={(e) => setEdit({ ...edit, value: e.target.value })} placeholder="Saldo em R$ (ex.: 123,45)" style={{ padding: "5px 8px", border: "1px solid #dee2e6", borderRadius: 6, width: 190 }} />
          <input value={edit.note} onChange={(e) => setEdit({ ...edit, note: e.target.value })} placeholder="Nota (opcional)" style={{ padding: "5px 8px", border: "1px solid #dee2e6", borderRadius: 6, flex: 1, minWidth: 140 }} />
          <button onClick={save} style={{ border: "none", background: GREEN, color: "#fff", borderRadius: 6, padding: "5px 14px", fontSize: 12, cursor: "pointer" }}>Salvar saldo</button>
          <button onClick={() => setEdit(null)} style={{ border: "none", background: "transparent", color: GRAY, fontSize: 12, cursor: "pointer" }}>cancelar</button>
          {msg && <span style={{ fontSize: 11, color: "#c31e3f" }}>{msg}</span>}
        </div>
      )}
      <div style={{ fontSize: 11, color: GRAY, marginTop: 8 }}>O saldo vem do que você informa (ou de integração, quando a plataforma oferece). Carteira sem saldo informado fica fora do total.</div>
    </div>
  );
}

export default function Financeiro() {
  const [days, setDays] = useState(30);
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const [canEdit, setCanEdit] = useState(false);
  const load = useCallback(() => { getJSON(`/finance/overview?days=${days}`).then((r) => { setD(r); setError(""); }).catch((e) => setError(e.message)); }, [days]);
  useEffect(() => { load(); const id = setInterval(load, 120000); return () => clearInterval(id); }, [load]);
  useEffect(() => { getJSON("/auth/me").then((me) => setCanEdit(!!me.permissions?.includes("connectors.manage"))).catch(() => {}); }, []);

  if (error) return <div style={{ ...card, color: "#c31e3f", fontSize: 13 }}>{error}</div>;
  if (!d) return <div style={{ ...card, color: GRAY }}>Carregando…</div>;
  const k = d.kpis;
  const series = d.series.map((p) => ({ ...p, label: day(p.date) }));
  const walletSeries = d.wallet_series.map((p) => ({ ...p, label: day(p.date) }));
  const hasWalletSeries = walletSeries.some((p) => p.total_brl != null);
  const change = k.commission_change_pct;
  const money = (v) => brl(v);

  return (
    <div>
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {[7, 30, 90].map((n) => (
          <button key={n} onClick={() => setDays(n)} style={{ border: "1px solid #dee2e6", borderRadius: 999, padding: "4px 14px", fontSize: 12, cursor: "pointer", background: days === n ? BLUE : "#fff", color: days === n ? "#fff" : "#525f7f" }}>{n} dias</button>
        ))}
      </div>

      <div style={{ ...card, display: "flex", gap: 26, flexWrap: "wrap" }}>
        <Kpi label="Saldo total (carteiras)" value={brl(d.wallets.total_brl)} hint={`${d.wallets.known} de ${d.wallets.of} carteiras informadas`} />
        <Kpi label="Comissão no período" value={brl(k.commission_brl)} color={GREEN}
          hint={change == null ? "sem período anterior para comparar" : `${change >= 0 ? "▲" : "▼"} ${Math.abs(change)}% sobre os ${days} dias anteriores`} />
        <Kpi label="Confirmada" value={brl(k.confirmed_brl)} />
        <Kpi label="Pendente (estimada)" value={brl(k.pending_brl)} color={AMBER} />
        <Kpi label="Vendas" value={k.sales} hint={`${brl(k.gross_brl)} em valor vendido`} />
        <Kpi label="Gasto com anúncios" value={brl(k.ads_spent_brl)} hint="lido da Meta" />
        <Kpi label="Resultado" value={brl(k.result_brl)} color={k.result_brl >= 0 ? GREEN : "#c31e3f"} hint="comissão − anúncios" />
      </div>

      <div style={card}>
        <div style={{ fontWeight: 700, color: "#32325d", marginBottom: 6 }}>Comissão por dia</div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={series}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f6" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `R$ ${v}`} width={64} />
            <Tooltip formatter={(v) => money(v)} />
            <Legend />
            <Bar dataKey="confirmed_brl" name="Confirmada" stackId="c" fill={GREEN} />
            <Bar dataKey="pending_brl" name="Pendente" stackId="c" fill={AMBER} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
        <div style={card}>
          <div style={{ fontWeight: 700, color: "#32325d", marginBottom: 6 }}>Evolução da comissão (acumulada)</div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={series}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef0f6" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `R$ ${v}`} width={64} />
              <Tooltip formatter={(v) => money(v)} />
              <Area type="monotone" dataKey="cumulative_brl" name="Acumulada" stroke={BLUE} fill="#dfe4fb" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div style={card}>
          <div style={{ fontWeight: 700, color: "#32325d", marginBottom: 6 }}>Vendas por dia</div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={series}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef0f6" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} width={36} />
              <Tooltip />
              <Bar dataKey="sales" name="Vendas" fill={BLUE} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={card}>
        <div style={{ fontWeight: 700, color: "#32325d", marginBottom: 6 }}>Por plataforma</div>
        {d.by_platform.length === 0 ? <div style={{ fontSize: 12, color: GRAY }}>Nenhuma venda no período.</div> : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead><tr style={{ textAlign: "left", color: GRAY, fontSize: 11, textTransform: "uppercase" }}><th style={{ padding: "6px 0" }}>Plataforma</th><th>Vendas</th><th>Valor vendido</th><th>Confirmada</th><th>Pendente</th></tr></thead>
            <tbody>{d.by_platform.map((p) => (
              <tr key={p.platform} style={{ borderTop: "1px solid #f0f2f5" }}>
                <td style={{ padding: "8px 0", fontWeight: 600, color: "#32325d" }}>{p.label}</td><td>{p.sales}</td><td>{brl(p.gross_brl)}</td><td style={{ color: GREEN }}>{brl(p.confirmed_brl)}</td><td style={{ color: AMBER }}>{brl(p.pending_brl)}</td>
              </tr>))}</tbody>
          </table>
        )}
      </div>

      <Wallets data={d.wallets} onSaved={load} canEdit={canEdit} />

      {hasWalletSeries && (
        <div style={card}>
          <div style={{ fontWeight: 700, color: "#32325d", marginBottom: 6 }}>Evolução do saldo total das carteiras</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={walletSeries}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef0f6" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `R$ ${v}`} width={64} />
              <Tooltip formatter={(v) => money(v)} />
              <Line type="stepAfter" dataKey="total_brl" name="Saldo total" stroke={GREEN} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div style={{ fontSize: 11, color: GRAY }}>{d.notes.join(" ")}</div>
    </div>
  );
}
