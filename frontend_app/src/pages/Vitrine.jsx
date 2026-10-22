import React, { useCallback, useEffect, useMemo, useState } from "react";
import { getJSON, postJSON, putJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", marginBottom: 16 };
const input = { padding: "6px 10px", fontSize: 13, border: "1px solid #dee2e6", borderRadius: 8, background: "#fff", width: "100%", boxSizing: "border-box" };
const SOCIALS = [
  ["instagram", "Instagram"], ["facebook", "Facebook"], ["youtube", "YouTube"], ["whatsapp", "Grupo do WhatsApp"], ["telegram", "Telegram"], ["tiktok", "TikTok"],
];
const brl = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
const when = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "nunca");

function Pill({ ok, children }) {
  const [bg, fg] = ok ? ["#e5faf1", "#1a7a54"] : ["#fff4e5", "#b8720a"];
  return <span style={{ background: bg, color: fg, fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "2px 9px", whiteSpace: "nowrap" }}>{children}</span>;
}

function ItemRow({ row, categories, onSave }) {
  const [blurb, setBlurb] = useState(row.blurb || "");
  const [title, setTitle] = useState(row.display_title || "");
  useEffect(() => { setBlurb(row.blurb || ""); setTitle(row.display_title || ""); }, [row.blurb, row.display_title]);
  const save = (patch) => onSave(row.product_id, patch);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "56px 1.6fr 1.2fr 130px 90px 90px", gap: 12, alignItems: "start", padding: "10px 0", borderTop: "1px solid #f0f2f7", opacity: row.hidden ? 0.6 : 1 }}>
      <div style={{ width: 56, height: 56, borderRadius: 8, overflow: "hidden", background: "#f6f9fc" }}>
        {row.image && <img src={row.image} alt="" loading="lazy" referrerPolicy="no-referrer" style={{ width: "100%", height: "100%", objectFit: "cover" }} />}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#32325d", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={row.title}>{row.title}</div>
        <div style={{ fontSize: 11, color: "#8898aa", margin: "3px 0 6px", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <span>{row.marketplace}</span><span>{brl(row.price)}</span>
          {row.commission_pct != null && <span>comissão {Number(row.commission_pct).toFixed(1).replace(".0", "")}%</span>}
          {row.portfolio_state ? <span>portfólio</span> : <span>só na vitrine</span>}
          {row.eligible ? <Pill ok>vai para a loja</Pill> : <Pill>{row.reason}</Pill>}
        </div>
        <input style={input} value={title} maxLength={160} placeholder="Nome curto na loja (opcional)" onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title !== (row.display_title || "") && save({ display_title: title })} />
      </div>
      <input style={{ ...input, alignSelf: "end" }} value={blurb} maxLength={280} placeholder="Uma frase honesta sobre o achado" onChange={(e) => setBlurb(e.target.value)}
        onBlur={() => blurb !== (row.blurb || "") && save({ blurb })} />
      <select style={{ ...input, alignSelf: "end" }} value={row.category} onChange={(e) => save({ category: e.target.value })} title={row.category_is_guess ? "Categoria sugerida automaticamente" : "Categoria escolhida"}>
        {categories.map((c) => <option key={c} value={c}>{c}{row.category_is_guess && c === row.category ? " (sugerida)" : ""}</option>)}
      </select>
      <label style={{ fontSize: 12, color: "#525f7f", display: "flex", gap: 6, alignItems: "center", alignSelf: "end" }}>
        <input type="checkbox" checked={row.highlight} onChange={(e) => save({ highlight: e.target.checked })} /> Destaque
      </label>
      <label style={{ fontSize: 12, color: "#525f7f", display: "flex", gap: 6, alignItems: "center", alignSelf: "end" }}>
        <input type="checkbox" checked={row.hidden} onChange={(e) => save({ hidden: e.target.checked })} /> Ocultar
      </label>
    </div>
  );
}

function AddFromCatalog({ onAdd }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);
  async function search(e) {
    e.preventDefault();
    if (q.trim().length < 3) return;
    setBusy(true);
    try { setResults(await getJSON(`/catalog/products?search=${encodeURIComponent(q.trim())}&limit=12&order_by=sold_quantity`)); } catch { setResults([]); } finally { setBusy(false); }
  }
  return (
    <div>
      <form onSubmit={search} style={{ display: "flex", gap: 8 }}>
        <input style={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar no catálogo pelo nome (mín. 3 letras)" />
        <button disabled={busy} style={{ border: "none", background: "#5e72e4", color: "#fff", borderRadius: 8, padding: "6px 16px", fontSize: 13, cursor: "pointer" }}>Buscar</button>
      </form>
      {results.map((p) => (
        <div key={p.id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "6px 0", borderTop: "1px solid #f0f2f7", fontSize: 13 }}>
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.title}</span>
          <span style={{ color: "#8898aa" }}>{p.marketplace} · {brl(p.price)}</span>
          <button onClick={() => onAdd(p.id)} style={{ border: "none", background: "#2dce89", color: "#fff", borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer" }}>Adicionar à vitrine</button>
        </div>
      ))}
    </div>
  );
}

