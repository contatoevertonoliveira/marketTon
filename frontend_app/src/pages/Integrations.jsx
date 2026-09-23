import React, { useEffect, useState } from "react";
import { API_BASE, getJSON, getTokens, postJSON, putJSON } from "../lib/apiClient";

const input = {
  padding: "8px 10px",
  border: "1px solid #dee2e6",
  borderRadius: 8,
  background: "#f6f9fc",
  color: "#32325d",
  fontSize: 13,
  width: "100%",
  boxSizing: "border-box",
};

const MARKETPLACES = {
  mercado_livre: { name: "Mercado Livre", icon: "🛒", color: "#ffe600" },
  shopee: { name: "Shopee", icon: "🛍️", color: "#ee4d2d" },
  amazon: { name: "Amazon", icon: "📦", color: "#ff9900" },
  tiktok_shop: { name: "TikTok Shop", icon: "🎵", color: "#010101" },
};

// verde = testado e funcionando · amarelo = configurado, ainda não validado
// (ou credencial mudou desde o último teste) · vermelho = sem credencial ou
// último teste falhou.
function semaphore(credential) {
  if (credential.last_check_status === "ok") return { color: "#2dce89", label: "conectado" };
  if (credential.last_check_status === "error") return { color: "#f5365c", label: "falha na conexão" };
  if (credential.configured) return { color: "#f6c944", label: "não validado" };
  return { color: "#f5365c", label: "não configurado" };
}

function Led({ color, title }) {
  return (
    <span
      title={title}
      style={{
        display: "inline-block",
        width: 11,
        height: 11,
        borderRadius: "50%",
        background: color,
        boxShadow: `0 0 6px ${color}`,
        flexShrink: 0,
      }}
    />
  );
}

function MarketplaceCard({ credential, onOpen }) {
  const meta = MARKETPLACES[credential.marketplace] || { name: credential.marketplace, icon: "🔌" };
  const status = semaphore(credential);
  return (
    <button
      onClick={onOpen}
      style={{
        background: "#fff",
        border: "1px solid #eef0f5",
        borderRadius: 14,
        padding: 20,
        cursor: "pointer",
        textAlign: "left",
        boxShadow: "0 0 2rem 0 rgba(136,152,170,.12)",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        transition: "transform .12s ease, box-shadow .12s ease",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.transform = "translateY(-2px)")}
      onMouseLeave={(e) => (e.currentTarget.style.transform = "translateY(0)")}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ fontSize: 30 }}>{meta.icon}</div>
        <Led color={status.color} title={status.label} />
      </div>
      <div>
        <div style={{ fontWeight: 700, color: "#32325d", fontSize: 15 }}>{meta.name}</div>
        <div style={{ fontSize: 12, color: status.color, fontWeight: 600, marginTop: 2 }}>{status.label}</div>
      </div>
      <div style={{ fontSize: 11, color: "#8898aa" }}>
        {credential.enabled ? "ativo" : "desativado"}
        {credential.reliability != null && ` · confiabilidade ${credential.reliability}`}
      </div>
    </button>
  );
}

