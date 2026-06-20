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
  { id: "marketplace", label: "Marketplace", icon: "🛒" },
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
  const [marketProducts, setMarketProducts] = useState([]);
  const [marketRules, setMarketRules] = useState(null);
  const [marketConfig, setMarketConfig] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [mlAuthUrl, setMlAuthUrl] = useState("");
  const [mlCode, setMlCode] = useState("");
  const [mlState, setMlState] = useState("");
  const [savingMp, setSavingMp] = useState(false);

  async function loadAll(force) {
    if (force) setRefreshing(true);
    try {
      const [badgeRes, kpiRes, payRes, fbRes, trendRes, agRes, grRes, mktProdsRes, mktRulesRes, mktConfigRes] = await Promise.allSettled([
        fetch(`${API}/methodology/badge`).then((r) => r.json()),
        fetch(`${API}/reports/kpis?days=1`).then((r) => r.json()),
        fetch(`${API}/payments?limit=20`).then((r) => r.json()),
        fetch(`${API}/feedback?limit=20`).then((r) => r.json()),
        fetch(`${API}/alerts/trends?limit=20`).then((r) => r.json()),
        fetch(`${API}/agenda?limit=20`).then((r) => r.json()),
        fetch(`${API}/groups`).then((r) => r.json()),
        fetch(`${API}/market/products?limit=50`).then((r) => r.json()),
        fetch(`${API}/market/rules`).then((r) => r.json()),
        fetch(`${API}/market/config`).then((r) => r.json()),
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
      if (mktProdsRes.status === "fulfilled") setMarketProducts(Array.isArray(mktProdsRes.value) ? mktProdsRes.value : []);
      if (mktRulesRes.status === "fulfilled") setMarketRules(mktRulesRes.value || null);
      if (mktConfigRes.status === "fulfilled") setMarketConfig(mktConfigRes.value || {});
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
      case "marketplace":
        return (
          <div>
            <h3 style={{ marginTop: 18, color: "#32325d" }}>Marketplace</h3>
            <p style={{ color: "#525f7f" }}>Produtos ranqueados por comissão, ticket e volume.</p>
            <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
              {marketProducts.length === 0 && <span style={{ color: "#8898aa" }}>Nenhum produto ranqueado ainda.</span>}
              {marketProducts.slice(0, 20).map((p, idx) => (
                <div key={idx} style={{ background: "#fff", padding: 14, borderRadius: 10, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)", display: "flex", justifyContent: "space-between", gap: 10 }}>
                  <div>
                    <div style={{ fontWeight: 700, color: "#32325d" }}>{p.title}</div>
                    <div style={{ fontSize: 12, color: "#8898aa" }}>{p.marketplace}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontWeight: 700, color: "#32325d" }}>R$ {Number(p.price ?? 0).toFixed(2)}</div>
                    <div style={{ fontSize: 12, color: "#8898aa" }}>Comissão {p.commission_pct ?? "—"}% • Score {p.score ? p.score.toFixed(2) : "—"}</div>
                  </div>
                </div>
              ))}
            </div>
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
          <MarketplaceConfigPanel
            config={marketConfig}
            mlAuthUrl={mlAuthUrl}
            onSave={async (payload) => {
              setSavingMp(true);
              await fetch(`${API}/market/config`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
              }).catch(() => {});
              setSavingMp(false);
              await loadAll(false);
            }}
            onMlLogin={async () => {
              const res = await fetch(`${API}/market/ml/auth-url`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ state: mlState || "state" }),
              }).then((r) => r.json());
              if (res?.ok) setMlAuthUrl(res.url);
            }}
          />
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

