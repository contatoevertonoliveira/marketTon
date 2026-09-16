import React, { useState } from "react";
import { login } from "../lib/apiClient";

const inputStyle = {
  display: "block",
  width: "100%",
  padding: "10px 12px",
  marginBottom: 10,
  border: "1px solid #dee2e6",
  borderRadius: 8,
  fontSize: 14,
  boxSizing: "border-box",
};

const buttonStyle = {
  width: "100%",
  padding: "10px 12px",
  background: "#5e72e4",
  color: "#fff",
  border: "none",
  borderRadius: 8,
  fontSize: 14,
  cursor: "pointer",
};

export default function Login({ onLoggedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username, password);
      onLoggedIn();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#172b4d",
      }}
    >
      <form
        onSubmit={submit}
        style={{ background: "#fff", padding: 32, borderRadius: 12, width: 320, boxShadow: "0 0 3rem rgba(0,0,0,.25)" }}
      >
        <h4 style={{ marginTop: 0, marginBottom: 2, color: "#32325d" }}>marketTon</h4>
        <p style={{ color: "#8898aa", fontSize: 13, marginTop: 0, marginBottom: 18 }}>Affiliate Intelligence System</p>
        <input
          placeholder="usuário"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          style={inputStyle}
          autoFocus
        />
        <input
          placeholder="senha"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={inputStyle}
        />
        {error && <div style={{ color: "#f5365c", fontSize: 12, marginBottom: 10 }}>{error}</div>}
        <button disabled={busy} style={{ ...buttonStyle, opacity: busy ? 0.7 : 1 }}>
          {busy ? "entrando..." : "Entrar"}
        </button>
      </form>
    </div>
  );
}
