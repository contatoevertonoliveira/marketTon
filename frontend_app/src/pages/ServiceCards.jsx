import React, { useEffect, useState } from "react";
import { getJSON, postJSON, putJSON } from "../lib/apiClient";

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

// Mesmo semáforo dos marketplaces: verde só depois de um teste real que passou.
function semaphore(s) {
  if (s.last_check_status === "ok") return { color: "#2dce89", label: "conectado" };
  if (s.last_check_status === "error") return { color: "#f5365c", label: "falha na conexão" };
  if (s.configured) return { color: "#f6c944", label: "não validado" };
  return { color: "#f5365c", label: "não configurado" };
}

function Led({ color }) {
  return (
    <span style={{ display: "inline-block", width: 11, height: 11, borderRadius: "50%", background: color, boxShadow: `0 0 6px ${color}`, flexShrink: 0 }} />
  );
}

function ServiceModal({ service, onClose, onSaved }) {
  const [enabled, setEnabled] = useState(service.enabled);
  const [values, setValues] = useState({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const status = semaphore(service);

  async function save() {
    setBusy("save");
    setError("");
    try {
      const data = await putJSON(`/integrations/services/${service.service}`, { enabled, values });
      setValues({});
      onSaved(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }

  async function test() {
    setBusy("test");
    setError("");
    try {
      onSaved(await postJSON(`/integrations/services/${service.service}/test`, {}));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(23,43,77,0.55)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200, padding: 20 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: "#fff", borderRadius: 16, width: "min(560px, 100%)", maxHeight: "88vh", overflowY: "auto", boxShadow: "0 20px 60px rgba(23,43,77,.35)" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "20px 24px", borderBottom: "1px solid #f0f2f7" }}>
          <div style={{ fontSize: 32 }}>{service.icon || "🔌"}</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 17, color: "#32325d" }}>{service.name}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: status.color, fontWeight: 600 }}>
              <Led color={status.color} />
              {status.label}
              {service.last_check_at && (
                <span style={{ color: "#8898aa", fontWeight: 400 }}>· testado em {new Date(service.last_check_at).toLocaleString("pt-BR")}</span>
              )}
            </div>
          </div>
          <button onClick={onClose} style={{ border: "none", background: "transparent", fontSize: 22, cursor: "pointer", color: "#8898aa" }}>
            ×
          </button>
        </div>

        <div style={{ padding: 24, display: "grid", gap: 12 }}>
          <div style={{ fontSize: 12, color: "#525f7f" }}>{service.description}</div>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#525f7f" }}>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Integração ativa
          </label>

          {service.fields.map((field) => (
            <div key={field.name}>
              <div style={{ fontSize: 12, color: "#8898aa", marginBottom: 4 }}>{field.label}</div>
              <input
                style={input}
                type={field.secret ? "password" : "text"}
                autoComplete="off"
                placeholder={service.values_set?.[field.name] ? "configurado — deixe em branco para manter" : ""}
                value={values[field.name] || ""}
                onChange={(e) => setValues({ ...values, [field.name]: e.target.value })}
              />
            </div>
          ))}

          {service.last_check_message && (
            <div
              style={{
                fontSize: 12,
                padding: 10,
                borderRadius: 8,
                background: service.last_check_status === "ok" ? "#e5faf1" : "#fef1f4",
                color: service.last_check_status === "ok" ? "#1a7a54" : "#c31e3f",
              }}
            >
              {service.last_check_message}
            </div>
          )}
          {error && <div style={{ fontSize: 12, color: "#f5365c" }}>{error}</div>}

          <div style={{ fontSize: 11, color: "#8898aa", background: "#f6f9fc", padding: 10, borderRadius: 8 }}>
            {service.service === "google_ads"
              ? `O teste confirma o login OAuth e consulta a conta. O Developer Token não é mais necessário (o Google o
                desativou em 09/09/2026); o acesso agora é do projeto do Google Cloud. Se o Google responder
                "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION" (ou "ACTION_NOT_PERMITTED"), as credenciais estão certas e o
                projeto ainda não tem acesso de produção (Exploração/Básico).`
              : `O teste confere o endereço e o token junto ao redirecionador. Os links curtos ficam em
                endereço/r/código; cada clique de pessoa (não de robô) é contado sem guardar IP nem cookie.`}
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
            <button
              onClick={save}
              disabled={busy !== ""}
              style={{ background: "#2dce89", color: "#fff", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, cursor: "pointer" }}
            >
              {busy === "save" ? "Salvando…" : "Salvar"}
            </button>
            <button
              onClick={test}
              disabled={busy !== "" || (!service.configured && !Object.keys(values).length)}
              style={{ background: "#11cdef", color: "#fff", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, cursor: "pointer" }}
            >
              {busy === "test" ? "Testando…" : "Testar conexão"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ServiceCards() {
  const [services, setServices] = useState(null);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");

  function load() {
    getJSON("/integrations/services")
      .then((data) => {
        setServices(data);
        setError("");
      })
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  if (error) return <p style={{ color: "#f5365c", fontSize: 13 }}>Serviços de dados indisponíveis ({error}).</p>;
  if (!services) return null;

  const current = services.find((s) => s.service === open);

  return (
    <div style={{ marginTop: 28 }}>
      <h6 style={{ color: "#32325d", margin: "0 0 4px" }}>Serviços de dados</h6>
      <div style={{ fontSize: 12, color: "#8898aa", marginBottom: 12 }}>
        Fontes de métricas que não são marketplaces. Alimentam a página Oportunidades de Busca.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(160px, 1fr))", gap: 16 }}>
        {services.map((s) => {
          const status = semaphore(s);
          return (
            <button
              key={s.service}
              onClick={() => setOpen(s.service)}
              style={{ background: "#fff", border: "1px solid #eef0f5", borderRadius: 14, padding: 20, cursor: "pointer", textAlign: "left", boxShadow: "0 0 2rem 0 rgba(136,152,170,.12)", display: "flex", flexDirection: "column", gap: 12 }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div style={{ fontSize: 30 }}>{s.icon || "🔌"}</div>
                <Led color={status.color} />
              </div>
              <div>
                <div style={{ fontWeight: 700, color: "#32325d", fontSize: 15 }}>{s.name.replace(/ \(.*\)$/, "")}</div>
                <div style={{ fontSize: 12, color: status.color, fontWeight: 600, marginTop: 2 }}>{status.label}</div>
              </div>
              <div style={{ fontSize: 11, color: "#8898aa" }}>{(s.name.match(/\((.*)\)$/) || [])[1] || "serviço de dados"} · {s.enabled ? "ativo" : "desativado"}</div>
            </button>
          );
        })}
      </div>
      {current && <ServiceModal service={current} onClose={() => setOpen(null)} onSaved={load} />}
    </div>
  );
}