const MODELO = "plataforma;nome;link;comissao_pct;comissao_reais;preco;foto;categoria\nhotmart;Nome do curso;https://pay.hotmart.com/SEU-LINK;40;;197,00;https://exemplo.com/capa.jpg;Cursos";

function ImportDigital({ onDone }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  async function send() {
    setBusy(true); setRes(null);
    try { const r = await postJSON("/catalog/import-digital", { csv: text }); setRes({ ok: true, ...r }); onDone && onDone(); } catch (e) { setRes({ ok: false, error: e.message }); } finally { setBusy(false); }
  }
  return (
    <div>
      <div style={{ fontSize: 12, color: "#8898aa", marginBottom: 8 }}>
        Hotmart, Eduzz e Monetizze não têm API para descobrir produtos. Escolha no painel de cada uma e cole aqui: <strong>plataforma, nome, link (seu link de afiliado, https), comissão % ou em R$, preço, foto, categoria</strong>.
        Só plataforma, nome e link são obrigatórios. Aceita planilha copiada (separada por tab), vírgula ou ponto e vírgula.
      </div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} placeholder={MODELO} style={{ ...input, fontFamily: "monospace", fontSize: 12 }} />
      <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button onClick={send} disabled={busy || !text.trim()} style={{ border: "none", background: "#5e72e4", color: "#fff", borderRadius: 8, padding: "7px 18px", fontSize: 13, cursor: "pointer" }}>{busy ? "Importando…" : "Importar"}</button>
        <button onClick={() => setText(MODELO)} style={{ border: "1px solid #dee2e6", background: "#fff", borderRadius: 8, padding: "6px 14px", fontSize: 12, cursor: "pointer" }}>Inserir modelo</button>
        {res?.ok && <span style={{ fontSize: 12, color: "#1a7a54" }}>{res.imported} produto(s) importado(s) {Object.entries(res.by_platform).map(([k, v]) => `${k}: ${v}`).join(", ")}{res.errors.length ? ` · ${res.errors.length} linha(s) com problema` : ""}</span>}
        {res && !res.ok && <span style={{ fontSize: 12, color: "#c31e3f" }}>{res.error}</span>}
      </div>
      {res?.ok && res.errors.length > 0 && <ul style={{ fontSize: 11, color: "#b8720a", margin: "8px 0 0 16px" }}>{res.errors.slice(0, 8).map((e) => <li key={e}>{e}</li>)}</ul>}
    </div>
  );
}