function MarketplaceModal({ credential, onClose, onSaved }) {
  const meta = MARKETPLACES[credential.marketplace] || { name: credential.marketplace, icon: "🔌" };
  const [enabled, setEnabled] = useState(credential.enabled);
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(
    credential.last_check_status
      ? { status: credential.last_check_status, message: credential.last_check_message, at: credential.last_check_at }
      : null
  );
  const [mlAuthUrl, setMlAuthUrl] = useState("");
  const [error, setError] = useState("");

  async function save(andTest) {
    setSaving(true);
    setError("");
    try {
      const data = await putJSON(`/marketplaces/${credential.marketplace}/credentials`, { enabled, values });
      setValues({});
      setTestResult(
        data.last_check_status ? { status: data.last_check_status, message: data.last_check_message, at: data.last_check_at } : null
      );
      onSaved(data);
      if (andTest) await test();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function test() {
    setTesting(true);
    setError("");
    try {
      const data = await postJSON(`/marketplaces/${credential.marketplace}/test`, {});
      setTestResult({ status: data.last_check_status, message: data.last_check_message, at: data.last_check_at });
      onSaved(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setTesting(false);
    }
  }

  async function connectMercadoLivre() {
    setError("");
    try {
      const { access } = getTokens();
      const res = await fetch(`${API_BASE}/marketplaces/mercado_livre/oauth/start`, {
        method: "POST",
        headers: { Authorization: `Bearer ${access}` },
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.detail || "falha ao iniciar login");
        return;
      }
      setMlAuthUrl(data.url);
      window.open(data.url, "_blank", "noopener");
    } catch (e) {
      setError(e.message);
    }
  }

  const status = testResult
    ? semaphore({ ...credential, last_check_status: testResult.status, configured: credential.configured })
    : semaphore(credential);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(23,43,77,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 200,
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 16,
          width: "min(560px, 100%)",
          maxHeight: "88vh",
          overflowY: "auto",
          boxShadow: "0 20px 60px rgba(23,43,77,.35)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            padding: "20px 24px",
            borderBottom: "1px solid #f0f2f7",
          }}
        >
          <div style={{ fontSize: 32 }}>{meta.icon}</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 18, color: "#32325d" }}>{meta.name}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: status.color, fontWeight: 600 }}>
              <Led color={status.color} title={status.label} />
              {status.label}
              {testResult?.at && (
                <span style={{ color: "#8898aa", fontWeight: 400 }}>
                  · testado em {new Date(testResult.at).toLocaleString("pt-BR")}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ border: "none", background: "transparent", fontSize: 22, cursor: "pointer", color: "#8898aa" }}
          >
            ×
          </button>
        </div>

        <div style={{ padding: 24, display: "grid", gap: 12 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#525f7f" }}>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Integração ativa
          </label>

          {credential.fields.map((field) => (
            <div key={field.name}>
              <div style={{ fontSize: 12, color: "#8898aa", marginBottom: 4 }}>{field.label}</div>
              <input
                style={input}
                type={field.secret ? "password" : "text"}
                placeholder={credential.values_set?.[field.name] ? "configurado — deixe em branco para manter" : field.label}
                value={values[field.name] || ""}
                onChange={(e) => setValues({ ...values, [field.name]: e.target.value })}
              />
            </div>
          ))}

          {credential.marketplace === "mercado_livre" && (
            <div style={{ fontSize: 11, color: "#8898aa", background: "#f6f9fc", padding: 10, borderRadius: 8 }}>
              Cadastre esta Redirect URI no app da Mercado Livre:{" "}
              <code>{API_BASE}/marketplaces/mercado_livre/oauth/callback</code>
            </div>
          )}

          {testResult?.message && (
            <div
              style={{
                fontSize: 12,
                padding: 10,
                borderRadius: 8,
                background: testResult.status === "ok" ? "#e5faf1" : "#fef1f4",
                color: testResult.status === "ok" ? "#1a7a54" : "#c31e3f",
              }}
            >
              {testResult.message}
            </div>
          )}
          {error && <div style={{ fontSize: 12, color: "#f5365c" }}>{error}</div>}

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
            <button
              onClick={() => save(false)}
              disabled={saving}
              style={{ background: "#2dce89", color: "#fff", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, cursor: "pointer" }}
            >
              {saving ? "Salvando…" : "Salvar"}
            </button>
            <button
              onClick={test}
              disabled={testing || !credential.configured && !Object.keys(values).length}
              style={{ background: "#11cdef", color: "#fff", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, cursor: "pointer" }}
            >
              {testing ? "Testando…" : "Testar conexão"}
            </button>
            {credential.marketplace === "mercado_livre" && (
              <button
                onClick={connectMercadoLivre}
                style={{ background: "#5e72e4", color: "#fff", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, cursor: "pointer" }}
              >
                Conectar com Mercado Livre
              </button>
            )}
          </div>
          {mlAuthUrl && (
            <div style={{ fontSize: 11, color: "#525f7f" }}>
              Se a aba não abriu:{" "}
              <a href={mlAuthUrl} target="_blank" rel="noreferrer">
                {mlAuthUrl}
              </a>
            </div>
          )}

          {credential.marketplace === "mercado_livre" && <CommissionPanel />}
        </div>
      </div>
    </div>
  );
}

