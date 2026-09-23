import React, { useEffect, useState } from "react";
import DailyOps from "./pages/DailyOps";
import VisaoGeral from "./pages/VisaoGeral";
import Portfolio from "./pages/Portfolio";
import Integrations from "./pages/Integrations";
import Login from "./pages/Login";
import { API_BASE, isLoggedIn, logout, setAuthExpiredHandler } from "./lib/apiClient";

const PAGES = [
  { id: "visao-geral", label: "Visão Geral", icon: "🏠" },
  { id: "daily-ops", label: "Daily Ops", icon: "🎯" },
  { id: "portfolio", label: "Portfólio", icon: "🗂️" },
  { id: "integracoes", label: "Integrações", icon: "🔌" },
];

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [page, setPage] = useState("daily-ops");

  useEffect(() => {
    setAuthExpiredHandler(() => setAuthed(false));
  }, []);

  const sidebarItem = (item) => (
    <button
      key={item.id}
      onClick={() => setPage(item.id)}
      style={{
        width: "100%",
        textAlign: "left",
        padding: "10px 16px",
        background: page === item.id ? "rgba(255,255,255,0.12)" : "transparent",
        color: "#fff",
        border: "none",
        cursor: "pointer",
        fontSize: 15,
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}
    >
      <span>{item.icon}</span>
      <span>{item.label}</span>
    </button>
  );

  const renderPage = () => {
    switch (page) {
      case "visao-geral":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Visão Geral</h3>
            <VisaoGeral />
          </div>
        );
      case "daily-ops":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Daily Ops</h3>
            <DailyOps />
          </div>
        );
      case "portfolio":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Portfólio</h3>
            <Portfolio />
          </div>
        );
      case "integracoes":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Integrações</h3>
            <Integrations />
          </div>
        );
      default:
        return null;
    }
  };

  if (!authed) {
    return <Login onLoggedIn={() => setAuthed(true)} />;
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "#f8f9fe" }}>
      <aside
        style={{
          width: 260,
          background: "#172b4d",
          color: "#fff",
          display: "flex",
          flexDirection: "column",
          padding: "18px 12px",
          position: "fixed",
          top: 0,
          bottom: 0,
          left: 0,
          zIndex: 50,
        }}
      >
        <div style={{ marginBottom: 22, padding: "0 10px", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 22 }}>🧲</span>
          <div style={{ fontWeight: 700, fontSize: 17 }}>marketTon</div>
        </div>

        <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {PAGES.map(sidebarItem)}
        </nav>

        <div style={{ marginTop: "auto", padding: "0 10px" }}>
          <div style={{ color: "#829ab1", fontSize: 12, marginBottom: 8 }}>Backend: {API_BASE}</div>
          <button
            onClick={() => {
              logout();
              setAuthed(false);
            }}
            style={{
              width: "100%",
              background: "rgba(255,255,255,0.08)",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              padding: "8px 10px",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            Sair
          </button>
        </div>
      </aside>

      <main style={{ marginLeft: 260, flex: 1, padding: "18px 22px" }}>
        <header
          style={{
            background: "#fff",
            borderRadius: 10,
            padding: "14px 18px",
            boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)",
            marginBottom: 18,
          }}
        >
          <div style={{ fontWeight: 600, color: "#32325d" }}>Painel marketTon</div>
        </header>

        {renderPage()}
      </main>
    </div>
  );
}