export default function Vitrine() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [meta, setMeta] = useState(null);
  const [filter, setFilter] = useState("todos");

  const load = useCallback(() => getJSON("/storefront").then((d) => { setData(d); setMeta((m) => m || { ...d.meta, socials: { ...d.meta.socials } }); }).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  async function saveItem(productId, patch) {
    setMsg(null);
    try { await putJSON(`/storefront/items/${productId}`, patch); await load(); } catch (e) { setMsg({ ok: false, text: e.message }); }
  }
  async function saveMeta() {
    setBusy(true); setMsg(null);
    try {
      const saved = await putJSON("/storefront/meta", { name: meta.name, tagline: meta.tagline, subtitle: meta.subtitle, socials: meta.socials });
      setMeta({ ...saved, socials: { ...saved.socials } });
      setMsg({ ok: true, text: "Dados da loja salvos. Publique para aparecerem no site." });
    } catch (e) { setMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  }
  async function publish() {
    setBusy(true); setMsg(null);
    try {
      const r = await postJSON("/storefront/publish");
      setMsg({ ok: true, text: `Publicado: ${r.count} produto(s) na loja${r.untracked ? ` (${r.untracked} sem contagem de cliques: configure o encurtador)` : ""}.` });
      await load();
    } catch (e) { setMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  }
  async function add(productId) { await saveItem(productId, { hidden: false }); }

  const rows = useMemo(() => {
    const items = data?.items || [];
    if (filter === "ok") return items.filter((r) => r.eligible);
    if (filter === "fora") return items.filter((r) => !r.eligible);
    return items;
  }, [data, filter]);

  if (error) return <p style={{ color: "#f5365c" }}>Não foi possível carregar a vitrine ({error}).</p>;
  if (!data || !meta) return <p style={{ color: "#8898aa" }}>Carregando…</p>;

  const last = data.last_publish;
  return (
    <div>
      <div style={card}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <div>
            <div style={{ fontWeight: 700, color: "#32325d", fontSize: 15 }}>Loja pública · {meta.name}</div>
            <div style={{ fontSize: 12, color: "#8898aa", marginTop: 4 }}>
              {data.publishable} produto(s) prontos · último envio: {last ? `${when(last.at)} (${last.count} produtos, por ${last.by})` : "nunca"}
              {data.public_url && <> · <a href={data.public_url} target="_blank" rel="noreferrer" style={{ color: "#5e72e4" }}>abrir a loja ↗</a></>}
            </div>
            {!data.configured && <div style={{ fontSize: 12, color: "#b8720a", marginTop: 6 }}>A vitrine ainda não está configurada: preencha o card “Vitrine pública” em Integrações (endereço e token) e teste.</div>}
          </div>
          <button onClick={publish} disabled={busy || !data.configured} style={{ border: "none", background: data.configured ? "#2dce89" : "#adb5bd", color: "#fff", borderRadius: 8, padding: "9px 22px", fontSize: 14, fontWeight: 700, cursor: data.configured ? "pointer" : "not-allowed" }}>
            {busy ? "Publicando…" : "Publicar vitrine"}
          </button>
        </div>
        {msg && <div style={{ marginTop: 10, fontSize: 12, padding: "8px 10px", borderRadius: 8, color: msg.ok ? "#1a7a54" : "#c31e3f", background: msg.ok ? "#e5faf1" : "#fef1f4" }}>{msg.text}</div>}
        <div style={{ fontSize: 11, color: "#8898aa", marginTop: 10 }}>
          Entram todos os itens do portfólio (menos pausados), mais o que você adicionar aqui. Comissão, custo e pontuação nunca vão para a loja.
          Produtos de saúde sexual ou adulto são bloqueados e não podem ser liberados.
        </div>
      </div>

      <div style={card}>
        <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14, marginBottom: 10 }}>Dados da loja e redes sociais</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10 }}>
          <label style={{ fontSize: 12, color: "#525f7f" }}>Nome<input style={input} value={meta.name} maxLength={60} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></label>
          <label style={{ fontSize: 12, color: "#525f7f" }}>Frase de abertura<input style={input} value={meta.tagline} maxLength={200} onChange={(e) => setMeta({ ...meta, tagline: e.target.value })} /></label>
          <label style={{ fontSize: 12, color: "#525f7f", gridColumn: "1 / -1" }}>Subtítulo<input style={input} value={meta.subtitle} maxLength={240} onChange={(e) => setMeta({ ...meta, subtitle: e.target.value })} /></label>
          {SOCIALS.map(([key, label]) => (
            <label key={key} style={{ fontSize: 12, color: "#525f7f" }}>{label} (https://…)
              <input style={input} value={meta.socials[key] || ""} placeholder="https://" onChange={(e) => setMeta({ ...meta, socials: { ...meta.socials, [key]: e.target.value } })} />
            </label>
          ))}
        </div>
        <button onClick={saveMeta} disabled={busy} style={{ marginTop: 12, border: "none", background: "#5e72e4", color: "#fff", borderRadius: 8, padding: "7px 18px", fontSize: 13, cursor: "pointer" }}>Salvar dados da loja</button>
      </div>

      <div style={card}>
        <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14, marginBottom: 10 }}>Adicionar produto do catálogo</div>
        <AddFromCatalog onAdd={add} />
      </div>

      <div style={card}>
        <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14, marginBottom: 10 }}>Importar produtos digitais (Hotmart, Eduzz, Monetizze)</div>
        <ImportDigital onDone={load} />
      </div>

      <div style={card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 6 }}>
          <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14 }}>Produtos da vitrine ({data.items.length})</div>
          <div style={{ display: "flex", gap: 6 }}>
            {[["todos", "Todos"], ["ok", "Prontos"], ["fora", "Fora da loja"]].map(([k, label]) => (
              <button key={k} onClick={() => setFilter(k)} style={{ border: "none", borderRadius: 999, padding: "4px 12px", fontSize: 12, cursor: "pointer", background: filter === k ? "#5e72e4" : "#eef0f6", color: filter === k ? "#fff" : "#525f7f" }}>{label}</button>
            ))}
          </div>
        </div>
        {rows.length === 0 ? (
          <p style={{ fontSize: 13, color: "#8898aa" }}>Nenhum produto nesta lista. Vincule produtos ao portfólio ou adicione do catálogo acima.</p>
        ) : (
          rows.map((r) => <ItemRow key={r.product_id} row={r} categories={data.categories} onSave={saveItem} />)
        )}
      </div>
    </div>
  );
}
