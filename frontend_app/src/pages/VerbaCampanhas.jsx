import React, { useCallback, useEffect, useMemo, useState } from "react";
import { getJSON, putJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", marginBottom: 16 };
const GRAY = "#8898aa", INK = "#32325d", BLUE = "#5e72e4", GREEN = "#2dce89", RED = "#c31e3f";
const COLORS = { meta: "#1877f2", google: "#f4b400", marketplace: "#fb6340" };
const brl = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
const num = (v) => {
  const n = Number(String(v ?? "").replace(/\./g, "").replace(",", "."));
  return Number.isFinite(n) ? n : 0;
};
const input = { padding: "6px 9px", border: "1px solid #dee2e6", borderRadius: 6, fontSize: 13, width: "100%", boxSizing: "border-box" };

const BUCKETS = [
  { key: "meta", label: "Meta Ads", hint: "Facebook e Instagram. O agente cria o anúncio pausado; só você liga." },
  { key: "google", label: "Google Ads", hint: "Anúncio de pesquisa. O agente cria pausado; só você liga." },
  { key: "marketplace", label: "Dentro dos marketplaces", hint: "Shopee Ads, Mercado Livre Ads etc. Você executa no painel do marketplace; aqui é só o planejamento." },
];

// Mexer em uma parte redistribui o resto entre as outras duas, sempre fechando 100%.
function rebalance(split, key, value) {
  const others = Object.keys(split).filter((k) => k !== key);
  const rest = 100 - value;
  const base = others.reduce((s, k) => s + split[k], 0);
  const next = { ...split, [key]: value };
  let used = 0;
  others.forEach((k, i) => {
    const share = i === others.length - 1 ? rest - used : Math.round(base > 0 ? (split[k] / base) * rest : rest / others.length);
    next[k] = Math.max(0, share);
    used += next[k];
  });
  return next;
}

function Bar({ split, total }) {
  return (
    <div>
      <div style={{ display: "flex", height: 16, borderRadius: 8, overflow: "hidden", background: "#eef1f6" }}>
        {BUCKETS.map((b) => <div key={b.key} title={`${b.label}: ${split[b.key]}%`} style={{ width: `${split[b.key]}%`, background: COLORS[b.key], transition: "width .2s" }} />)}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: GRAY, marginTop: 4 }}>
        <span>0</span><span>{brl(total)} por semana</span>
      </div>
    </div>
  );
}

function Usage({ m }) {
  if (m.week_committed_brl == null) return null;
  return <span style={{ fontSize: 11, color: GRAY }}>Esta semana: comprometido {brl(m.week_committed_brl)} · gasto lido {brl(m.week_spent_brl)}</span>;
}

