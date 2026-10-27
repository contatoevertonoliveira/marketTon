import React, { useEffect, useState } from "react";
import VisaoGeral from "./pages/VisaoGeral";
import Dashboard from "./pages/Dashboard";
import Portfolio from "./pages/Portfolio";
import Produtos from "./pages/Produtos";
import Integrations from "./pages/Integrations";
import TrendingAbroad from "./pages/TrendingAbroad";
import Opportunities from "./pages/Opportunities";
import Profile from "./pages/Profile";
import Vitrine from "./pages/Vitrine";
import Criativos from "./pages/Criativos";
import Relatorios from "./pages/Relatorios";
import Financeiro from "./pages/Financeiro";
import AgentSwitch from "./components/AgentSwitch";
import AgentChat from "./pages/AgentChat";
import Login from "./pages/Login";
import { API_BASE, getJSON, isLoggedIn, logout, setAuthExpiredHandler } from "./lib/apiClient";

const PAGES = [
  { id: "visao-geral", label: "Visão Geral", icon: "🏠" },
  { id: "daily-ops", label: "Daily Ops", icon: "🎯" },
  { id: "financeiro", label: "Financeiro", icon: "💰" },
  { id: "produtos", label: "Produtos", icon: "📦" },
  { id: "portfolio", label: "Portfólio", icon: "🗂️" },
  { id: "oportunidades", label: "Oportunidades de Busca", icon: "🔥" },
  { id: "tendencias", label: "Tendências Internacionais", icon: "🌎" },
  { id: "vitrine", label: "Vitrine (loja)", icon: "🛍️" },
  { id: "criativos", label: "Criativos e anúncios", icon: "🎬" },
  { id: "agente", label: "Agente (chat)", icon: "🤖" },
  { id: "relatorios", label: "Relatórios do agente", icon: "📋" },
  { id: "integracoes", label: "Integrações", icon: "🔌" },
  { id: "perfil", label: "Perfil", icon: "👤" },
];

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [page, setPage] = useState("daily-ops");
  const [loginNotice, setLoginNotice] = useState("");
  const [chatCounts, setChatCounts] = useState(null);

  useEffect(() => {
    setAuthExpiredHandler(() => setAuthed(false));
  }, []);

  // Aviso no menu: mensagens, alertas de venda e pedidos do agente ainda não vistos.
  useEffect(() => {
    if (!authed) return undefined;
    const poll = () => getJSON("/agent/chat?limit=1").then((d) => setChatCounts(d.counts)).catch(() => {});
    poll();
    const id = setInterval(poll, 30000);
    return () => clearInterval(id);
  }, [authed]);

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
      {item.id === "agente" && chatCounts && chatCounts.unread_for_user + chatCounts.open_requests > 0 && (
        <span style={{ marginLeft: "auto", background: "#f5365c", color: "#fff", borderRadius: 999, fontSize: 11, fontWeight: 700, padding: "1px 7px" }}>
          {chatCounts.unread_for_user + chatCounts.open_requests}
        </span>
      )}
    </button>
  );

  const renderPage = () => {
    switch (page) {
      case "visao-geral":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Visão Geral</h3>
            <Dashboard />
          </div>
        );
      case "daily-ops":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Daily Ops</h3>
            <VisaoGeral />
          </div>
        );
      case "produtos":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Produtos vinculados</h3>
            <Produtos />
          </div>
        );
      case "portfolio":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Portfólio</h3>
            <Portfolio />
          </div>
        );
      case "oportunidades":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Oportunidades de Busca</h3>
            <Opportunities />
          </div>
        );
      case "tendencias":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Tendências Internacionais</h3>
            <TrendingAbroad />
          </div>
        );
      case "integracoes":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Integrações</h3>
            <Integrations />
          </div>
        );
      case "criativos":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Criativos e anúncios</h3>
            <Criativos />
          </div>
        );
      case "financeiro":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Financeiro</h3>
            <Financeiro />
          </div>
        );
      case "relatorios":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Relatórios do agente</h3>
            <Relatorios />
          </div>
        );
      case "vitrine":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Vitrine pública: Mural na Web</h3>
            <Vitrine />
          </div>
        );
      case "agente":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Chat com o agente</h3>
            <AgentChat onCountsChange={setChatCounts} />
          </div>
        );
      case "perfil":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Perfil</h3>
            <Profile
              onRelogin={(message) => {
                logout();
                setLoginNotice(message);
                setAuthed(false);
              }}
            />
          </div>
        );
      default:
        return null;
    }
  };

  if (!authed) {
    return <Login notice={loginNotice} onLoggedIn={() => { setLoginNotice(""); setPage("daily-ops"); setAuthed(true); }} />;
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
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <div style={{ fontWeight: 600, color: "#32325d" }}>Painel marketTon</div>
          <AgentSwitch />
        </header>

        {renderPage()}
      </main>
    </div>
  );
}
