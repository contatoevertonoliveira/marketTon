import React, { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getJSON } from "../lib/apiClient";

const MARKETPLACES = {
  mercado_livre: { name: "Mercado Livre", color: "#5e72e4" },
  shopee: { name: "Shopee", color: "#ee4d2d" },
  amazon: { name: "Amazon", color: "#fb6340" },
  tiktok_shop: { name: "TikTok Shop", color: "#11cdef" },
  aliexpress: { name: "AliExpress", color: "#f6c944" },
};

const SCORE_BUCKETS = [
  { key: "0-20", min: 0, max: 20 },
  { key: "20-40", min: 20, max: 40 },
  { key: "40-60", min: 40, max: 60 },
  { key: "60-80", min: 60, max: 80 },
  { key: "80-100", min: 80, max: 101 },
];

const FUNNEL_STAGES = [
  { key: "Descoberta", states: ["DISCOVERED", "ANALYZING", "WATCHLIST"] },
  { key: "Recomendado", states: ["RECOMMENDED"] },
  { key: "Afiliação", states: ["AFFILIATION_PENDING", "AFFILIATED"] },
  { key: "Ativo", states: ["PORTFOLIO_ACTIVE", "CREATIVE_PENDING", "READY_TO_PUBLISH"] },
  { key: "Publicado", states: ["PUBLISHED", "MONITORING", "SCALING"] },
  { key: "Parado", states: ["OPTIMIZATION_REQUIRED", "PAUSED", "REMOVED"] },
];

const card = {
  background: "#fff",
  borderRadius: 12,
  padding: 18,
  boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)",
};

// Dados de exemplo — só pra visualizar a forma do gráfico com um catálogo
// maduro (e com marketplaces que ainda não foram ativados, como AliExpress,
// que nem existe no domínio do backend ainda). Nunca é confundido com dado
// real: todo lugar que usa isto mostra o aviso "dados de exemplo".
const MOCK = {
  products: [
    { marketplace: "mercado_livre", produtos: 340 },
    { marketplace: "shopee", produtos: 512 },
    { marketplace: "amazon", produtos: 128 },
    { marketplace: "aliexpress", produtos: 275 },
  ],
  scoreDistribution: [
    { bucket: "0-20", mercado_livre: 20, shopee: 30, amazon: 10, aliexpress: 40 },
    { bucket: "20-40", mercado_livre: 45, shopee: 70, amazon: 18, aliexpress: 60 },
    { bucket: "40-60", mercado_livre: 90, shopee: 140, amazon: 35, aliexpress: 80 },
    { bucket: "60-80", mercado_livre: 120, shopee: 180, amazon: 45, aliexpress: 70 },
    { bucket: "80-100", mercado_livre: 65, shopee: 92, amazon: 20, aliexpress: 25 },
  ],
  funnel: [
    { estado: "Descoberta", mercado_livre: 200, shopee: 300, amazon: 80, aliexpress: 150 },
    { estado: "Recomendado", mercado_livre: 60, shopee: 90, amazon: 25, aliexpress: 50 },
    { estado: "Afiliação", mercado_livre: 30, shopee: 55, amazon: 12, aliexpress: 30 },
    { estado: "Ativo", mercado_livre: 22, shopee: 38, amazon: 8, aliexpress: 20 },
    { estado: "Publicado", mercado_livre: 18, shopee: 25, amazon: 5, aliexpress: 15 },
    { estado: "Parado", mercado_livre: 10, shopee: 4, amazon: 3, aliexpress: 10 },
  ],
  commission: [
    { marketplace: "mercado_livre", estimada: 1450.5, confirmada: 980.2 },
    { marketplace: "shopee", estimada: 3200.75, confirmada: 2540.4 },
    { marketplace: "amazon", estimada: 610.0, confirmada: 300.0 },
    { marketplace: "aliexpress", estimada: 1780.3, confirmada: 1120.9 },
  ],
  salesOverTime: [
    { dia: "seg", mercado_livre: 4, shopee: 7, amazon: 1, aliexpress: 3 },
    { dia: "ter", mercado_livre: 6, shopee: 9, amazon: 2, aliexpress: 5 },
    { dia: "qua", mercado_livre: 5, shopee: 12, amazon: 1, aliexpress: 4 },
    { dia: "qui", mercado_livre: 8, shopee: 15, amazon: 3, aliexpress: 6 },
    { dia: "sex", mercado_livre: 9, shopee: 18, amazon: 2, aliexpress: 8 },
    { dia: "sáb", mercado_livre: 12, shopee: 22, amazon: 4, aliexpress: 10 },
    { dia: "dom", mercado_livre: 10, shopee: 20, amazon: 3, aliexpress: 9 },
  ],
};

