import React, { useEffect, useState } from "react";
import { API_BASE, getJSON, getTokens, putJSON } from "../lib/apiClient";

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

const NAMES = {
  mercado_livre: "Mercado Livre",
  shopee: "Shopee",
  amazon: "Amazon",
  tiktok_shop: "TikTok Shop",
};

function MarketplaceCard({ credential, onSaved }) {
  const [enabled, setEnabled] = useState(credential.enabled);
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [mlAuthUrl, setMlAuthUrl] = useState("");
  const [error, setError] = useState("");

  async function save() {
    setSaving(true);
    setError("");
    try {
      const data = await putJSON(`/marketplaces/${credential.marketplace}/credentials`, { enabled, values });
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

  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <strong style={{ color: "#32325d" }}>{NAMES[credential.marketplace] || credential.marketplace}</strong>
          <div style={{ fontSize: 11, color: "#8898aa" }}>
            {credential.configured === null ? (
              "sem diagnóstico de conector"
            ) : (
              <span style={{ color: credential.configured ? "#2dce89" : "#f5365c" }}>
                {credential.configured ? "conectado" : "não configurado"}
              </span>
            )}
            {credential.reliability != null && ` · confiabilidade ${credential.reliability}`}
          </div>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#525f7f" }}>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          ativo
        </label>
      </div>

      <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
        {credential.fields.map((field) => (
          <input
            key={field.name}
            style={{ ...input, width: "100%" }}
            type={field.secret ? "password" : "text"}
            placeholder={`${field.label}${credential.values_set?.[field.name] ? " (configurado — deixe em branco para manter)" : ""}`}
            value={values[field.name] || ""}
            onChange={(e) => setValues({ ...values, [field.name]: e.target.value })}
          />
        ))}

        {credential.marketplace === "mercado_livre" && (
          <div style={{ fontSize: 11, color: "#8898aa", background: "#f6f9fc", padding: 8, borderRadius: 6 }}>
            Cadastre esta Redirect URI no app da Mercado Livre:{" "}
            <code>{API_BASE}/marketplaces/mercado_livre/oauth/callback</code>
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
          {credential.marketplace === "mercado_livre" && (
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
            Se a aba não abriu:{" "}
            <a href={mlAuthUrl} target="_blank" rel="noreferrer">
              {mlAuthUrl}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Integrations() {
  const [credentials, setCredentials] = useState([]);
  const [error, setError] = useState(null);

  function load() {
    getJSON("/marketplaces/credentials")
      .then((data) => {
        setCredentials(data);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  if (error) {
    return <p style={{ color: "#f5365c" }}>Não foi possível falar com o backend: {error}</p>;
  }

  return (
    <div>
      <p style={{ color: "#525f7f" }}>
        Credenciais ficam salvas no Postgres (não em <code>.env</code>) — cada marketplace tem seu próprio esquema de
        autenticação. Segredos nunca voltam preenchidos aqui; o campo mostra se já está configurado.
      </p>
      {credentials.map((c) => (
        <MarketplaceCard key={c.marketplace} credential={c} onSaved={load} />
      ))}
    </div>
  );
}
