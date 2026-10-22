import React, { useEffect, useState } from "react";
import { getJSON, patchJSON, postJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 22, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", marginBottom: 18 };
const input = {
  padding: "9px 11px",
  border: "1px solid #dee2e6",
  borderRadius: 8,
  background: "#f6f9fc",
  color: "#32325d",
  fontSize: 13,
  width: "100%",
  boxSizing: "border-box",
};
const label = { fontSize: 12, color: "#8898aa", marginBottom: 4 };
const primary = { background: "#5e72e4", color: "#fff", border: "none", borderRadius: 8, padding: "9px 18px", fontSize: 13, fontWeight: 600, cursor: "pointer" };

const ROLE_LABELS = { admin: "Administrador", manager: "Gerente", operator: "Operador", viewer: "Leitor", bot: "Agente (Claude)" };

function Field({ title, children, hint }) {
  return (
    <div>
      <div style={label}>{title}</div>
      {children}
      {hint && <div style={{ fontSize: 11, color: "#adb5bd", marginTop: 3 }}>{hint}</div>}
    </div>
  );
}

function Notice({ notice }) {
  if (!notice) return null;
  const ok = notice.type === "ok";
  return (
    <div style={{ fontSize: 12, padding: "9px 12px", borderRadius: 8, background: ok ? "#e5faf1" : "#fef1f4", color: ok ? "#1a7a54" : "#c31e3f" }}>
      {notice.text}
    </div>
  );
}

function ProfileData({ me, onSaved }) {
  const [form, setForm] = useState({ full_name: me.full_name || "", email: me.email || "", phone: me.phone || "", company: me.company || "" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);

  async function save() {
    setBusy(true);
    setNotice(null);
    try {
      const data = await patchJSON("/auth/me", form);
      onSaved(data);
      setNotice({ type: "ok", text: "Dados salvos." });
    } catch (e) {
      setNotice({ type: "err", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return (
    <div style={card}>
      <h6 style={{ margin: "0 0 4px", color: "#32325d" }}>Dados do perfil</h6>
      <div style={{ fontSize: 12, color: "#8898aa", marginBottom: 16 }}>Informações de contato. Todas são opcionais.</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Field title="Nome completo"><input style={input} value={form.full_name} onChange={set("full_name")} maxLength={128} /></Field>
        <Field title="E-mail"><input style={input} type="email" value={form.email} onChange={set("email")} maxLength={255} /></Field>
        <Field title="Telefone"><input style={input} value={form.phone} onChange={set("phone")} maxLength={32} /></Field>
        <Field title="Empresa / projeto"><input style={input} value={form.company} onChange={set("company")} maxLength={128} /></Field>
      </div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 16 }}>
        <button style={primary} onClick={save} disabled={busy}>{busy ? "Salvando…" : "Salvar dados"}</button>
        <Notice notice={notice} />
      </div>
    </div>
  );
}

function UsernameCard({ me, onRelogin }) {
  const [username, setUsername] = useState(me.username);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const changed = username.trim() !== me.username;

  async function save() {
    if (!window.confirm("Ao mudar o nome de usuário você será desconectado e precisará entrar de novo com o novo nome. Continuar?")) return;
    setBusy(true);
    setNotice(null);
    try {
      const data = await patchJSON("/auth/me", { username });
      if (data.relogin_required) onRelogin("Nome de usuário alterado. Entre de novo com o novo nome.");
    } catch (e) {
      setNotice({ type: "err", text: e.message });
      setBusy(false);
    }
  }

  return (
    <div style={card}>
      <h6 style={{ margin: "0 0 4px", color: "#32325d" }}>Nome de usuário</h6>
      <div style={{ fontSize: 12, color: "#8898aa", marginBottom: 16 }}>Usado para entrar no sistema. De 3 a 64 caracteres: letras, números, ponto, hífen ou sublinhado.</div>
      <div style={{ maxWidth: 360 }}>
        <Field title="Usuário"><input style={input} value={username} onChange={(e) => setUsername(e.target.value)} maxLength={64} autoComplete="username" /></Field>
      </div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 16 }}>
        <button style={{ ...primary, opacity: changed ? 1 : 0.5 }} onClick={save} disabled={busy || !changed}>
          {busy ? "Alterando…" : "Alterar usuário"}
        </button>
        <Notice notice={notice} />
      </div>
    </div>
  );
}

function PasswordCard({ onRelogin }) {
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save() {
    setNotice(null);
    if (form.next !== form.confirm) {
      setNotice({ type: "err", text: "A confirmação não é igual à nova senha." });
      return;
    }
    setBusy(true);
    try {
      await postJSON("/auth/me/password", { current_password: form.current, new_password: form.next });
      onRelogin("Senha alterada. Entre de novo com a nova senha.");
    } catch (e) {
      setNotice({ type: "err", text: e.message });
      setBusy(false);
    }
  }

  return (
    <div style={card}>
      <h6 style={{ margin: "0 0 4px", color: "#32325d" }}>Alterar senha</h6>
      <div style={{ fontSize: 12, color: "#8898aa", marginBottom: 16 }}>
        Mínimo de 10 caracteres, misturando letras e números. Ao trocar, todas as sessões abertas são encerradas. Cinco
        tentativas erradas da senha atual bloqueiam a conta por 15 minutos.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
        <Field title="Senha atual"><input style={input} type="password" value={form.current} onChange={set("current")} autoComplete="current-password" /></Field>
        <Field title="Nova senha"><input style={input} type="password" value={form.next} onChange={set("next")} autoComplete="new-password" /></Field>
        <Field title="Confirmar nova senha"><input style={input} type="password" value={form.confirm} onChange={set("confirm")} autoComplete="new-password" /></Field>
      </div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 16 }}>
        <button style={primary} onClick={save} disabled={busy || !form.current || !form.next}>{busy ? "Alterando…" : "Alterar senha"}</button>
        <Notice notice={notice} />
      </div>
    </div>
  );
}

