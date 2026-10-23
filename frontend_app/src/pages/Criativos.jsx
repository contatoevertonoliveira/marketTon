import React, { useCallback, useEffect, useMemo, useState } from "react";
import { getJSON, postJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", marginBottom: 16 };
const MODE = { sandbox: ["#eef0f6", "#525f7f", "teste (sandbox)"], live: ["#e5faf1", "#1a7a54", "ao vivo"] };
const STATUS = {
  requested: ["#fff4e5", "#b8720a", "pedido"], queued: ["#fff4e5", "#b8720a", "na fila"], planning: ["#eef2ff", "#3b4fb8", "planejando"],
  generating: ["#eef2ff", "#3b4fb8", "gerando"], assembling: ["#eef2ff", "#3b4fb8", "montando"], qa: ["#eef2ff", "#3b4fb8", "conferindo"],
  completed: ["#e5faf1", "#1a7a54", "pronto"], partial: ["#fff4e5", "#b8720a", "parcial"], failed: ["#fef1f4", "#c31e3f", "falhou"], canceled: ["#eef0f6", "#525f7f", "cancelado"],
};
const AD = { draft: ["#eef0f6", "#525f7f", "planejado"], paused: ["#fff4e5", "#b8720a", "pausado"], active: ["#e5faf1", "#1a7a54", "ativo"], ended: ["#eef0f6", "#525f7f", "encerrado"], failed: ["#fef1f4", "#c31e3f", "falhou"] };
const brl = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
const usd = (v) => (v == null ? "—" : `US$ ${Number(v).toFixed(2)}`);
const num = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR"));
const when = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");

function Chip({ map, k, fallback }) {
  const [bg, fg, label] = map[k] || ["#eef0f6", "#525f7f", fallback || k];
  return <span style={{ background: bg, color: fg, fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "2px 9px", whiteSpace: "nowrap" }}>{label}</span>;
}

function Metric({ label, value, hint }) {
  return (
    <div title={hint}>
      <div style={{ fontSize: 10, color: "#8898aa", textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: "#32325d" }}>{value}</div>
    </div>
  );
}

function Piece({ d }) {
  const box = { background: "#f6f9fc", borderRadius: 8, padding: 8, fontSize: 12, color: "#525f7f", maxWidth: 230 };
  if (d.kind === "video")
    return (
      <div style={box}>
        {d.download ? <video src={d.download} controls preload="none" style={{ width: "100%", borderRadius: 6, background: "#000" }} /> : null}
        <div style={{ marginTop: 4 }}>Vídeo {d.aspect_ratio} {d.duration_s ? `· ${d.duration_s}s` : ""} {d.variant ? `· gancho ${d.variant}` : ""}</div>
      </div>
    );
  if (d.kind === "image" || d.kind === "thumbnail")
    return (
      <div style={box}>
        {d.download ? <img src={d.download} alt="" style={{ width: "100%", borderRadius: 6 }} /> : null}
        <div style={{ marginTop: 4 }}>{d.kind === "image" ? "Imagem" : "Miniatura"} {d.aspect_ratio}</div>
      </div>
    );
  if (d.kind === "copy") {
    const c = d.content || {};
    return (
      <div style={{ ...box, maxWidth: 320 }}>
        <div style={{ fontWeight: 700, color: "#32325d", marginBottom: 4 }}>Texto {d.channel ? `· ${d.channel}` : ""}</div>
        {c.headline && <div><strong>{c.headline}</strong></div>}
        {c.caption && <div style={{ whiteSpace: "pre-wrap" }}>{c.caption}</div>}
        {c.hashtags && <div style={{ color: "#5e72e4" }}>{[].concat(c.hashtags).join(" ")}</div>}
      </div>
    );
  }
  return <div style={box}>{d.kind}{d.download ? <> · <a href={d.download} target="_blank" rel="noreferrer">abrir</a></> : null}</div>;
}

function AdActions({ ad, onDone, onMsg }) {
  const [busy, setBusy] = useState(false);
  async function run(path, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true);
    try { await postJSON(path); onMsg({ ok: true, text: "Feito." }); onDone(); } catch (e) { onMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  }
  const btn = (bg, color) => ({ border: "none", background: bg, color, borderRadius: 6, padding: "3px 10px", fontSize: 11, fontWeight: 700, cursor: "pointer" });
  if (!ad.on_meta) return <span style={{ color: "#8898aa" }}>—</span>;
  if (ad.status === "active") return <button disabled={busy} style={btn("#fff4e5", "#b8720a")} onClick={() => run(`/ads/${ad.id}/pause`)}>Pausar</button>;
  if (ad.status === "paused" || ad.status === "draft")
    return (
      <button disabled={busy} style={btn("#2dce89", "#fff")}
        onClick={() => run(`/ads/${ad.id}/activate`, `LIGAR este anúncio na Meta?\n\nEle começa a gastar até ${brl(ad.daily_budget_brl)} por dia, por ${ad.duration_days || 1} dia(s) (no máximo ${brl((ad.daily_budget_brl || 0) * (ad.duration_days || 1))} no total).`)}>
        Ligar
      </button>
    );
  return <span style={{ color: "#8898aa" }}>—</span>;
}

function Item({ it, onDone, onMsg }) {
  const p = it.product;
  const r = it.product_results;
  return (
    <div style={card}>
      <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ width: 64, height: 64, borderRadius: 8, overflow: "hidden", background: "#f6f9fc", flex: "none" }}>
          {p?.image && <img src={p.image} alt="" referrerPolicy="no-referrer" style={{ width: "100%", height: "100%", objectFit: "cover" }} />}
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14 }}>{p ? p.title : "Produto removido"}</div>
          <div style={{ fontSize: 11, color: "#8898aa", margin: "3px 0 6px" }}>
            {p ? `${p.marketplace} · ${brl(p.price)}` : ""} · criado {when(it.created_at)}{it.created_by ? ` por ${it.created_by}` : ""} · {it.external_ref}
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            <Chip map={MODE} k={it.mode} />
            <Chip map={STATUS} k={it.status} />
            <span style={{ fontSize: 11, color: "#8898aa" }}>qualidade {it.quality}{it.angle ? ` · ângulo ${it.angle}` : ""}</span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 22, flexWrap: "wrap" }}>
          <Metric label="Custo do criativo" value={usd(it.cost_usd)} hint={`Teto da campanha: ${usd(it.budget_usd)}`} />
          <Metric label="Teto" value={usd(it.budget_usd)} />
        </div>
      </div>

      {it.error && <div style={{ marginTop: 10, fontSize: 12, padding: "7px 10px", borderRadius: 8, color: "#c31e3f", background: "#fef1f4" }}>{it.error}</div>}

      {it.deliverables.length > 0 && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>{it.deliverables.map((d) => <Piece key={d.id} d={d} />)}</div>
      )}

      <div style={{ marginTop: 14, borderTop: "1px solid #f0f2f7", paddingTop: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#32325d", marginBottom: 6 }}>Anúncios feitos com este criativo</div>
        {it.ads.length === 0 ? (
          <div style={{ fontSize: 12, color: "#8898aa" }}>Nenhum anúncio ainda. Quando o agente (ou você) criar o anúncio na Meta, ele aparece aqui com gasto, impressões, cliques, CTR e CPC.</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse", minWidth: 640 }}>
              <thead>
                <tr style={{ color: "#8898aa", textAlign: "left" }}>
                  {["Plataforma", "Gancho", "Estado", "Verba/dia", "Gasto", "Impressões", "Cliques", "CTR", "CPC", "Início", "Métricas de", ""].map((h) => <th key={h} style={{ padding: "4px 8px 4px 0", fontWeight: 600 }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {it.ads.map((a) => (
                  <tr key={a.id} style={{ borderTop: "1px solid #f6f9fc" }}>
                    <td style={{ padding: "5px 8px 5px 0" }}>{a.platform}</td><td>{a.variant || "—"}</td><td><Chip map={AD} k={a.status} />{a.meta_status && a.meta_status !== "PAUSED" && a.meta_status !== "ACTIVE" ? <div style={{ fontSize: 10, color: "#b8720a" }}>Meta: {a.meta_status}</div> : null}</td>
                    <td>{brl(a.daily_budget_brl)}</td><td>{brl(a.spent_brl)}</td><td>{num(a.impressions)}</td><td>{num(a.clicks)}</td>
                    <td>{a.ctr_pct == null ? "—" : `${String(a.ctr_pct).replace(".", ",")}%`}</td><td>{brl(a.cpc_brl)}</td><td>{when(a.started_at)}</td><td>{when(a.last_metrics_at)}</td><td><AdActions ad={a} onDone={onDone} onMsg={onMsg} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {r && (
        <div style={{ marginTop: 12, display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-end", background: "#f6f9fc", borderRadius: 8, padding: "10px 12px" }}>
          <Metric label="Cliques na loja desde o criativo" value={num(r.store_clicks)} hint="Cliques de pessoas nos links curtos do produto (não de robôs)" />
          <Metric label="Vendas desde o criativo" value={num(r.sales)} />
          <Metric label="Comissão (confirmada ou estimada)" value={brl(r.commission_brl)} />
          <div style={{ fontSize: 11, color: "#8898aa", maxWidth: 360 }}>Resultado do produto no período, não atribuído a um anúncio: a venda de afiliado sai do marketplace dias depois e não diz de qual anúncio veio.</div>
        </div>
      )}
    </div>
  );
}

export default function Criativos() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("todos");
  const load = useCallback(() => getJSON("/creatives/history?limit=100").then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); const id = setInterval(load, 30000); return () => clearInterval(id); }, [load]);
  const [budget, setBudget] = useState(null);
  const [msg, setMsg] = useState(null);
  const loadAll = useCallback(() => { load(); getJSON("/ads/budget").then(setBudget).catch(() => {}); }, [load]);
  useEffect(() => { getJSON("/ads/budget").then(setBudget).catch(() => {}); }, [data]);
  async function stopAll() {
    if (!window.confirm("PAUSAR todos os anúncios ativos agora?")) return;
    try { const r = await postJSON("/ads/pause-all"); setMsg({ ok: true, text: `${r.paused} anúncio(s) pausado(s).` }); loadAll(); } catch (e) { setMsg({ ok: false, text: e.message }); }
  }
  async function syncNow() {
    try { const r = await postJSON("/ads/sync"); setMsg({ ok: true, text: `Métricas atualizadas em ${r.updated} anúncio(s).` }); loadAll(); } catch (e) { setMsg({ ok: false, text: e.message }); }
  }
  const items = useMemo(() => (data?.items || []).filter((i) => mode === "todos" || i.mode === mode), [data, mode]);

  if (error) return <p style={{ color: "#f5365c" }}>Não foi possível carregar os criativos ({error}).</p>;
  if (!data) return <p style={{ color: "#8898aa" }}>Carregando…</p>;
  const t = data.totals;
  return (
    <div>
      <div style={{ ...card, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14 }}>
        <Metric label="Criativos" value={num(t.creatives)} />
        <Metric label="Gasto em criativos" value={usd(t.cost_usd)} hint="Custo das gerações no AI Studio (só modo ao vivo gasta)" />
        <Metric label="Anúncios" value={`${num(t.ads)} (${num(t.active_ads)} ativos)`} />
        <Metric label="Gasto em anúncios" value={brl(t.spent_brl)} />
      </div>
      {budget && budget.configured && (
        <div style={{ ...card, display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Metric label="Verba da semana" value={`${brl(budget.week_committed_brl)} de ${brl(budget.weekly_brl)}`} hint="Compromisso: verba por dia × dias dos anúncios criados nesta semana" />
          <Metric label="Por dia agora" value={`${brl(budget.daily_committed_brl)} de ${brl(budget.daily_cap_brl)}`} hint="Anúncios abertos (planejados, pausados ou ativos)" />
          <Metric label="Produtos na semana" value={`${budget.week_products} de ${budget.max_products}`} />
          <Metric label="Gasto lido da Meta (semana)" value={brl(budget.week_spent_brl)} />
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button onClick={syncNow} style={{ border: "1px solid #dee2e6", background: "#fff", borderRadius: 8, padding: "6px 14px", fontSize: 12, cursor: "pointer" }}>Atualizar métricas</button>
            <button onClick={stopAll} style={{ border: "none", background: "#f5365c", color: "#fff", borderRadius: 8, padding: "6px 14px", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>Pausar tudo</button>
          </div>
        </div>
      )}
      {budget && !budget.configured && <div style={{ ...card, fontSize: 12, color: "#b8720a" }}>Defina o Orçamento de anúncios em Integrações (valor por semana e teto por dia) para o agente poder planejar anúncios.</div>}
      {msg && <div style={{ marginBottom: 12, fontSize: 12, padding: "8px 10px", borderRadius: 8, color: msg.ok ? "#1a7a54" : "#c31e3f", background: msg.ok ? "#e5faf1" : "#fef1f4" }}>{msg.text}</div>}
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {[["todos", "Todos"], ["live", "Ao vivo"], ["sandbox", "Testes"]].map(([k, label]) => (
          <button key={k} onClick={() => setMode(k)} style={{ border: "none", borderRadius: 999, padding: "4px 14px", fontSize: 12, cursor: "pointer", background: mode === k ? "#5e72e4" : "#eef0f6", color: mode === k ? "#fff" : "#525f7f" }}>{label}</button>
        ))}
      </div>
      {items.length === 0 ? (
        <div style={card}><span style={{ fontSize: 13, color: "#8898aa" }}>Nenhum criativo ainda. Configure o cartão do AI Studio em Integrações; o agente pede os criativos dos produtos escolhidos e eles aparecem aqui, em ordem do mais recente.</span></div>
      ) : (
        items.map((it) => <Item key={it.id} it={it} onDone={loadAll} onMsg={setMsg} />)
      )}
    </div>
  );
}
