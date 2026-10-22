import React, { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, patchJSON, postJSON, putJSON } from "../lib/apiClient";

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
        <div style={{ fontSize: 11, fontWeight: 700, color: "#8a6d1d", marginBottom: 4 }}>
          🙋 PEDIDO DO AGENTE{m.meta?.category ? ` · ${m.meta.category}` : ""} · {time(m.created_at)}
          {m.meta?.reminders > 0 && ` · cobrado ${m.meta.reminders}x (última ${time(m.meta.last_reminded_at)})`}
        </div>
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


const TRIGGERS = { activation: "ativação", chat: "chat", morning: "rotina da manhã", evening: "rotina da noite", manual: "manual" };
const usd = (v) => (v == null ? null : `US$ ${Number(v).toFixed(v < 0.1 ? 3 : 2)}`);
const kTokens = (n) => (n == null ? null : n >= 1000 ? `${Math.round(n / 1000)} mil` : String(n));
const RUN_STATUS = {
  ok: ["✓", "#2dce89", "concluída"], failed: ["✗", "#f5365c", "falhou"], timeout: ["⏱", "#f5365c", "estourou o tempo"],
  needs_login: ["🔑", "#f6c944", "pediu login"], running: ["…", "#5e72e4", "em execução"],
};

function RuntimePanel() {
  const [rt, setRt] = useState(null);
  const [canManage, setCanManage] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(() => getJSON("/agent/runtime").then(setRt).catch(() => {}), []);
  useEffect(() => {
    load();
    getJSON("/auth/me").then((me) => setCanManage(!!me.permissions?.includes("users.manage"))).catch(() => {});
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  async function runNow() {
    setMsg("");
    try {
      await postJSON("/agent/runtime/run");
      setMsg("Pedido enviado: a rodada começa em instantes.");
      setTimeout(load, 3000);
    } catch (e) {
      setMsg(e.message);
    }
  }

  if (!rt) return null;
  let state;
  if (!rt.autorun) state = ["#8898aa", "#f6f9fc", "Execução automática desligada neste backend (AGENT_AUTORUN=false)."];
  else if (!rt.supervisor_alive) state = ["#8898aa", "#f6f9fc", "O supervisor ainda não subiu: reinicie o backend com o código novo."];
  else if (!rt.claude_found) state = ["#c31e3f", "#fef1f4", "Claude Code não encontrado nesta máquina."];
  else if (rt.waiting_for_login) state = ["#8a6d1d", "#fff8e6", "Aguardando o login do Claude Code: abra um terminal, rode claude e use /login. O agente volta sozinho depois."];
  else if (rt.running_now) state = ["#3b4fb8", "#eef2ff", `Executando agora: ${TRIGGERS[rt.running_now] || rt.running_now}…`];
  else state = ["#1a7a54", "#e5faf1", `Em segundo plano: roda sozinho na ativação, quando você escreve no chat e (autonomia independente) na rotina da manhã (a partir das ${rt.schedule.morning_from_hour}h) e da noite (a partir das ${rt.schedule.evening_from_hour}h).`];

  return (
    <div style={card}>
      <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14, marginBottom: 8 }}>Agente em segundo plano</div>
      <div style={{ fontSize: 12, padding: "8px 10px", borderRadius: 8, color: state[0], background: state[1] }}>{state[2]}</div>
      {rt.usage_today && (
        <div style={{ marginTop: 8, fontSize: 12, color: rt.usage_today.cost_usd >= rt.usage_today.daily_budget_usd || rt.usage_today.runs >= rt.usage_today.max_runs ? "#c31e3f" : "#525f7f" }}>
          Hoje: <strong>{rt.usage_today.runs}</strong> de {rt.usage_today.max_runs} rodadas · <strong>{usd(rt.usage_today.cost_usd) || "US$ 0"}</strong> de {usd(rt.usage_today.daily_budget_usd)} · {kTokens(rt.usage_today.tokens) || 0} tokens
          <div style={{ fontSize: 11, color: "#8898aa" }}>
            Modelo {rt.settings?.model}, esforço {rt.settings?.effort} (chat: {rt.settings?.effort_chat}); teto de {usd(rt.settings?.run_budget_usd)} por rodada.
            Valores a preço de tabela da API — em plano de assinatura servem como medida do consumo. Ao bater o teto do dia, só o "Rodar agora" funciona.
          </div>
        </div>
      )}
      {canManage && (
        <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
          <button onClick={runNow} style={{ border: "none", background: "#5e72e4", color: "#fff", borderRadius: 6, padding: "5px 12px", fontSize: 12, cursor: "pointer" }}>Rodar agora</button>
          {msg && <span style={{ fontSize: 11, color: "#525f7f" }}>{msg}</span>}
        </div>
      )}
      {rt.runs.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: "#8898aa", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>Últimas rodadas</div>
          {rt.runs.slice(0, 6).map((r) => {
            const [icon, color, label] = RUN_STATUS[r.status] || ["?", "#8898aa", r.status];
            return (
              <details key={r.id} style={{ fontSize: 12, padding: "3px 0", borderTop: "1px solid #f0f2f7" }}>
                <summary style={{ cursor: "pointer", color: "#32325d" }}>
                  <span style={{ color, fontWeight: 900 }}>{icon}</span> {TRIGGERS[r.trigger] || r.trigger} · {label}
                  <span style={{ color: "#8898aa" }}> · {time(r.started_at)}{r.duration_seconds ? ` · ${Math.round(r.duration_seconds)}s` : ""}{r.cost_usd != null ? ` · ${usd(r.cost_usd)}` : ""}{r.num_turns ? ` · ${r.num_turns} passos` : ""}</span>
                </summary>
                <div style={{ color: "#525f7f", whiteSpace: "pre-wrap", margin: "4px 0 4px 14px", wordBreak: "break-word" }}>
                  {r.error && <div style={{ color: "#c31e3f" }}>{r.error}</div>}
                  {r.output_tail || "sem saída"}
                </div>
              </details>
            );
          })}
        </div>
      )}
    </div>
  );
}

