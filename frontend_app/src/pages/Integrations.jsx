import React, { useEffect, useState } from "react";
import { INTEL_API, getJSON } from "../lib/intelApi";

const card = {
  background: "#fff",
  borderRadius: 10,
  padding: 18,
  boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)",
};

const input = {
  padding: "7px 9px",
  border: "1px solid #dee2e6",
  borderRadius: 6,
  background: "#f6f9fc",
  color: "#32325d",
  fontSize: 13,
};

async function putJSON(path, body) {
  const res = await fetch(`${INTEL_API}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail || res.statusText);
  return res.json();
}

function MarketplaceCard({ marketplace, onSaved }) {
  const [enabled, setEnabled] = useState(marketplace.credential_enabled);
  const [mode, setMode] = useState(marketplace.credential_mode);
  const [scope, setScope] = useState(marketplace.credential_scope);
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [mlAuthUrl, setMlAuthUrl] = useState("");
  const [error, setError] = useState("");

  async function save() {
    setSaving(true);
    setError("");
    try {
      const data = await putJSON(`/marketplaces/${marketplace.slug}/credentials/`, { enabled, mode, scope, values });
      setValues({});
      onSaved(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function connectMercadoLivre() {
    setError("");
    try {
      const data = await (await fetch(`${INTEL_API}/marketplaces/mercado_livre/oauth/start/`, { method: "POST" })).json();
      if (!data.ok) {
        setError(data.error || "falha ao iniciar login");
        return;
      }
      setMlAuthUrl(data.url);
      window.open(data.url, "_blank", "noopener");
    } catch (e) {
      setError(e.message);
    }
  }

  const accessTokenConfigured = marketplace.credential_status?.access_token;

  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <strong style={{ color: "#32325d" }}>{marketplace.name}</strong>
          <div style={{ fontSize: 11, color: "#8898aa" }}>
            {marketplace.slug === "mercado_livre" && (
              <span style={{ color: accessTokenConfigured ? "#2dce89" : "#f5365c" }}>
                {accessTokenConfigured ? "conectado (access token presente)" : "não conectado"}
              </span>
            )}
            {marketplace.slug !== "mercado_livre" && marketplace.credential_schema.length === 0 && "sem integração implementada ainda"}
            {marketplace.slug !== "mercado_livre" &&
              marketplace.credential_schema.length > 0 &&
              (Object.values(marketplace.credential_status || {}).every(Boolean)
                ? "credenciais configuradas"
                : "credenciais incompletas")}
          </div>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#525f7f" }}>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          ativo
        </label>
      </div>

      <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <select style={{ ...input, flex: 1 }} value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="affiliate">afiliado</option>
            <option value="dropshipping">dropshipping</option>
            <option value="both">ambos</option>
          </select>
          <input
            style={{ ...input, flex: 1 }}
            placeholder="scope"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          />
        </div>

        {marketplace.credential_schema.map((field) => (
          <div key={field.name}>
            <input
              style={{ ...input, width: "100%" }}
              type={field.secret ? "password" : "text"}
              placeholder={`${field.label}${marketplace.credential_status?.[field.name] ? " (configurado — deixe em branco para manter)" : ""}`}
              value={values[field.name] || ""}
              onChange={(e) => setValues({ ...values, [field.name]: e.target.value })}
            />
          </div>
        ))}

        {marketplace.slug === "mercado_livre" && (
          <div style={{ fontSize: 11, color: "#8898aa", background: "#f6f9fc", padding: 8, borderRadius: 6 }}>
            Cadastre esta Redirect URI no app da Mercado Livre:{" "}
            <code>http://127.0.0.1:8001/api/marketplaces/mercado_livre/oauth/callback/</code>
          </div>
        )}

        {error && <div style={{ fontSize: 12, color: "#f5365c" }}>{error}</div>}

        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={save}
            disabled={saving}
            style={{ background: "#2dce89", color: "#fff", border: "none", borderRadius: 6, padding: "8px 14px", fontSize: 13, cursor: "pointer" }}
          >
            Salvar
          </button>
          {marketplace.slug === "mercado_livre" && (
            <button
              onClick={connectMercadoLivre}
              style={{ background: "#5e72e4", color: "#fff", border: "none", borderRadius: 6, padding: "8px 14px", fontSize: 13, cursor: "pointer" }}
            >
              Conectar com Mercado Livre
            </button>
          )}
        </div>
        {mlAuthUrl && (
          <div style={{ fontSize: 11, color: "#525f7f" }}>
            Se a aba não abriu: <a href={mlAuthUrl} target="_blank" rel="noreferrer">{mlAuthUrl}</a>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Integrations() {
  const [marketplaces, setMarketplaces] = useState([]);
  const [error, setError] = useState(null);

  function load() {
    getJSON("/marketplaces/")
      .then((data) => {
        setMarketplaces(data.results || []);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  if (error) {
    return <p style={{ color: "#f5365c" }}>Não foi possível falar com o backend de inteligência (porta 8001): {error}</p>;
  }

  return (
    <div>
      <p style={{ color: "#525f7f" }}>
        Credenciais ficam salvas no banco (não em <code>.env</code>) — cada marketplace tem seu próprio esquema de
        autenticação. Segredos nunca voltam preenchidos aqui; o campo mostra se já está configurado.
      </p>
      {marketplaces.map((m) => (
        <MarketplaceCard key={m.slug} marketplace={m} onSaved={load} />
      ))}
    </div>
  );
}
