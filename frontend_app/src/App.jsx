import React, { useEffect, useMemo, useState } from "react";

const API = "http://127.0.0.1:8000";

const AGENTS = [
  {
    id: "master",
    name: "Master",
    role: "Coordenador",
    description: "Coordena todo o ciclo",
    color: "#5e72e4",
    icon: "🎯",
  },
  {
    id: "trend_hunter",
    name: "Trend Hunter",
    role: "Tendências",
    description: "Captura tendências de mercado",
    color: "#11cdef",
    icon: "📈",
  },
  {
    id: "product_hunter",
    name: "Product Hunter",
    role: "Produtos",
    description: "Encontra produtos vencedores",
    color: "#2dce89",
    icon: "🎁",
  },
  {
    id: "copy_chief",
    name: "Copy Chief",
    role: "Copy",
    description: "Cria copys diretas e vendedoras",
    color: "#fb6340",
    icon: "✍️",
  },
  {
    id: "marketplace_manager",
    name: "Marketplace Manager",
    role: "Marketplaces",
    description: "Gerencia publicações",
    color: "#f5365c",
    icon: "🛒",
  },
  {
    id: "growth_analyst",
    name: "Growth Analyst",
    role: "Crescimento",
    description: "Analisa métricas e sugere ajustes",
    color: "#f6c944",
    icon: "📊",
  },
];

const PAGES = [
  { id: "visao-geral", label: "Visão Geral", icon: "🏠" },
  { id: "agentes", label: "Agentes", icon: "🤖" },
  { id: "produtos", label: "Produtos", icon: "📦" },
  { id: "copys", label: "Copys", icon: "✍️" },
  { id: "feedbacks", label: "Feedbacks", icon: "💬" },
  { id: "agenda", label: "Agenda", icon: "📅" },
  { id: "grupos", label: "Grupos", icon: "👥" },
  { id: "configuracoes", label: "Configurações", icon: "⚙️" },
];