function CommissionPanel() {
  const [rows, setRows] = useState(null);
  const [edits, setEdits] = useState({});
  const [msg, setMsg] = useState("");

  useEffect(() => {
    getJSON("/marketplaces/mercado_livre/commissions").then(setRows).catch((e) => setMsg(e.message));
  }, []);

  async function save() {
    const rates = {};
    for (const [id, v] of Object.entries(edits)) rates[id] = v === "" ? null : Number(String(v).replace(",", "."));
    try {
      await putJSON("/marketplaces/mercado_livre/commissions", { rates });
      setEdits({});
      setRows(await getJSON("/marketplaces/mercado_livre/commissions"));
      setMsg("Salvo.");
    } catch (e) {
      setMsg(e.message);
    }
  }

  return (
    <div style={{ marginTop: 8, paddingTop: 16, borderTop: "1px solid #f0f2f7" }}>
      <strong style={{ color: "#32325d", fontSize: 13 }}>Comissão de afiliado por categoria</strong>
      <div style={{ fontSize: 11, color: "#8898aa", margin: "4px 0 10px" }}>
        A API não informa comissão. Digite a % de cada categoria conforme o painel do seu programa de afiliados.
        Categoria em branco = sem estimativa.
      </div>
      {!rows ? (
        <div style={{ fontSize: 12, color: "#8898aa" }}>{msg || "carregando categorias..."}</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8, maxHeight: 220, overflowY: "auto" }}>
          {rows.map((r) => (
            <label key={r.category_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, fontSize: 12, color: "#525f7f" }}>
              <span>{r.name}</span>
              <input
                style={{ ...input, width: 60 }}
                placeholder="%"
                value={edits[r.category_id] ?? (r.rate_pct ?? "")}
                onChange={(e) => setEdits({ ...edits, [r.category_id]: e.target.value })}
              />
            </label>
          ))}
        </div>
      )}
      <div style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "center" }}>
        <button
          onClick={save}
          disabled={!Object.keys(edits).length}
          style={{ background: "#2dce89", color: "#fff", border: "none", borderRadius: 6, padding: "7px 12px", fontSize: 12, cursor: "pointer" }}
        >
          Salvar comissões
        </button>
        {msg && rows && <span style={{ fontSize: 11, color: "#525f7f" }}>{msg}</span>}
      </div>
    </div>
  );
}

export default function Integrations() {
  const [credentials, setCredentials] = useState([]);
  const [error, setError] = useState(null);
  const [openMarketplace, setOpenMarketplace] = useState(null);

  function load() {
    return getJSON("/marketplaces/credentials")
      .then((data) => {
        setCredentials(data);
        setError(null);
        return data;
      })
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    load();
  }, []);

  if (error) {
    return <p style={{ color: "#f5365c" }}>Não foi possível falar com o backend: {error}</p>;
  }

  const open = credentials.find((c) => c.marketplace === openMarketplace);

  return (
    <div>
      <p style={{ color: "#525f7f", fontSize: 13 }}>
        Credenciais ficam salvas no Postgres (não em <code>.env</code>). Clique num card para configurar e testar a
        conexão. O ponto colorido mostra o estado real: <strong style={{ color: "#2dce89" }}>verde</strong> = testado
        e funcionando, <strong style={{ color: "#f6c944" }}>amarelo</strong> = configurado mas ainda não validado,{" "}
        <strong style={{ color: "#f5365c" }}>vermelho</strong> = sem credencial ou última tentativa falhou.
      </p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(160px, 1fr))",
          gap: 16,
          marginTop: 16,
        }}
      >
        {credentials.map((c) => (
          <MarketplaceCard key={c.marketplace} credential={c} onOpen={() => setOpenMarketplace(c.marketplace)} />
        ))}
      </div>

      {open && (
        <MarketplaceModal
          credential={open}
          onClose={() => setOpenMarketplace(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}