function useRealDashboardData(enabledMarketplaces) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!enabledMarketplaces || enabledMarketplaces.length === 0) return;
    let cancelled = false;

    Promise.all(
      enabledMarketplaces.map((slug) =>
        Promise.all([
          getJSON(`/catalog/products?marketplace=${slug}&limit=500`),
          getJSON(`/portfolio/items?marketplace=${slug}&limit=500`),
          getJSON(`/operations/daily?marketplace=${slug}&days=30`),
        ]).then(([products, items, daily]) => ({ slug, products, items, daily }))
      )
    )
      .then((perMarketplace) => {
        if (cancelled) return;

        const products = perMarketplace.map(({ slug, products }) => ({
          marketplace: slug,
          produtos: products.length,
        }));

        const scoreDistribution = SCORE_BUCKETS.map((bucket) => {
          const row = { bucket: bucket.key };
          for (const { slug, products } of perMarketplace) {
            row[slug] = products.filter((p) => {
              const score = p.scores?.OPPORTUNITY;
              return score != null && score >= bucket.min && score < bucket.max;
            }).length;
          }
          return row;
        });

        const funnel = FUNNEL_STAGES.map((stage) => {
          const row = { estado: stage.key };
          for (const { slug, items } of perMarketplace) {
            row[slug] = items.filter((i) => stage.states.includes(i.state)).length;
          }
          return row;
        });

        const commission = perMarketplace.map(({ slug, daily }) => ({
          marketplace: slug,
          estimada: daily.kpis?.commission_estimated ?? 0,
          confirmada: daily.kpis?.commission_confirmed ?? 0,
        }));

        setData({ products, scoreDistribution, funnel, commission, marketplaces: enabledMarketplaces });
        setError("");
      })
      .catch((e) => !cancelled && setError(e.message));

    return () => {
      cancelled = true;
    };
  }, [enabledMarketplaces?.join(",")]);

  return { data, error };
}