function fmtMoney(n) {
  const v = typeof n === "number" ? n : Number(n || 0);
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtDateTime(v) {
  if (!v) return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString("pt-BR");
}

function statusChip(s) {
  const base = {
    padding: "4px 10px",
    borderRadius: 999,
    fontSize: 12,
    color: "#fff",
    background: "#525f7f",
    display: "inline-block",
  };
  const map = {
    scheduled: "#5e72e4",
    published: "#2dce89",
    failed: "#f5365c",
    active: "#2dce89",
    blocked: "#fb6340",
    paused: "#f6c944",
    muted: "#8898aa",
  };
  return { ...base, background: map[s] || base.background };
}

function rowHover() {
  return {
    ":hover": { background: "#f6f9fc" },
  };
}

export default function App() {
  const [page, setPage] = useState("visao-geral");
  const [badge, setBadge] = useState(null);
  const [dailyTarget, setDailyTarget] = useState(1);
  const [kpi, setKpi] = useState(null);
  const [payments, setPayments] = useState([]);
  const [feedbacks, setFeedbacks] = useState([]);
  const [trends, setTrends] = useState([]);
  const [agenda, setAgenda] = useState([]);
  const [groups, setGroups] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  async function loadAll(force) {
    if (force) setRefreshing(true);
    try {
      const [badgeRes, kpiRes, payRes, fbRes, trendRes, agRes, grRes] = await Promise.allSettled([
        fetch(`${API}/methodology/badge`).then((r) => r.json()),
        fetch(`${API}/reports/kpis?days=1`).then((r) => r.json()),
        fetch(`${API}/payments?limit=20`).then((r) => r.json()),
        fetch(`${API}/feedback?limit=20`).then((r) => r.json()),
        fetch(`${API}/alerts/trends?limit=20`).then((r) => r.json()),
        fetch(`${API}/agenda?limit=20`).then((r) => r.json()),
        fetch(`${API}/groups`).then((r) => r.json()),
      ]);
      if (badgeRes.status === "fulfilled") {
        setBadge(badgeRes.value.badge);
        setDailyTarget(badgeRes.value.daily_sales_target ?? 1);
      }
      if (kpiRes.status === "fulfilled") setKpi(kpiRes.value);
      if (payRes.status === "fulfilled") setPayments(Array.isArray(payRes.value) ? payRes.value : []);
      if (fbRes.status === "fulfilled") setFeedbacks(Array.isArray(fbRes.value) ? fbRes.value : []);
      if (trendRes.status === "fulfilled") setTrends(Array.isArray(trendRes.value) ? trendRes.value : []);
      if (agRes.status === "fulfilled") setAgenda(Array.isArray(agRes.value) ? agRes.value : []);
      if (grRes.status === "fulfilled") setGroups(Array.isArray(grRes.value) ? grRes.value : []);
    } catch (e) {
      // silent fallback
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    loadAll(true);
    const id = setInterval(() => loadAll(false), 15000);
    return () => clearInterval(id);
  }, []);

  const todaySales = kpi?.orders ?? 0;
  const todayRevenue = kpi?.revenue ?? 0;
  const avgTicket = kpi?.ticket_average ?? 0;
  const metaFalta = Math.max(0, (dailyTarget || 1) - todaySales);

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

  function renderCards() {
    return (
      <div className="row" style={{ marginTop: 14 }}>
        {[
          { label: "Vendas hoje", value: todaySales, color: "#2dce89", note: metaFalta > 0 ? `faltam ${metaFalta} para a meta` : "meta atingida" },
          { label: "Receita hoje (R$)", value: fmtMoney(todayRevenue), color: "#5e72e4" },
          { label: "Ticket médio (R$)", value: fmtMoney(avgTicket), color: "#11cdef" },
          { label: "Meta diária", value: String(dailyTarget), color: "#fb6340", note: "1 venda/dia mínimo" },
        ].map((kpiItem) => (
          <div className="col-xl-3 col-lg-6" key={kpiItem.label}>
            <div
              style={{
                background: "#fff",
                borderRadius: 10,
                padding: 18,
                boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)",
                borderLeft: `4px solid ${kpiItem.color}`,
              }}
            >
              <div style={{ fontSize: 12, color: "#8898aa", textTransform: "uppercase", letterSpacing: 1 }}>{kpiItem.label}</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: "#32325d", marginTop: 4 }}>{kpiItem.value}</div>
              {kpiItem.note && (
                <div style={{ fontSize: 12, color: "#525f7f", marginTop: 6 }}>{kpiItem.note}</div>
              )}
            </div>
          </div>
        ))}
      </div>
    );
  }

  function renderPayments() {
    return (
      <div className="card" style={{ marginTop: 18, background: "#fff", borderRadius: 10, padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h5 style={{ margin: 0, color: "#32325d" }}>Vendas recentes</h5>
          <span style={{ fontSize: 12, color: "#8898aa" }}>Fonte: /payments</span>
        </div>
        <div style={{ marginTop: 10 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "8px 4px", color: "#525f7f", fontSize: 12 }}>ID</th>
                <th style={{ textAlign: "left", padding: "8px 4px", color: "#525f7f", fontSize: 12 }}>Usuário</th>
                <th style={{ textAlign: "right", padding: "8px 4px", color: "#525f7f", fontSize: 12 }}>Valor</th>
                <th style={{ textAlign: "left", padding: "8px 4px", color: "#525f7f", fontSize: 12 }}>Data</th>
              </tr>
            </thead>
            <tbody>
              {payments.slice(0, 10).map((p) => (
                <tr key={p.id ?? p.user_id}>
                  <td style={{ padding: "8px 4px", borderTop: "1px solid #e9ecef", fontSize: 13 }}>{p.id ?? "—"}</td>
                  <td style={{ padding: "8px 4px", borderTop: "1px solid #e9ecef", fontSize: 13 }}>{p.username ?? p.user_id ?? "—"}</td>
                  <td style={{ padding: "8px 4px", borderTop: "1px solid #e9ecef", fontSize: 13, textAlign: "right" }}>{fmtMoney(p.amount)}</td>
                  <td style={{ padding: "8px 4px", borderTop: "1px solid #e9ecef", fontSize: 13 }}>{fmtDateTime(p.created_at)}</td>
                </tr>
              ))}
              {payments.length === 0 && (
                <tr>
                  <td colSpan={4} style={{ padding: "10px 4px", borderTop: "1px solid #e9ecef", fontSize: 13, color: "#8898aa" }}>
                    Nenhuma venda registrada ainda.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  function renderTrends() {
    return (
      <div className="card" style={{ marginTop: 18, background: "#fff", borderRadius: 10, padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h5 style={{ margin: 0, color: "#32325d" }}>Alertas de tendência</h5>
          <span style={{ fontSize: 12, color: "#8898aa" }}>Fonte: /alerts/trends</span>
        </div>
        <div style={{ marginTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
          {trends.slice(0, 12).map((t) => (
            <span
              key={t.id ?? t.keyword}
              style={{
                background: "#eef2ff",
                color: "#32325d",
                border: "1px solid #e9ecef",
                borderRadius: 12,
                padding: "8px 12px",
                fontSize: 12,
              }}
            >
              {t.keyword ?? t.topic ?? "trend"}{" "}
              {typeof t.score === "number" && <span style={{ color: "#5e72e4" }}>{t.score.toFixed(1)}</span>}
            </span>
          ))}
          {trends.length === 0 && (
            <span style={{ fontSize: 12, color: "#8898aa" }}>Sem alertas no momento.</span>
          )}
        </div>
      </div>
    );
  }

  function renderAgenda() {
    return (
      <div className="card" style={{ marginTop: 18, background: "#fff", borderRadius: 10, padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h5 style={{ margin: 0, color: "#32325d" }}>Agenda</h5>
          <span style={{ fontSize: 12, color: "#8898aa" }}>Fonte: /agenda</span>
        </div>
        <ul style={{ marginTop: 10, paddingLeft: 18, color: "#525f7f", fontSize: 13 }}>
          {agenda.length === 0 && <li>Nenhum item.</li>}
          {agenda.map((a) => (
            <li key={a.id ?? a.when_date} style={{ marginBottom: 6 }}>
              {a.title ?? a.description ?? "Item"} • {fmtDateTime(a.when_date)}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  function renderGroups() {
    return (
      <div className="card" style={{ marginTop: 18, background: "#fff", borderRadius: 10, padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h5 style={{ margin: 0, color: "#32325d" }}>Grupos</h5>
          <span style={{ fontSize: 12, color: "#8898aa" }}>Fonte: /groups</span>
        </div>
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {groups.length === 0 && <span style={{ fontSize: 12, color: "#8898aa" }}>Sem grupos cadastrados.</span>}
          {groups.map((g) => (
            <span key={g.group_id} style={{ ...statusChip(g.status) }}>
              {g.group_name ?? g.group_id} • {g.status ?? "—"}
            </span>
          ))}
        </div>
      </div>
    );
  }

  function renderFeedbacks() {
    return (
      <div className="card" style={{ marginTop: 18, background: "#fff", borderRadius: 10, padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h5 style={{ margin: 0, color: "#32325d" }}>Feedbacks</h5>
          <span style={{ fontSize: 12, color: "#8898aa" }}>Fonte: /feedback</span>
        </div>
        <div style={{ marginTop: 10 }}>
          {feedbacks.length === 0 && <span style={{ fontSize: 12, color: "#8898aa" }}>Nenhum feedback.</span>}
          {feedbacks.slice(0, 8).map((f) => (
            <div key={f.id} style={{ padding: "10px 0", borderTop: "1px solid #f6f9fc" }}>
              <div style={{ fontSize: 13, color: "#32325d" }}>{f.text ?? "(sem texto)"}</div>
              <div style={{ fontSize: 12, color: "#8898aa", marginTop: 4 }}>
                {f.username ?? f.user_id ?? "—"} • {f.sentiment ?? "—"} • {fmtDateTime(f.created_at)}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const renderPage = () => {
    switch (page) {
      case "visao-geral":
        return (
          <div>
            {renderCards()}
            {renderPayments()}
            {renderTrends()}
            {renderAgenda()}
            {renderGroups()}
          </div>
        );
      case "agentes":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Agentes</h3>
            <div className="row" style={{ marginTop: 12 }}>
              {AGENTS.map((a) => (
                <div className="col-lg-4 col-md-6" key={a.id}>
                  <div
                    style={{
                      background: "#fff",
                      borderRadius: 10,
                      padding: 18,
                      boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)",
                    }}
                  >
                    <div style={{ fontSize: 28 }}>{a.icon}</div>
                    <h6 style={{ color: a.color, marginTop: 8 }}>{a.name}</h6>
                    <div style={{ color: "#525f7f", fontSize: 13 }}>{a.role}</div>
                    <div style={{ color: "#525f7f", fontSize: 13, marginTop: 4 }}>{a.description}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      case "produtos":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Produtos</h3>
            <p style={{ color: "#525f7f" }}>Conectado ao Product Hunter — utilize o backend para popular registros.</p>
          </div>
        );
      case "copys":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Copys</h3>
            <p style={{ color: "#525f7f" }}>Utilize os dados aprovados pelos agentes para gerar publicações.</p>
          </div>
        );
      case "feedbacks":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Feedbacks</h3>
            {renderFeedbacks()}
          </div>
        );
      case "agenda":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Agenda</h3>
            {renderAgenda()}
          </div>
        );
      case "grupos":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Grupos</h3>
            {renderGroups()}
          </div>
        );
      case "configuracoes":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Configurações</h3>
            <div style={{ background: "#fff", padding: 18, borderRadius: 10, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)" }}>
              <p style={{ color: "#525f7f" }}>
                Badge atual: <strong>{badge ?? "—"}</strong> • Meta diária: {dailyTarget} venda(s).
              </p>
              <p style={{ color: "#525f7f" }}>Atualização automática a cada 15s enquanto o app estiver aberto.</p>
            </div>
          </div>
        );
      default:
        return null;
    }
  };

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
          <div>
            <div style={{ fontWeight: 700, fontSize: 17 }}>marketTon</div>
            <div style={{ fontSize: 12, color: "#c2c9d6", marginTop: 2 }}>
              Badge: <strong>{badge ?? "—"}</strong>
            </div>
          </div>
        </div>

        <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {PAGES.map(sidebarItem)}
        </nav>

        <div style={{ marginTop: "auto", padding: "0 10px", color: "#829ab1", fontSize: 12 }}>
          Backend online • {API}
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
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <div style={{ fontWeight: 600, color: "#32325d" }}>Painel marketTon</div>
            <div style={{ color: "#525f7f", fontSize: 13 }}>Objetivo do dia: {dailyTarget} venda(s)</div>
          </div>
          <div
            style={{
              background: "#5e72e4",
              color: "#fff",
              borderRadius: 999,
              padding: "6px 14px",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            {badge ? ` Badge: ${badge}` : " Badge: —"}
          </div>
        </header>

        {renderPage()}
      </main>
    </div>
  );
}
