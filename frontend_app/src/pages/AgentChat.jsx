import React, { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, patchJSON, postJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 16, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)" };
const STATUS = {
  pronto: { label: "pronto", color: "#1a7a54", bg: "#e5faf1" },
  configurar: { label: "configurar", color: "#8a6d1d", bg: "#fff8e6" },
  nao_construido: { label: "a construir", color: "#c31e3f", bg: "#fef1f4" },
};
const HEALTH = { ok: "#2dce89", aviso: "#f6c944", erro: "#f5365c" };

function time(iso) {
  return iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
}

function Bubble({ m, onStatus }) {
  const mine = m.author === "user";
  if (m.kind === "alert") {
    return (
      <div style={{ alignSelf: "center", maxWidth: "90%", background: "#e5faf1", color: "#1a7a54", borderRadius: 10, padding: "8px 12px", fontSize: 12 }}>
        {m.text} <span style={{ color: "#8898aa" }}>· {time(m.created_at)}</span>
      </div>
    );
  }
  if (m.kind === "task") {
    const open = m.status === "open";
    return (
      <div style={{ alignSelf: "center", maxWidth: "92%", border: "1px dashed #b6c0f5", background: "#f4f6ff", borderRadius: 10, padding: "10px 14px", fontSize: 12, color: "#32325d" }}>
        <strong>📋 Tarefa do agente {open ? "(aguardando o Claude conectar)" : "(concluída)"}</strong>
        <div style={{ whiteSpace: "pre-wrap", marginTop: 4, color: "#525f7f" }}>{m.text}</div>
      </div>
    );
  }
  if (m.kind === "request") {
    const open = m.status === "open";
    return (
      <div style={{ alignSelf: "flex-start", maxWidth: "88%", border: `1px solid ${open ? "#f6c944" : "#e9ecef"}`, background: open ? "#fffaf0" : "#fafbfc", borderRadius: 12, padding: "10px 14px", fontSize: 13 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#8a6d1d", marginBottom: 4 }}>🙋 PEDIDO DO AGENTE · {time(m.created_at)}</div>
        <div style={{ whiteSpace: "pre-wrap", color: "#32325d" }}>{m.text}</div>
        {open ? (
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button onClick={() => onStatus(m.id, "done")} style={{ border: "none", background: "#2dce89", color: "#fff", borderRadius: 6, padding: "5px 10px", fontSize: 12, cursor: "pointer" }}>Já providenciei</button>
            <button onClick={() => onStatus(m.id, "dismissed")} style={{ border: "1px solid #dee2e6", background: "#fff", color: "#525f7f", borderRadius: 6, padding: "5px 10px", fontSize: 12, cursor: "pointer" }}>Dispensar</button>
          </div>
        ) : (
          <div style={{ fontSize: 11, color: "#8898aa", marginTop: 6 }}>{m.status === "done" ? "✓ providenciado" : "dispensado"}</div>
        )}
      </div>
    );
  }
  const isReport = m.kind === "report";
  return (
    <div style={{ alignSelf: mine ? "flex-end" : "flex-start", maxWidth: "88%", background: mine ? "#5e72e4" : isReport ? "#eef2ff" : "#f6f9fc", color: mine ? "#fff" : "#32325d", borderRadius: 12, padding: "9px 13px", fontSize: 13 }}>
      <div style={{ fontSize: 11, opacity: 0.75, marginBottom: 3 }}>
        {mine ? "Você" : m.author === "agent" ? (isReport ? "🤖 Relatório do agente" : "🤖 Agente") : "Sistema"} · {time(m.created_at)}
      </div>
      <div style={{ whiteSpace: "pre-wrap" }}>{m.text}</div>
    </div>
  );
}

function SidePanel({ caps, health }) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ display: "grid", gap: 14, alignContent: "start" }}>
      <div style={card}>
        <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14, marginBottom: 8 }}>
          Saúde do sistema{" "}
          {health && <span style={{ fontSize: 11, color: HEALTH[health.overall] }}>● {health.overall}</span>}
        </div>
        {!health ? (
          <div style={{ fontSize: 12, color: "#8898aa" }}>Carregando…</div>
        ) : (
          health.checks.map((c) => (
            <div key={c.name} style={{ display: "flex", gap: 8, fontSize: 12, padding: "3px 0", color: "#525f7f" }}>
              <span style={{ color: HEALTH[c.status] }}>●</span>
              <span><strong style={{ color: "#32325d" }}>{c.name.replaceAll("_", " ")}</strong> — {c.detail}</span>
            </div>
          ))
        )}
      </div>

      <div style={card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14 }}>O que falta para vender mais</div>
          <button onClick={() => setOpen(!open)} style={{ border: "none", background: "transparent", color: "#5e72e4", fontSize: 12, cursor: "pointer" }}>{open ? "recolher" : "ver"}</button>
        </div>
        {!caps ? (
          <div style={{ fontSize: 12, color: "#8898aa" }}>Carregando…</div>
        ) : (
          <>
            <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
              {Object.entries(caps.summary).map(([k, v]) => (
                <span key={k} style={{ fontSize: 11, fontWeight: 700, color: STATUS[k].color, background: STATUS[k].bg, borderRadius: 999, padding: "2px 9px" }}>{v} {STATUS[k].label}</span>
              ))}
            </div>
            {open && caps.capabilities.filter((c) => c.status !== "pronto").map((c) => (
              <div key={c.key} style={{ padding: "7px 0", borderTop: "1px solid #f0f2f7", fontSize: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <strong style={{ color: "#32325d" }}>{c.name}</strong>
                  <span style={{ fontSize: 10, fontWeight: 700, color: STATUS[c.status].color, background: STATUS[c.status].bg, borderRadius: 999, padding: "1px 8px", whiteSpace: "nowrap" }}>{STATUS[c.status].label}</span>
                </div>
                <div style={{ color: "#8898aa" }}>Destrava: {c.unlocks}</div>
                {c.needs.map((n) => <div key={n} style={{ color: "#525f7f" }}>• {n}</div>)}
                {c.note && <div style={{ color: "#adb5bd", fontSize: 11 }}>{c.note}</div>}
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

export default function AgentChat({ onCountsChange }) {
  const [messages, setMessages] = useState(null);
  const [counts, setCounts] = useState(null);
  const [mode, setMode] = useState(null);
  const [caps, setCaps] = useState(null);
  const [health, setHealth] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);
  const lastId = useRef(0);

  const load = useCallback((initial) => {
    getJSON(`/agent/chat?limit=200${initial ? "" : `&after_id=${lastId.current}`}`)
      .then((d) => {
        setCounts(d.counts);
        onCountsChange?.(d.counts);
        if (initial) {
          setMessages(d.messages);
        } else if (d.messages.length) {
          setMessages((prev) => [...(prev || []), ...d.messages]);
        }
        const all = d.messages;
        if (all.length) lastId.current = all[all.length - 1].id;
        if (d.counts.unread_for_user) postJSON("/agent/chat/read").then((r) => { setCounts(r.counts); onCountsChange?.(r.counts); }).catch(() => {});
      })
      .catch((e) => setError(e.message));
  }, [onCountsChange]);

  useEffect(() => {
    load(true);
    getJSON("/agent/mode").then(setMode).catch(() => {});
    getJSON("/agent/capabilities").then(setCaps).catch(() => {});
    getJSON("/agent/health").then(setHealth).catch(() => {});
    const id = setInterval(() => load(false), 8000);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function send() {
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      const m = await postJSON("/agent/chat", { text });
      setMessages((prev) => [...(prev || []), m]);
      lastId.current = m.id;
      setText("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(id, status) {
    try {
      const m = await patchJSON(`/agent/chat/${id}`, { status });
      setMessages((prev) => prev.map((x) => (x.id === id ? m : x)));
      load(false);
      getJSON("/agent/health").then(setHealth).catch(() => {});
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.6fr) minmax(280px,1fr)", gap: 18, alignItems: "start" }}>
      <div style={{ ...card, display: "flex", flexDirection: "column", height: "calc(100vh - 190px)", minHeight: 420 }}>
        <div style={{ fontSize: 12, padding: "8px 10px", borderRadius: 8, marginBottom: 10, background: mode?.enabled ? "#e5faf1" : "#f6f9fc", color: mode?.enabled ? "#1a7a54" : "#525f7f" }}>
          {mode?.enabled
            ? "Modo agente ATIVO. O agente trabalha enquanto uma sessão do Claude estiver aberta e deixa o que fez aqui."
            : "Modo agente em MANUAL: o agente só consulta. Ative no interruptor do topo para ele agir."}
          {mode && !mode.agent_last_login_at && " O Claude ainda não conectou (use “Conectar Claude”)."}
        </div>

        <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, padding: "4px 2px" }}>
          {messages === null && <div style={{ color: "#8898aa", fontSize: 13 }}>Carregando…</div>}
          {messages?.length === 0 && (
            <div style={{ color: "#8898aa", fontSize: 13, textAlign: "center", marginTop: 40 }}>
              Nenhuma mensagem ainda. Ao ativar o agente, a rotina de ativação aparece aqui; avisos de venda também.
            </div>
          )}
          {messages?.map((m) => <Bubble key={m.id} m={m} onStatus={setStatus} />)}
          <div ref={endRef} />
        </div>

        {error && <div style={{ color: "#f5365c", fontSize: 12, margin: "6px 0" }}>{error}</div>}
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Escreva para o agente (Enter envia, Shift+Enter quebra linha). Ele lê quando uma sessão do Claude estiver aberta."
            rows={2}
            style={{ flex: 1, padding: "9px 11px", border: "1px solid #dee2e6", borderRadius: 8, fontSize: 13, background: "#f6f9fc", resize: "none", fontFamily: "inherit" }}
          />
          <button onClick={send} disabled={busy || !text.trim()} style={{ border: "none", background: "#5e72e4", color: "#fff", borderRadius: 8, padding: "0 20px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
            {busy ? "…" : "Enviar"}
          </button>
        </div>
      </div>

      <SidePanel caps={caps} health={health} />
    </div>
  );
}
