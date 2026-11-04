import React, { useEffect, useState } from "react";
import { getJSON, postJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", marginBottom: 16 };

// Mercado Livre não tem API para gerar o link de afiliado: o operador gera no painel de Afiliados (Gerador de link) e cola aqui.
export default function LinksAfiliadoManual({ marketplace = "mercado_livre", name = "Mercado Livre" }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [missing, setMissing] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => getJSON(`/affiliate-links/missing?marketplace=${marketplace}&limit=30`).then(setMissing).catch(() => setMissing(null));
  useEffect(() => { if (open) load(); }, [open, marketplace]); // eslint-disable-line react-hooks/exhaustive-deps

  async function send() {
    setBusy(true); setError(""); setResult(null);
    try { const r = await postJSON("/affiliate-links/import", { text, marketplace }); setResult(r); if (r.saved.length) { setText(""); load(); } }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <div style={card}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        style={{ display: "flex", width: "100%", alignItems: "center", gap: 10, background: "none", border: "none", padding: 0, cursor: "pointer", textAlign: "left" }}>
        <span style={{ fontSize: 12, color: "#8898aa", width: 12 }}>{open ? "▼" : "▶"}</span>
        <span style={{ flex: 1, fontWeight: 700, color: "#32325d", fontSize: 14 }}>🔗 Links de afiliado do {name}
          <span style={{ fontWeight: 400, color: "#525f7f", fontSize: 12 }}> · sem link, o produto não gera comissão nem entra em anúncio direto</span></span>
        <span style={{ fontSize: 12, color: "#5e72e4" }}>{open ? "recolher" : "abrir"}</span>
      </button>
      {open && (
        <div style={{ marginTop: 12, fontSize: 13, color: "#525f7f" }}>
          <ol style={{ margin: "0 0 10px 18px", padding: 0, lineHeight: 1.6 }}>
            <li>No painel de Afiliados do {name}, abra o <strong>Gerador de link</strong>, cole o endereço do produto e copie o link gerado.</li>
            <li>Cole abaixo, <strong>uma linha por produto</strong>: o endereço do produto, um espaço e o link de afiliado.</li>
            <li>O sistema acha o produto pelo código do anúncio e guarda o link. A atualização do catálogo não o apaga.</li>
          </ol>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} spellCheck={false}
            placeholder={"https://produto.mercadolivre.com.br/MLB-123456789-nome-do-produto-_JM https://mercadolivre.com/sec/AbC123"}
            style={{ width: "100%", boxSizing: "border-box", padding: 8, border: "1px solid #dee2e6", borderRadius: 8, fontFamily: "monospace", fontSize: 12 }} />
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            <button disabled={busy || !text.trim()} onClick={send}
              style={{ border: "none", background: "#5e72e4", color: "#fff", borderRadius: 8, padding: "8px 16px", fontSize: 13, fontWeight: 700, cursor: "pointer", opacity: busy || !text.trim() ? 0.5 : 1 }}>Salvar links</button>
            <span style={{ fontSize: 11, color: "#8898aa" }}>Só aceita links de afiliado do próprio {name} ({(missing?.hosts || []).join(", ")}).</span>
          </div>
          {error && <div style={{ marginTop: 8, color: "#c31e3f", background: "#fef1f4", padding: 8, borderRadius: 8 }}>{error}</div>}
          {result && (
            <div style={{ marginTop: 8, fontSize: 12 }}>
              <div style={{ color: "#1a7a54" }}>{result.saved.length} link(s) salvo(s).</div>
              {result.not_in_catalog.map((r, i) => <div key={i} style={{ color: "#b8720a" }}>Fora do catálogo: {r.product_url}</div>)}
              {result.rejected.map((r, i) => <div key={i} style={{ color: "#c31e3f" }}>Recusado: {r.reason} ({r.line})</div>)}
            </div>
          )}
          {missing && missing.items.length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: "pointer", fontSize: 12 }}>{missing.items.length}+ produto(s) do catálogo sem link (os mais caros primeiro)</summary>
              {missing.items.map((p) => (
                <div key={p.product_id} style={{ fontSize: 12, padding: "3px 0", borderBottom: "1px solid #f0f2f7" }}>
                  <strong>R$ {p.price != null ? Number(p.price).toFixed(2).replace(".", ",") : "—"}</strong> · {p.title}
                  {p.product_url && <> · <a href={p.product_url} target="_blank" rel="noreferrer">abrir</a></>}
                </div>
              ))}
            </details>
          )}
        </div>
      )}
    </div>
  );
}