export default function VerbaCampanhas() {
  const [plan, setPlan] = useState(null);
  const [canEdit, setCanEdit] = useState(false);
  const [total, setTotal] = useState("");
  const [split, setSplit] = useState({ meta: 100, google: 0, marketplace: 0 });
  const [rows, setRows] = useState([]);
  const [msg, setMsg] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    getJSON("/ads/plan").then((p) => {
      setPlan(p);
      setTotal(p.total_weekly_brl ? String(p.total_weekly_brl).replace(".", ",") : "");
      const s = { meta: Math.round(p.meta_pct), google: Math.round(p.google_pct), marketplace: Math.round(p.marketplace_pct) };
      const sum = s.meta + s.google + s.marketplace;
      setSplit(sum === 100 || sum === 0 ? (sum === 0 ? { meta: 100, google: 0, marketplace: 0 } : s) : { ...s, meta: s.meta + (100 - sum) });
      setRows(p.marketplaces.map((m) => ({ ...m, weekly: m.weekly_brl ?? "", daily: m.daily_cap_brl ?? "", own: m.own_ads_weekly_brl ?? "" })));
    }).catch((e) => setMsg({ ok: false, text: e.message }));
    getJSON("/auth/me").then((me) => setCanEdit(!!me.permissions?.includes("connectors.manage"))).catch(() => {});
  }, []);
  useEffect(load, [load]);

  const totalN = num(total);
  const money = (key) => (totalN * split[key]) / 100;
  const inList = rows.filter((r) => r.enabled);
  const outList = rows.filter((r) => !r.enabled);
  const ownSum = inList.reduce((s, r) => s + num(r.own), 0);
  const problems = useMemo(() => {
    const out = [];
    if (!(totalN > 0)) out.push("Informe a verba total por semana.");
    if (inList.length === 0) out.push("Nenhum marketplace na lista: o agente não fará nenhuma campanha paga.");
    if (ownSum > money("marketplace") + 0.005) out.push(`A propaganda dentro dos marketplaces (${brl(ownSum)}) passa da parte reservada (${brl(money("marketplace"))}).`);
    inList.forEach((r) => { if (num(r.weekly) > money("meta") + money("google") + 0.005) out.push(`${r.name}: o teto por semana passa da verba de Meta + Google.`); });
    return out;
  }, [totalN, split, rows]); // eslint-disable-line react-hooks/exhaustive-deps

  const patch = (slug, changes) => setRows((rs) => rs.map((r) => (r.slug === slug ? { ...r, ...changes } : r)));

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      const p = await putJSON("/ads/plan", {
        total_weekly_brl: total, meta_pct: split.meta, google_pct: split.google, marketplace_pct: split.marketplace,
        marketplaces: rows.map((r) => ({ slug: r.slug, enabled: r.enabled, weekly_brl: r.weekly === "" ? null : r.weekly, daily_cap_brl: r.daily === "" ? null : r.daily, own_ads_weekly_brl: r.own === "" ? null : r.own })),
      });
      setPlan(p);
      setMsg({ ok: true, text: "Plano salvo. O agente já passa a seguir estas regras." });
      load();
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setSaving(false);
    }
  }

  if (!plan) return <div style={card}>{msg ? <span style={{ color: RED }}>{msg.text}</span> : "Carregando…"}</div>;

  return (
    <div>
      <div style={{ ...card, background: "#f6f9fc", boxShadow: "none", border: "1px solid #e3e8ef" }}>
        <div style={{ fontWeight: 700, color: INK, marginBottom: 6 }}>Como funciona</div>
        <ol style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "#525f7f", lineHeight: 1.6 }}>
          <li>Defina quanto pode ser gasto por semana e como dividir entre Meta, Google e propaganda dentro dos marketplaces.</li>
          <li>Coloque na lista os marketplaces onde o agente PODE fazer campanha. Os que ficarem fora da lista têm só divulgação orgânica (Instagram, Facebook e vitrine).</li>
          <li>O agente nunca passa destes limites e todo anúncio novo nasce pausado: só você liga.</li>
        </ol>
      </div>

      <div style={card}>
        <div style={{ fontWeight: 700, color: INK, marginBottom: 10 }}>1. Quanto gastar por semana</div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
          <label style={{ fontSize: 13, color: "#525f7f" }}>Verba total por semana</label>
          <input disabled={!canEdit} value={total} onChange={(e) => setTotal(e.target.value)} placeholder="ex.: 150" style={{ ...input, width: 140 }} />
          <span style={{ fontSize: 12, color: GRAY }}>em reais (R$)</span>
        </div>
        <Bar split={split} total={totalN} />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, marginTop: 14 }}>
          {BUCKETS.map((b) => (
            <div key={b.key} style={{ borderLeft: `4px solid ${COLORS[b.key]}`, paddingLeft: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <strong style={{ color: INK, fontSize: 14 }}>{b.label}</strong>
                <span style={{ fontSize: 18, fontWeight: 700, color: INK }}>{brl(money(b.key))}</span>
              </div>
              <input type="range" min={0} max={100} step={5} disabled={!canEdit} value={split[b.key]}
                onChange={(e) => setSplit(rebalance(split, b.key, Number(e.target.value)))} style={{ width: "100%", accentColor: COLORS[b.key] }} />
              <div style={{ fontSize: 11, color: GRAY }}>{split[b.key]}% da verba · {b.hint}</div>
              {plan.platforms?.[b.key]?.configured && (
                <div style={{ fontSize: 11, color: "#525f7f", marginTop: 3 }}>
                  Comprometido na semana: {brl(plan.platforms[b.key].week_committed_brl)} · gasto lido: {brl(plan.platforms[b.key].week_spent_brl)}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div style={card}>
        <div style={{ fontWeight: 700, color: INK, marginBottom: 2 }}>2. Marketplaces com campanha</div>
        <div style={{ fontSize: 12, color: GRAY, marginBottom: 12 }}>Só produtos destes marketplaces recebem anúncio pago do agente. Cada um pode ter um teto próprio (opcional), somando Meta e Google.</div>
        {inList.length === 0 && <div style={{ fontSize: 13, color: GRAY, padding: "8px 0" }}>Nenhum marketplace na lista ainda. Adicione abaixo.</div>}
        {inList.map((r) => (
          <div key={r.slug} style={{ border: "1px solid #e3e8ef", borderLeft: `4px solid ${GREEN}`, borderRadius: 8, padding: 12, marginBottom: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 6 }}>
              <strong style={{ color: INK }}>{r.name} <span style={{ fontSize: 11, color: GREEN, fontWeight: 600 }}>com campanha</span></strong>
              {canEdit && <button onClick={() => patch(r.slug, { enabled: false })} style={{ border: "none", background: "transparent", color: RED, fontSize: 12, cursor: "pointer" }}>tirar da lista (só orgânico)</button>}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, margin: "10px 0 6px" }}>
              <label style={{ fontSize: 11, color: GRAY }}>Teto por semana (opcional)
                <input disabled={!canEdit} value={r.weekly} onChange={(e) => patch(r.slug, { weekly: e.target.value })} placeholder="sem teto próprio" style={input} />
              </label>
              <label style={{ fontSize: 11, color: GRAY }}>Teto por dia (opcional)
                <input disabled={!canEdit} value={r.daily} onChange={(e) => patch(r.slug, { daily: e.target.value })} placeholder={r.weekly ? "30% da semana" : "—"} style={input} />
              </label>
              <label style={{ fontSize: 11, color: GRAY }}>Propaganda no próprio marketplace (R$/sem)
                <input disabled={!canEdit} value={r.own} onChange={(e) => patch(r.slug, { own: e.target.value })} placeholder="0" style={input} />
              </label>
            </div>
            <Usage m={r} />
          </div>
        ))}
        {outList.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, color: GRAY, marginBottom: 6 }}>Fora da lista (só orgânico):</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {outList.map((r) => (
                <button key={r.slug} disabled={!canEdit} onClick={() => patch(r.slug, { enabled: true })}
                  style={{ border: "1px dashed #adb5bd", background: "#f8f9fe", borderRadius: 999, padding: "6px 14px", fontSize: 13, color: "#525f7f", cursor: canEdit ? "pointer" : "default" }}>
                  + {r.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div style={{ ...card, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <button onClick={save} disabled={!canEdit || saving || problems.some((p) => !p.startsWith("Nenhum marketplace"))}
          style={{ border: "none", background: BLUE, color: "#fff", borderRadius: 8, padding: "10px 22px", fontSize: 14, fontWeight: 600, cursor: "pointer", opacity: canEdit ? 1 : 0.5 }}>
          {saving ? "Salvando…" : "Salvar plano"}
        </button>
        {!canEdit && <span style={{ fontSize: 12, color: GRAY }}>Só quem gerencia integrações pode alterar o plano.</span>}
        <div style={{ flex: 1, minWidth: 220 }}>
          {problems.map((p) => <div key={p} style={{ fontSize: 12, color: p.startsWith("Nenhum") ? "#fb6340" : RED }}>{p}</div>)}
          {msg && <div style={{ fontSize: 13, color: msg.ok ? GREEN : RED }}>{msg.text}</div>}
        </div>
      </div>
    </div>
  );
}