function GoalsPanel() {
  const [g, setG] = useState(null);
  const [canManage, setCanManage] = useState(false);
  const [edit, setEdit] = useState(null);
  const [msg, setMsg] = useState("");
  const load = useCallback(() => getJSON("/agent/goals").then(setG).catch(() => {}), []);
  useEffect(() => {
    load();
    getJSON("/auth/me").then((me) => setCanManage(!!me.permissions?.includes("users.manage"))).catch(() => {});
  }, [load]);
  if (!g) return null;
  const COLORS = { adiantada: "#2dce89", no_ritmo: "#5e72e4", atrasada: "#f5365c", sem_meta: "#adb5bd" };
  const LABELS = { adiantada: "adiantada", no_ritmo: "no ritmo", atrasada: "atrasada", sem_meta: "sem meta" };
  const fmt = (m, v) => (m.unit === "R$" ? Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : Number(v).toLocaleString("pt-BR"));
  async function save() {
    setMsg("");
    try {
      const targets = Object.fromEntries(Object.entries(edit).map(([k, v]) => [k, Number(String(v).replace(",", "."))]));
      setG(await putJSON("/agent/goals", { targets }));
      setEdit(null);
    } catch (e) { setMsg(e.message); }
  }
  return (
    <div style={card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14 }}>Metas de {g.period}</div>
        {canManage && !edit && <button onClick={() => setEdit(Object.fromEntries(g.metrics.map((m) => [m.key, m.target])))} style={{ border: "none", background: "transparent", color: "#5e72e4", fontSize: 12, cursor: "pointer" }}>editar</button>}
      </div>
      <div style={{ fontSize: 11, color: "#8898aa", marginBottom: 8 }}>{g.summary} Faltam {g.days_left} dia(s) no mês.</div>
      {g.metrics.map((m) => (
        <div key={m.key} style={{ padding: "6px 0", fontSize: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <strong style={{ color: "#32325d" }}>{m.label}{m.suggested ? " (sugerida)" : ""}</strong>
            <span style={{ color: COLORS[m.status], fontWeight: 700 }}>{LABELS[m.status]}</span>
          </div>
          {edit ? (
            <input value={edit[m.key]} onChange={(e) => setEdit({ ...edit, [m.key]: e.target.value })} style={{ width: "100%", boxSizing: "border-box", marginTop: 4, padding: "4px 8px", border: "1px solid #dee2e6", borderRadius: 6 }} />
          ) : (
            <>
              <div style={{ height: 6, background: "#eef0f6", borderRadius: 999, margin: "5px 0", position: "relative" }}>
                <div style={{ width: `${Math.min(100, m.pct || 0)}%`, height: "100%", background: COLORS[m.status], borderRadius: 999 }} />
                {m.expected_pct < 100 && <div title="ritmo esperado hoje" style={{ position: "absolute", left: `${m.expected_pct}%`, top: -3, width: 2, height: 12, background: "#32325d" }} />}
              </div>
              <div style={{ color: "#8898aa" }}>{fmt(m, m.current)} de {fmt(m, m.target)}{m.projection != null ? ` · projeção do mês: ${fmt(m, m.projection)}` : ""}</div>
            </>
          )}
        </div>
      ))}
      {edit && (
        <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
          <button onClick={save} style={{ border: "none", background: "#2dce89", color: "#fff", borderRadius: 6, padding: "5px 14px", fontSize: 12, cursor: "pointer" }}>Salvar metas</button>
          <button onClick={() => setEdit(null)} style={{ border: "none", background: "transparent", color: "#8898aa", fontSize: 12, cursor: "pointer" }}>cancelar</button>
          {msg && <span style={{ fontSize: 11, color: "#c31e3f" }}>{msg}</span>}
        </div>
      )}
    </div>
  );
}

function SidePanel({ caps, health }) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ display: "grid", gap: 14, alignContent: "start" }}>
      <RuntimePanel />
      <GoalsPanel />
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
            ? "Modo agente ATIVO. O agente trabalha em segundo plano (sem terminal) e deixa o que fez aqui."
            : "Modo agente em MANUAL: o agente só consulta. Ative no interruptor do topo para ele agir."}
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
            placeholder="Escreva para o agente (Enter envia, Shift+Enter quebra linha). Ele lê e responde em segundo plano."
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
