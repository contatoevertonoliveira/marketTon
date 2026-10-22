import React, { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../lib/apiClient";

const CHANNEL_LABELS = {
  instagram: "Instagram", tiktok: "TikTok", youtube: "YouTube", pinterest: "Pinterest", whatsapp: "WhatsApp",
  telegram: "Telegram", facebook: "Facebook", x: "X", shopee_video: "Shopee Vídeo", outro: "Outro",
};

// Links curtos rastreados do produto: o que se divulga é o link curto, que conta o clique.
export default function TrackedLinks({ portfolioItem }) {
  const [links, setLinks] = useState(null);
  const [channels, setChannels] = useState(Object.keys(CHANNEL_LABELS));
  const [channel, setChannel] = useState("instagram");
  const [campaign, setCampaign] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [copied, setCopied] = useState("");

  const load = useCallback(() => {
    getJSON(`/links?portfolio_item_id=${portfolioItem.id}`).then(setLinks).catch(() => setLinks([]));
  }, [portfolioItem.id]);

  useEffect(() => {
    load();
    getJSON("/links/channels").then(setChannels).catch(() => {});
  }, [load]);

  async function create() {
    setBusy(true);
    setMsg(null);
    try {
      await postJSON("/links", { portfolio_item_id: portfolioItem.id, channel, campaign: campaign.trim() || null });
      setCampaign("");
      load();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function sync() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await postJSON("/links/sync");
      setMsg(`${r.new_clicks} clique(s) novo(s).`);
      load();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }

  const input = { padding: "5px 9px", fontSize: 12, border: "1px solid #dee2e6", borderRadius: 8, background: "#fff" };
  const total = (links || []).reduce((n, l) => n + l.clicks, 0);

  return (
    <div style={{ border: "1px solid #eef0f5", borderRadius: 12, padding: 16, background: "#fcfdff", marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14 }}>🔗 Links rastreados</div>
        <div style={{ fontSize: 12, color: "#8898aa" }}>{links ? `${links.length} link(s) · ${total} clique(s)` : ""}</div>
      </div>
      <div style={{ fontSize: 11, color: "#8898aa", margin: "4px 0 10px" }}>
        Divulgue o link curto, não o comum: ele conta os cliques de pessoas (não de robôs). Um link por canal e ângulo.
      </div>

      {(links || []).map((l) => (
        <div key={l.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, padding: "4px 0", borderTop: "1px solid #f0f2f7" }}>
          <span style={{ width: 92, color: "#525f7f" }}>{CHANNEL_LABELS[l.channel] || l.channel}</span>
          <span style={{ flex: 1, color: "#32325d", wordBreak: "break-all" }}>
            {l.short_url}
            {l.campaign && <span style={{ color: "#8898aa" }}> · {l.campaign}</span>}
          </span>
          <strong style={{ color: "#32325d", minWidth: 54, textAlign: "right" }}>{l.clicks} cliq.</strong>
          <button
            onClick={() => navigator.clipboard.writeText(l.short_url).then(() => { setCopied(l.id); setTimeout(() => setCopied(""), 1500); })}
            style={{ border: "none", background: "#5e72e4", color: "#fff", borderRadius: 6, padding: "3px 9px", fontSize: 11, cursor: "pointer" }}
          >
            {copied === l.id ? "Copiado" : "Copiar"}
          </button>
        </div>
      ))}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10, alignItems: "center" }}>
        <select value={channel} onChange={(e) => setChannel(e.target.value)} style={input}>
          {channels.map((c) => <option key={c} value={c}>{CHANNEL_LABELS[c] || c}</option>)}
        </select>
        <input value={campaign} onChange={(e) => setCampaign(e.target.value)} placeholder="ângulo/gancho (opcional)" style={{ ...input, flex: 1, minWidth: 140 }} maxLength={128} />
        <button onClick={create} disabled={busy} style={{ border: "none", background: "#2dce89", color: "#fff", borderRadius: 8, padding: "6px 14px", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
          Criar link rastreado
        </button>
        <button onClick={sync} disabled={busy} style={{ border: "1px solid #dee2e6", background: "#fff", color: "#525f7f", borderRadius: 8, padding: "6px 12px", fontSize: 12, cursor: "pointer" }}>
          Atualizar cliques
        </button>
      </div>
      {msg && <div style={{ fontSize: 11, color: "#525f7f", marginTop: 6 }}>{msg}</div>}
    </div>
  );
}
