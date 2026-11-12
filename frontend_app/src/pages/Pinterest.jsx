import React, { useCallback, useEffect, useState } from "react";
import { API_BASE, getJSON, getTokens, patchJSON, postJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", marginBottom: 16 };
const GRAY = "#8898aa", INK = "#32325d", RED = "#c31e3f";
const input = { padding: "6px 9px", border: "1px solid #dee2e6", borderRadius: 6, fontSize: 13, width: "100%", boxSizing: "border-box" };
const STATUS = {
  draft: ["#eef2ff", "#3b4fb8", "rascunho"], approved: ["#fff4e5", "#b8720a", "aprovado"], published: ["#e5faf1", "#1a7a54", "publicado"],
  failed: ["#fef1f4", "#c31e3f", "falhou"], rejected: ["#eef0f6", "#525f7f", "descartado"],
};
const num = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR"));
const when = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—");
const toLocalInput = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

function useBlob(path) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    if (!path) return undefined;
    let revoke = null;
    let alive = true;
    fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${getTokens().access}` } })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((b) => { revoke = URL.createObjectURL(b); if (alive) setUrl(revoke); })
      .catch(() => {});
    return () => { alive = false; if (revoke) URL.revokeObjectURL(revoke); };
  }, [path]);
  return url;
}

function Chip({ k }) {
  const [bg, fg, label] = STATUS[k] || ["#eef0f6", "#525f7f", k];
  return <span style={{ background: bg, color: fg, fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "2px 9px" }}>{label}</span>;
}

function Field({ label, children, hint }) {
  return (
    <label style={{ display: "block", marginBottom: 8 }}>
      <div style={{ fontSize: 11, color: GRAY, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3 }}>{label}{hint ? <span style={{ textTransform: "none", marginLeft: 6 }}>{hint}</span> : null}</div>
      {children}
    </label>
  );
}

function PinCard({ pin, canPublish, onChanged, onError }) {
  const src = useBlob(pin.image_file);
  const [f, setF] = useState({ title: pin.title, description: pin.description, alt_text: pin.alt_text || "", keywords: pin.keywords || "", board_name: pin.board_name, scheduled_for: toLocalInput(pin.scheduled_for) });
  const [busy, setBusy] = useState(false);
  const locked = pin.status === "published" || pin.status === "rejected";
  const dirty = f.title !== pin.title || f.description !== pin.description || f.alt_text !== (pin.alt_text || "") || f.keywords !== (pin.keywords || "") || f.board_name !== pin.board_name || f.scheduled_for !== toLocalInput(pin.scheduled_for);
  const payload = () => ({ title: f.title, description: f.description, alt_text: f.alt_text, keywords: f.keywords, board_name: f.board_name, scheduled_for: f.scheduled_for ? new Date(f.scheduled_for).toISOString() : null });
  const run = async (fn) => {
    setBusy(true);
    onError("");
    try { await fn(); await onChanged(); } catch (e) { onError(e.message || String(e)); await onChanged(); } finally { setBusy(false); }
  };
  const saveFirst = async () => { if (dirty) await patchJSON(`/pinterest/pins/${pin.id}`, payload()); };
  const copy = (text) => navigator.clipboard?.writeText(text).catch(() => {});
  const kit = `${f.title}\n\n${f.description}\n\nLink: ${pin.link_url}\nQuadro: ${f.board_name}\nInteresses: ${f.keywords}`;
  const btn = (bg, fg) => ({ background: bg, color: fg, border: "none", borderRadius: 6, padding: "6px 12px", fontSize: 12, fontWeight: 700, cursor: busy ? "wait" : "pointer" });
  return (
    <div style={{ ...card, display: "flex", gap: 16, flexWrap: "wrap" }}>
      <div style={{ width: 170, flex: "0 0 170px" }}>
        {src ? <img src={src} alt={pin.alt_text || pin.title} style={{ width: "100%", borderRadius: 8, background: "#f6f9fc", aspectRatio: "2/3", objectFit: "cover" }} /> : <div style={{ aspectRatio: "2/3", background: "#f6f9fc", borderRadius: 8 }} />}
        {src ? <a href={src} download={`pin-${pin.id}.jpg`} style={{ fontSize: 12, color: "#5e72e4", display: "block", marginTop: 6 }}>baixar imagem</a> : null}
      </div>
      <div style={{ flex: "1 1 340px", minWidth: 280 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
          <Chip k={pin.status} />
          <span style={{ fontSize: 12, color: GRAY }}>{pin.product_title?.slice(0, 70)}</span>
        </div>
        {pin.error ? <div style={{ background: "#fef1f4", color: RED, borderRadius: 6, padding: "6px 10px", fontSize: 12, marginBottom: 8 }}>{pin.error}</div> : null}
        <Field label="Título" hint={`${f.title.length}/100`}><input style={input} maxLength={100} disabled={locked} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="Descrição" hint={`${f.description.length}/800`}><textarea style={{ ...input, minHeight: 90 }} maxLength={800} disabled={locked} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 160px" }}><Field label="Quadro"><input style={input} disabled={locked} value={f.board_name} onChange={(e) => setF({ ...f, board_name: e.target.value })} /></Field></div>
          <div style={{ flex: "1 1 200px" }}><Field label="Interesses (marque no Pinterest)"><input style={input} disabled={locked} value={f.keywords} onChange={(e) => setF({ ...f, keywords: e.target.value })} /></Field></div>
          <div style={{ flex: "1 1 190px" }}><Field label="Agendar para"><input style={input} type="datetime-local" disabled={locked} value={f.scheduled_for} onChange={(e) => setF({ ...f, scheduled_for: e.target.value })} /></Field></div>
        </div>
        <Field label="Texto alternativo da imagem"><input style={input} maxLength={500} disabled={locked} value={f.alt_text} onChange={(e) => setF({ ...f, alt_text: e.target.value })} /></Field>
        <div style={{ fontSize: 12, color: GRAY, marginBottom: 10, wordBreak: "break-all" }}>
          Link do pin ({pin.link_mode === "page" ? "página do produto no Mural" : "link rastreado direto"}): <a href={pin.link_url} target="_blank" rel="noreferrer" style={{ color: "#5e72e4" }}>{pin.link_url}</a>
        </div>
        {pin.status === "published" ? (
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 13, color: INK, marginBottom: 6 }}>
            <a href={pin.permalink} target="_blank" rel="noreferrer" style={{ color: "#5e72e4", fontWeight: 700 }}>ver no Pinterest</a>
            <span>publicado {when(pin.published_at)}</span>
            <span>impressões <b>{num(pin.impressions)}</b></span><span>salvamentos <b>{num(pin.saves)}</b></span>
            <span>cliques no pin <b>{num(pin.pin_clicks)}</b></span><span>cliques no link <b>{num(pin.outbound_clicks)}</b></span>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {dirty && !locked ? <button style={btn("#eef0f6", INK)} disabled={busy} onClick={() => run(saveFirst)}>Salvar edição</button> : null}
            {pin.status !== "rejected" ? <button style={btn("#fff4e5", "#b8720a")} disabled={busy} onClick={() => run(async () => { await saveFirst(); await postJSON(`/pinterest/pins/${pin.id}/approve`, { scheduled_for: f.scheduled_for ? new Date(f.scheduled_for).toISOString() : null }); })}>{pin.status === "approved" ? "Reaprovar" : "Aprovar (sai sozinho)"}</button> : null}
            {canPublish && pin.status !== "rejected" ? <button style={btn("#2dce89", "#fff")} disabled={busy} onClick={() => run(async () => { await saveFirst(); await postJSON(`/pinterest/pins/${pin.id}/publish`, {}); })}>Publicar agora</button> : null}
            <button style={btn("#eef2ff", "#3b4fb8")} onClick={() => copy(kit)}>Copiar kit (texto + link)</button>
            {pin.status !== "rejected" ? <button style={btn("#fef1f4", RED)} disabled={busy} onClick={() => run(() => postJSON(`/pinterest/pins/${pin.id}/reject`, {}))}>Descartar</button> : null}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Pinterest() {
  const [status, setStatus] = useState(null);
  const [pins, setPins] = useState([]);
  const [filter, setFilter] = useState("");
  const [count, setCount] = useState(3);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([getJSON("/pinterest/status"), getJSON(`/pinterest/pins${filter ? `?status=${filter}` : ""}`)]);
      setStatus(s);
      setPins(p.pins);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }, [filter]);
  useEffect(() => { load(); }, [load]);

  const act = async (fn, ok) => {
    setBusy(true); setErr(""); setMsg("");
    try { const r = await fn(); setMsg(ok(r)); await load(); } catch (e) { setErr(e.message || String(e)); } finally { setBusy(false); }
  };
  const c = status?.counts || {};
  const btn = { background: "#5e72e4", color: "#fff", border: "none", borderRadius: 6, padding: "8px 14px", fontSize: 13, fontWeight: 700, cursor: busy ? "wait" : "pointer" };
  return (
    <div>
      <div style={card}>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
          {[["Rascunhos", c.draft], ["Aprovados", c.approved], ["Publicados", c.published], ["Com erro", c.failed], ["Saíram em 24 h", status?.published_last_24h], ["Produtos sem pin", status?.candidates]].map(([l, v]) => (
            <div key={l}><div style={{ fontSize: 10, color: GRAY, textTransform: "uppercase", letterSpacing: 0.4 }}>{l}</div><div style={{ fontSize: 20, fontWeight: 700, color: INK }}>{num(v || 0)}</div></div>
          ))}
        </div>
        {status && !status.token_set ? (
          <div style={{ background: "#fff4e5", color: "#8a5a00", borderRadius: 8, padding: "8px 12px", fontSize: 13, marginBottom: 12 }}>
            O Pinterest ainda não está conectado (Integrações → Pinterest). Enquanto isso, use o <b>kit</b>: baixe a imagem, copie o texto e o link e poste à mão em pinterest.com → Criar pin. Os rascunhos já saem prontos.
          </div>
        ) : status?.sandbox ? (
          <div style={{ background: "#fff4e5", color: "#8a5a00", borderRadius: 8, padding: "8px 12px", fontSize: 13, marginBottom: 12 }}>
            A conexão está em <b>SANDBOX</b>: o que for publicado só você vê. Para o público ver, o Pinterest precisa liberar o acesso de produção ao seu app.
          </div>
        ) : null}
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, color: INK }}>Gerar</span>
          <input type="number" min={1} max={20} value={count} onChange={(e) => setCount(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} style={{ ...input, width: 70 }} />
          <button style={btn} disabled={busy} onClick={() => act(() => postJSON("/pinterest/drafts", { count }), (r) => `${r.pins.length} rascunho(s) criado(s).`)}>rascunhos de pin</button>
          <button style={{ ...btn, background: "#eef0f6", color: INK }} disabled={busy} onClick={() => act(() => postJSON("/pinterest/sync-metrics", {}), (r) => `${r.updated} pin(s) com métricas atualizadas.`)}>Ler métricas</button>
          <span style={{ fontSize: 12, color: GRAY }}>teto {status?.max_per_day ?? 3}/dia · link do pin: {status?.link_mode === "direct" ? "direto" : "página do Mural"} (mude em Integrações)</span>
        </div>
        {msg ? <div style={{ color: "#1a7a54", fontSize: 13, marginTop: 10 }}>{msg}</div> : null}
        {err ? <div style={{ color: RED, fontSize: 13, marginTop: 10 }}>{err}</div> : null}
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        {[["", "Todos"], ["draft", "Rascunhos"], ["approved", "Aprovados"], ["published", "Publicados"], ["failed", "Com erro"], ["rejected", "Descartados"]].map(([k, l]) => (
          <button key={k} onClick={() => setFilter(k)} style={{ border: "1px solid #dee2e6", background: filter === k ? "#5e72e4" : "#fff", color: filter === k ? "#fff" : INK, borderRadius: 999, padding: "4px 12px", fontSize: 12, cursor: "pointer" }}>{l}</button>
        ))}
      </div>
      {pins.length === 0 ? <div style={{ ...card, color: GRAY, fontSize: 13 }}>Nenhum pin aqui ainda. Clique em “rascunhos de pin”: pego produtos da vitrine, com a melhor imagem, texto de SEO e o link do Mural.</div> : null}
      {pins.map((p) => <PinCard key={`${p.id}-${p.status}-${p.title}`} pin={p} canPublish onChanged={load} onError={setErr} />)}
    </div>
  );
}