function UsersAdmin({ me }) {
  const [users, setUsers] = useState(null);
  const [roles, setRoles] = useState(["admin", "manager", "operator", "viewer"]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ username: "", password: "", role: "viewer", email: "" });
  const [notice, setNotice] = useState(null);

  function load() {
    getJSON("/auth/users").then(setUsers).catch((e) => setError(e.message));
  }
  useEffect(() => {
    load();
    getJSON("/auth/permissions").then((d) => d.roles && setRoles(d.roles)).catch(() => {});
  }, []);

  async function create() {
    setNotice(null);
    try {
      await postJSON("/auth/users", form);
      setForm({ username: "", password: "", role: "viewer", email: "" });
      setNotice({ type: "ok", text: "Usuário criado." });
      load();
    } catch (e) {
      setNotice({ type: "err", text: e.message });
    }
  }

  async function patch(user, body, okText) {
    setNotice(null);
    try {
      await patchJSON(`/auth/users/${user.id}`, body);
      setNotice({ type: "ok", text: okText });
      load();
    } catch (e) {
      setNotice({ type: "err", text: e.message });
    }
  }

  function resetPassword(user) {
    const pwd = window.prompt(`Nova senha para "${user.username}" (mín. 10 caracteres, letras e números). As sessões dele serão encerradas.`);
    if (pwd) patch(user, { password: pwd }, `Senha de ${user.username} redefinida.`);
  }

  if (error) return <p style={{ color: "#f5365c" }}>{error}</p>;
  if (!users) return <p style={{ color: "#8898aa" }}>Carregando...</p>;

  return (
    <div>
      <div style={card}>
        <h6 style={{ margin: "0 0 14px", color: "#32325d" }}>Novo usuário</h6>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 160px", gap: 12 }}>
          <Field title="Usuário"><input style={input} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></Field>
          <Field title="Senha inicial"><input style={input} type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" /></Field>
          <Field title="E-mail (opcional)"><input style={input} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field title="Papel">
            <select style={input} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {roles.map((r) => <option key={r} value={r}>{ROLE_LABELS[r] || r}</option>)}
            </select>
          </Field>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 14 }}>
          <button style={primary} onClick={create} disabled={!form.username || !form.password}>Criar usuário</button>
          <Notice notice={notice} />
        </div>
      </div>

      <div style={card}>
        <h6 style={{ margin: "0 0 12px", color: "#32325d" }}>Usuários ({users.length})</h6>
        {users.map((u) => {
          const self = u.username === me.username;
          return (
            <div key={u.id} style={{ display: "grid", gridTemplateColumns: "1.2fr 1.4fr 150px 90px auto", gap: 12, alignItems: "center", padding: "10px 0", borderTop: "1px solid #f0f2f7", fontSize: 13 }}>
              <div>
                <strong style={{ color: "#32325d" }}>{u.username}</strong>
                {self && <span style={{ marginLeft: 6, fontSize: 10, color: "#5e72e4" }}>você</span>}
                <div style={{ fontSize: 11, color: "#8898aa" }}>{u.full_name || ""}</div>
              </div>
              <div style={{ color: "#525f7f", fontSize: 12 }}>
                {u.email || "—"}
                <div style={{ fontSize: 11, color: "#adb5bd" }}>último acesso: {u.last_login_at ? new Date(u.last_login_at).toLocaleString("pt-BR") : "nunca"}</div>
              </div>
              <select
                style={{ ...input, padding: "6px 8px" }}
                value={u.role}
                disabled={self}
                title={self ? "Você não pode rebaixar a própria conta" : ""}
                onChange={(e) => patch(u, { role: e.target.value }, `Papel de ${u.username} alterado.`)}
              >
                {roles.map((r) => <option key={r} value={r}>{ROLE_LABELS[r] || r}</option>)}
              </select>
              <span style={{ fontSize: 11, fontWeight: 700, color: u.is_active ? "#1a7a54" : "#c31e3f" }}>{u.is_active ? "ativo" : "desativado"}</span>
              <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                <button style={{ ...primary, background: "#8898aa", padding: "6px 10px", fontSize: 12 }} onClick={() => resetPassword(u)}>Redefinir senha</button>
                {!self && (
                  <button
                    style={{ ...primary, background: u.is_active ? "#f5365c" : "#2dce89", padding: "6px 10px", fontSize: 12 }}
                    onClick={() => patch(u, { is_active: !u.is_active }, `${u.username} ${u.is_active ? "desativado" : "ativado"}.`)}
                  >
                    {u.is_active ? "Desativar" : "Ativar"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function Profile({ onRelogin }) {
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState("perfil");
  const [error, setError] = useState("");

  useEffect(() => {
    getJSON("/auth/me").then(setMe).catch((e) => setError(e.message));
  }, []);

  if (error) return <p style={{ color: "#f5365c" }}>Não foi possível carregar o perfil ({error}).</p>;
  if (!me) return <p style={{ color: "#8898aa" }}>Carregando...</p>;

  const isAdmin = me.permissions?.includes("users.manage");
  const tabs = [["perfil", "Meu perfil"], ...(isAdmin ? [["usuarios", "Usuários"]] : [])];

  return (
    <div>
      <div style={{ ...card, display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ width: 52, height: 52, borderRadius: "50%", background: "linear-gradient(135deg,#5e72e4,#825ee4)", color: "#fff", display: "grid", placeItems: "center", fontSize: 22, fontWeight: 700 }}>
          {(me.full_name || me.username).slice(0, 1).toUpperCase()}
        </div>
        <div>
          <div style={{ fontWeight: 700, color: "#32325d", fontSize: 16 }}>{me.full_name || me.username}</div>
          <div style={{ fontSize: 12, color: "#8898aa" }}>
            {ROLE_LABELS[me.role] || me.role} · @{me.username}
            {me.last_login_at && ` · último acesso ${new Date(me.last_login_at).toLocaleString("pt-BR")}`}
          </div>
        </div>
      </div>

      {tabs.length > 1 && (
        <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e9ecef", marginBottom: 18 }}>
          {tabs.map(([id, name]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              style={{ border: "none", background: "transparent", padding: "10px 16px", fontSize: 14, fontWeight: tab === id ? 700 : 500, color: tab === id ? "#5e72e4" : "#8898aa", borderBottom: tab === id ? "2px solid #5e72e4" : "2px solid transparent", cursor: "pointer" }}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      {tab === "perfil" ? (
        <>
          <ProfileData me={me} onSaved={(data) => setMe((prev) => ({ ...prev, ...data }))} />
          <UsernameCard me={me} onRelogin={onRelogin} />
          <PasswordCard onRelogin={onRelogin} />
        </>
      ) : (
        <UsersAdmin me={me} />
      )}
    </div>
  );
}
