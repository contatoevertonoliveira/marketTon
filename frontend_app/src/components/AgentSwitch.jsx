import React, { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, postJSON, putJSON } from "../lib/apiClient";

const btn = { border: "none", borderRadius: 8, padding: "8px 14px", fontSize: 13, fontWeight: 600, cursor: "pointer" };

function CopyBlock({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <div style={{ position: "relative", marginTop: 6 }}>
      <pre style={{ margin: 0, padding: "10px 70px 10px 12px", background: "#172b4d", color: "#e8ecf5", borderRadius: 8, fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
        {text}
      </pre>
      <button
        onClick={() => navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); })}
        style={{ ...btn, position: "absolute", top: 6, right: 6, padding: "4px 10px", fontSize: 11, background: "#5e72e4", color: "#fff" }}
      >
        {copied ? "Copiado" : "Copiar"}
      </button>
    </div>
  );
}

function fmtAgo(iso) {
  if (!iso) return null;
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "agora há pouco";
  if (mins < 60) return `há ${mins} min`;
  if (mins < 1440) return `há ${Math.round(mins / 60)} h`;
  return new Date(iso).toLocaleString("pt-BR");
}

function ConnectModal({ mode, onClose, onRefresh }) {
  const [access, setAccess] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const startedAt = useRef(Date.now());

  // Enquanto o painel está aberto, confere de tempos em tempos se o Claude já entrou.
  useEffect(() => {
    const id = setInterval(onRefresh, 4000);
    return () => clearInterval(id);
  }, [onRefresh]);

  async function generate() {
    if (mode.agent_user_exists && !window.confirm("Já existe um acesso do agente. Gerar outro desconecta o Claude até você colar a nova senha. Continuar?")) return;
    setBusy(true);
    setError("");
    try {
      setAccess(await postJSON("/agent/access"));
      startedAt.current = Date.now();
      onRefresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const connected = mode.agent_last_login_at && new Date(mode.agent_last_login_at).getTime() >= startedAt.current - 60000 && !!access;
  const everConnected = !!mode.agent_last_login_at;
  const apiUrl = "http://127.0.0.1:8000";
  const envBlock = access
    ? `$env:MARKETTON_API_URL="${apiUrl}"\n$env:MARKETTON_AGENT_USER="${access.username}"\n$env:MARKETTON_AGENT_PASSWORD="${access.password}"`
    : "";

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(23,43,77,0.55)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "#fff", borderRadius: 16, width: "min(640px, 100%)", maxHeight: "90vh", overflowY: "auto", padding: 24, boxShadow: "0 20px 60px rgba(23,43,77,.35)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h5 style={{ margin: 0, color: "#32325d" }}>🤖 Conectar o Claude ao marketTon</h5>
          <button onClick={onClose} style={{ border: "none", background: "transparent", fontSize: 22, cursor: "pointer", color: "#8898aa" }}>×</button>
        </div>

        <div style={{ fontSize: 12, padding: "9px 12px", borderRadius: 8, marginTop: 14, background: connected ? "#e5faf1" : everConnected ? "#fff8e6" : "#f6f9fc", color: connected ? "#1a7a54" : "#525f7f" }}>
          {connected
            ? `✅ Claude conectado (${fmtAgo(mode.agent_last_login_at)}).`
            : everConnected
              ? `Último acesso do Claude: ${fmtAgo(mode.agent_last_login_at)}. O agente só trabalha enquanto uma sessão do Claude estiver aberta.`
              : "⏳ O Claude ainda não conectou. Siga os passos abaixo; esta tela confirma sozinha."}
        </div>

        <p style={{ fontSize: 12, color: "#8898aa", margin: "12px 0" }}>
          O Claude não faz login pelo site: ele entra no marketTon com um acesso próprio (papel “agente”, sem acesso a
          credenciais nem usuários). O marketTon gera esse acesso para você — não precisa inventar usuário e senha.
        </p>

        <div style={{ fontWeight: 700, fontSize: 13, color: "#32325d" }}>1. Gerar o acesso do agente</div>
        <div style={{ marginTop: 6 }}>
          <button onClick={generate} disabled={busy} style={{ ...btn, background: "#5e72e4", color: "#fff" }}>
            {busy ? "Gerando…" : mode.agent_user_exists ? "Gerar novo acesso" : "Gerar acesso do agente"}
          </button>
          {error && <span style={{ marginLeft: 10, fontSize: 12, color: "#f5365c" }}>{error}</span>}
        </div>

        {access && (
          <>
            <div style={{ fontWeight: 700, fontSize: 13, color: "#32325d", marginTop: 16 }}>2. No PowerShell, na pasta do projeto, cole e abra o Claude Code</div>
            <CopyBlock text={`${envBlock}\nclaude`} />
            <div style={{ fontSize: 11, color: "#c31e3f", marginTop: 6 }}>
              A senha aparece só agora e não fica guardada em texto no marketTon. Copie antes de fechar.
            </div>
            <div style={{ fontSize: 11, color: "#8898aa", marginTop: 6 }}>
              O arquivo <code>.mcp.json</code> do projeto já aponta para o servidor do marketTon; na primeira vez o Claude
              Code pede para você aprovar esse servidor.
            </div>
          </>
        )}

        <div style={{ fontWeight: 700, fontSize: 13, color: "#32325d", marginTop: 16 }}>{access ? "3." : "2."} Abrir o Claude</div>
        <div style={{ marginTop: 6 }}>
          <button onClick={() => window.open("https://claude.ai", "_blank", "noopener")} style={{ ...btn, background: "#f6f9fc", color: "#32325d", border: "1px solid #dee2e6" }}>
            Abrir claude.ai ↗
          </button>
          <span style={{ fontSize: 11, color: "#8898aa", marginLeft: 10 }}>Se pedir, entre com a sua conta do Claude.</span>
        </div>

        <div style={{ fontSize: 11, color: "#8898aa", marginTop: 16, lineHeight: 1.5 }}>
          Com o modo agente <strong>ligado</strong>, o Claude pode agir no portfólio. Com ele <strong>desligado</strong>, só
          consulta. O interruptor vale na hora, mesmo com o Claude conectado.
        </div>
      </div>
    </div>
  );
}

export default function AgentSwitch() {
  const [mode, setMode] = useState(null);
  const [canManage, setCanManage] = useState(false);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    getJSON("/agent/mode").then(setMode).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    getJSON("/auth/me").then((me) => setCanManage(!!me.permissions?.includes("users.manage"))).catch(() => {});
  }, [refresh]);

  async function toggle() {
    const next = !mode.enabled;
    if (
      next &&
      !window.confirm(
        "Ativar a administração pelo agente Claude?\n\n" +
          "Com o modo ligado, o Claude pode: vincular produtos ao portfólio, mover o estado dos produtos, registrar sinais " +
          "manuais e preencher a comissão observada nas vendas.\n\n" +
          "Ele NÃO acessa credenciais, usuários nem publica nada. Cada ação fica na auditoria, e você pode desligar a " +
          "qualquer momento."
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      setMode(await putJSON("/agent/mode", { enabled: next }));
      if (next && !mode.agent_last_login_at) setOpen(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!mode) return null;
  const on = mode.enabled;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      {error && <span style={{ fontSize: 11, color: "#f5365c" }}>{error}</span>}
      <span style={{ fontSize: 12, color: on ? "#1a7a54" : "#8898aa", fontWeight: 600 }}>
        🤖 Agente Claude: {on ? "ativo" : "manual"}
      </span>
      <button
        role="switch"
        aria-checked={on}
        aria-label="Administração pelo agente Claude"
        onClick={toggle}
        disabled={busy || !canManage}
        title={canManage ? (on ? "Voltar para administração manual" : "Ativar a administração pelo agente") : "Só administradores alteram"}
        style={{
          width: 44, height: 24, borderRadius: 999, border: "none", position: "relative", cursor: canManage ? "pointer" : "not-allowed",
          background: on ? "#2dce89" : "#cbd5e1", transition: "background .15s", opacity: busy ? 0.6 : 1,
        }}
      >
        <span style={{ position: "absolute", top: 3, left: on ? 23 : 3, width: 18, height: 18, borderRadius: "50%", background: "#fff", transition: "left .15s", boxShadow: "0 1px 3px rgba(0,0,0,.3)" }} />
      </button>
      {canManage && (
        <button onClick={() => setOpen(true)} style={{ ...btn, padding: "5px 10px", fontSize: 12, background: "#f6f9fc", color: "#525f7f", border: "1px solid #dee2e6" }}>
          {mode.agent_last_login_at ? "Conexão" : "Conectar Claude"}
        </button>
      )}
      {open && <ConnectModal mode={mode} onClose={() => setOpen(false)} onRefresh={refresh} />}
    </div>
  );
}