function MarketplaceConfigPanel({ config = {}, mlAuthUrl = "", onSave, onMlLogin }) {
  const marketplaces = config.marketplaces || {};

  function setPath(obj, pathParts, value) {
    const key = pathParts[0];
    if (!(key in obj)) obj[key] = {};
    if (pathParts.length === 1) {
      obj[key] = value;
      return;
    }
    setPath(obj[key], pathParts.slice(1), value);
  }

  const [form, setForm] = useState(() => {
    const clone = JSON.parse(JSON.stringify(marketplaces)) || {};
    // normalize lists -> comma string
    for (const mp of Object.values(clone)) {
      if (Array.isArray(mp.scope)) mp.scope = mp.scope.join(",");
      if (Array.isArray(mp.mode)) mp.mode = mp.mode[0] || "affiliate";
    }
    // back-compat for empty config
    if (!("mercadolivre" in clone)) clone.mercadolivre = { enabled: true, mode: "affiliate", scope: "national,international", values: {} };
    if (!("shopee" in clone)) clone.shopee = { enabled: true, mode: "affiliate", scope: "national,international", values: {} };
    if (!("amazon" in clone)) clone.amazon = { enabled: true, mode: "affiliate", scope: "international", values: {} };
    return clone;
  });

  const update = (marketplace, pathParts, value) => {
    const next = JSON.parse(JSON.stringify(form));
    setPath(next, [marketplace, ...pathParts], value);
    setForm(next);
  };

  const submit = async (marketplace) => {
    const payload = {
      marketplace,
      enabled: !!form[marketplace]?.enabled,
      mode: String(form[marketplace]?.mode || "affiliate"),
      scope: String(form[marketplace]?.scope || "national,international"),
      values: { ...(form[marketplace]?.values || {}) },
    };
    await onSave(payload);
  };

  return (
    <div>
      <h3 style={{ marginTop: 18, color: "#32325d" }}>Configurações</h3>
      <div style={{ display: "grid", gap: 18, marginTop: 12, gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
        {[
          { key: "mercadolivre", title: "Mercado Livre", fields: ["api_url","client_id","client_secret","access_token","refresh_token","redirect_uri","country","currency"], ml: true },
          { key: "shopee", title: "Shopee", fields: ["api_url","partner_id","partner_key","access_token","country","currency"] },
          { key: "amazon", title: "Amazon", fields: ["api_url","access_key","secret_key","associate_tag","region","country","currency"] },
        ].map(({ key, title, fields, ml }) => (
          <div key={key} style={{ background: "#fff", padding: 18, borderRadius: 10, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong style={{ color: "#32325d" }}>{title}</strong>
              <label style={{ display: "flex", alignItems: "center", gap: 8, color: "#525f7f", fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={!!form[key]?.enabled}
                  onChange={(e) => update(key, ["enabled"], e.target.checked)}
                />
                ativo
              </label>
            </div>
            <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
              <select
                value={form[key]?.mode || "affiliate"}
                onChange={(e) => update(key, ["mode"], e.target.value)}
              >
                <option value="affiliate">afiliado</option>
                <option value="dropshipping">dropshipping</option>
                <option value="both">ambos</option>
              </select>
              <input
                placeholder="scope: nacional/internacional"
                value={form[key]?.scope || ""}
                onChange={(e) => update(key, ["scope"], e.target.value)}
              />
              {fields.map((field) => (
                <input
                  key={field}
                  placeholder={field}
                  value={form[key]?.values?.[field] || ""}
                  onChange={(e) => {
                    const values = { ...(form[key]?.values || {}) };
                    values[field] = e.target.value;
                    update(key, ["values"], values);
                  }}
                />
              ))}
              {ml && (
                <button
                  onClick={onMlLogin}
                  style={{
                    marginTop: 8, background: "#5e72e4", color: "#fff", border: "none", borderRadius: 8, padding: "8px 12px", cursor: "pointer",
                  }}
                >
                  Abrir login Mercado Livre
                </button>
              )}
              {ml && mlAuthUrl && (
                <div style={{ fontSize: 12, color: "#525f7f", background: "#f6f9fc", padding: 10, borderRadius: 8 }}>
                  <a href={mlAuthUrl} target="_blank" rel="noreferrer">{mlAuthUrl}</a>
                </div>
              )}
              <button
                onClick={() => submit(key)}
                style={{
                  marginTop: 4, background: "#2dce89", color: "#fff", border: "none", borderRadius: 8, padding: "8px 12px", cursor: "pointer",
                }}
              >
                Salvar {title}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const inputStyle = {
  padding: "8px 10px",
  border: "1px solid #dee2e6",
  borderRadius: 8,
  background: "#f6f9fc",
  color: "#32325d",
  fontSize: 14,
  outline: "none",
};

const buttonStyle = {
  padding: "8px 12px",
  border: "none",
  borderRadius: 8,
  color: "#fff",
  fontSize: 14,
  cursor: "pointer",
};