function ChartCard({ title, note, children }) {
  return (
    <div style={{ ...card, marginBottom: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h6 style={{ margin: 0, color: "#32325d" }}>{title}</h6>
        {note && <span style={{ fontSize: 11, color: "#8898aa" }}>{note}</span>}
      </div>
      <div style={{ width: "100%", height: 260, marginTop: 12 }}>
        <ResponsiveContainer>{children}</ResponsiveContainer>
      </div>
    </div>
  );
}

function marketplaceLabel(slug) {
  return MARKETPLACES[slug]?.name || slug;
}

function marketplaceColor(slug) {
  return MARKETPLACES[slug]?.color || "#8898aa";
}

export default function Dashboard() {
  const [useMock, setUseMock] = useState(false);
  const [enabled, setEnabled] = useState(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    getJSON("/marketplaces/credentials")
      .then((rows) => setEnabled(rows.filter((c) => c.enabled).map((c) => c.marketplace)))
      .catch((e) => setLoadError(e.message));
  }, []);

  const { data: realData, error: realError } = useRealDashboardData(useMock ? null : enabled);

  const active = useMock
    ? { ...MOCK, marketplaces: Object.keys(MOCK.products.reduce((a, p) => ((a[p.marketplace] = 1), a), {})) }
    : realData;

  const marketplaces = useMock ? MOCK.products.map((p) => p.marketplace) : enabled || [];

  return (
    <div>
      <div
        style={{
          ...card,
          marginBottom: 18,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <div>
          <strong style={{ color: "#32325d" }}>Fonte dos gráficos</strong>
          <div style={{ fontSize: 12, color: "#8898aa" }}>
            {useMock
              ? "Dados de exemplo — inclui marketplaces ainda não ativados, só para mostrar como o dashboard fica com um catálogo maduro."
              : "Dados reais do seu catálogo e portfólio, só dos marketplaces ativados em Integrações."}
          </div>
        </div>
        <div style={{ display: "flex", borderRadius: 999, background: "#f6f9fc", padding: 3 }}>
          <button
            onClick={() => setUseMock(false)}
            style={{
              border: "none",
              borderRadius: 999,
              padding: "7px 16px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              background: !useMock ? "#5e72e4" : "transparent",
              color: !useMock ? "#fff" : "#525f7f",
            }}
          >
            Dados reais
          </button>
          <button
            onClick={() => setUseMock(true)}
            style={{
              border: "none",
              borderRadius: 999,
              padding: "7px 16px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              background: useMock ? "#5e72e4" : "transparent",
              color: useMock ? "#fff" : "#525f7f",
            }}
          >
            Dados de exemplo
          </button>
        </div>
      </div>

      {loadError && <p style={{ color: "#f5365c" }}>Não foi possível carregar os marketplaces: {loadError}</p>}
      {!useMock && realError && <p style={{ color: "#f5365c" }}>Não foi possível carregar os dados reais: {realError}</p>}
      {!useMock && enabled && enabled.length === 0 && (
        <div style={{ ...card, fontSize: 13, color: "#8898aa" }}>
          Nenhum marketplace ativado em Integrações — ative pelo menos um para ver dados reais, ou troque pra
          "dados de exemplo" acima.
        </div>
      )}

      {active && marketplaces.length > 0 && (
        <>
          <ChartCard title="Produtos no catálogo por marketplace" note={useMock ? "exemplo" : "real"}>
            <BarChart data={active.products}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f2f7" />
              <XAxis dataKey="marketplace" tickFormatter={marketplaceLabel} tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
              <Tooltip labelFormatter={marketplaceLabel} />
              <Bar dataKey="produtos" radius={[6, 6, 0, 0]}>
                {active.products.map((row) => (
                  <Cell key={row.marketplace} fill={marketplaceColor(row.marketplace)} />
                ))}
              </Bar>
            </BarChart>
          </ChartCard>

          <ChartCard
            title="Distribuição do Opportunity Score"
            note="por faixa de pontuação, um produto pode ainda não ter score calculado"
          >
            <BarChart data={active.scoreDistribution}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f2f7" />
              <XAxis dataKey="bucket" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
              <Tooltip formatter={(v, name) => [v, marketplaceLabel(name)]} />
              <Legend formatter={marketplaceLabel} />
              {marketplaces.map((slug) => (
                <Bar key={slug} dataKey={slug} stackId="score" fill={marketplaceColor(slug)} radius={[4, 4, 0, 0]} />
              ))}
            </BarChart>
          </ChartCard>

          <ChartCard title="Funil de portfólio" note="quantos produtos em cada etapa do funil, por marketplace">
            <BarChart data={active.funnel} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f0f2f7" />
              <XAxis type="number" tick={{ fontSize: 12 }} allowDecimals={false} />
              <YAxis dataKey="estado" type="category" tick={{ fontSize: 12 }} width={80} />
              <Tooltip formatter={(v, name) => [v, marketplaceLabel(name)]} />
              <Legend formatter={marketplaceLabel} />
              {marketplaces.map((slug) => (
                <Bar key={slug} dataKey={slug} stackId="funnel" fill={marketplaceColor(slug)} />
              ))}
            </BarChart>
          </ChartCard>

          <ChartCard
            title="Comissão estimada x confirmada (30 dias)"
            note={useMock ? "exemplo" : "real — hoje deve estar zerado ou baixo, o sistema é novo"}
          >
            <BarChart data={active.commission}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f2f7" />
              <XAxis dataKey="marketplace" tickFormatter={marketplaceLabel} tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip labelFormatter={marketplaceLabel} formatter={(v) => `R$ ${Number(v).toFixed(2)}`} />
              <Legend />
              <Bar dataKey="estimada" fill="#f6c944" radius={[6, 6, 0, 0]} name="estimada" />
              <Bar dataKey="confirmada" fill="#2dce89" radius={[6, 6, 0, 0]} name="confirmada" />
            </BarChart>
          </ChartCard>

          {useMock && (
            <ChartCard title="Vendas por dia (últimos 7 dias)" note="exemplo — ainda não temos série real por dia">
              <LineChart data={MOCK.salesOverTime}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f2f7" />
                <XAxis dataKey="dia" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                <Tooltip formatter={(v, name) => [v, marketplaceLabel(name)]} />
                <Legend formatter={marketplaceLabel} />
                {marketplaces.map((slug) => (
                  <Line
                    key={slug}
                    type="monotone"
                    dataKey={slug}
                    stroke={marketplaceColor(slug)}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
              </LineChart>
            </ChartCard>
          )}
        </>
      )}
    </div>
  );
}
