import React, { useEffect, useState } from "react";
import { getJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)" };

// Exemplo só para enxergar o layout completo (CPC/volume/concorrência exigem
// um provedor pago configurado). Rotulado como exemplo em toda a tela.
const MOCK = {
  ranking_basis: "cpc_and_growth",
  planner_configured: true,
  fx_configured: true,
  top: [
    { keyword: "lanterna tática", trend_direction: "rising", growth_pct_30d: 155.7, audience: "masculino", monthly_volume: 22200, cpc_brl: 0.41, competition: "LOW" },
    { keyword: "legging térmica feminina", trend_direction: "rising", growth_pct_30d: 64.2, audience: "feminino", monthly_volume: 14800, cpc_brl: 0.63, competition: "MEDIUM" },
    { keyword: "garrafa térmica infantil", trend_direction: "rising", growth_pct_30d: 38.9, audience: "infantil", monthly_volume: 9900, cpc_brl: 0.72, competition: "LOW" },
    { keyword: "fone bluetooth esportivo", trend_direction: "rising", growth_pct_30d: 21.4, audience: null, monthly_volume: 40500, cpc_brl: 0.95, competition: "HIGH" },
    { keyword: "luminária led mesa", trend_direction: "rising", growth_pct_30d: 12.0, audience: null, monthly_volume: 6600, cpc_brl: 1.1, competition: "MEDIUM" },
  ],
  analyzed: [],
};

const AUDIENCE = { feminino: "Feminino", masculino: "Masculino", infantil: "Infantil" };
const COMPETITION = {
  LOW: { label: "Pouco disputado", color: "#2dce89" },
  MEDIUM: { label: "Disputa média", color: "#f6c944" },
  HIGH: { label: "Muito disputado", color: "#f5365c" },
};

function Chip({ children, color = "#8898aa" }) {
  return (
    <span style={{ fontSize: 11, fontWeight: 700, color, background: `${color}1f`, borderRadius: 999, padding: "3px 10px" }}>
      {children}
    </span>
  );
}

function Metric({ label, value, note }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "#8898aa", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: value === "—" ? "#c1c9d6" : "#32325d" }}>{value}</div>
      {note && <div style={{ fontSize: 10, color: "#adb5bd" }}>{note}</div>}
    </div>
  );
}

function trendLabel(item) {
  if (item.growth_pct_30d == null) return "—";
  const arrow = item.trend_direction === "rising" ? "▲" : item.trend_direction === "falling" ? "▼" : "■";
  const sign = item.growth_pct_30d > 0 ? "+" : "";
  return `${arrow} ${sign}${item.growth_pct_30d}%`;
}

function OpportunityCard({ item, rank }) {
  const up = item.trend_direction === "rising";
  const down = item.trend_direction === "falling";
  const comp = COMPETITION[item.competition];
  const cpc =
    item.cpc_brl != null ? `R$ ${item.cpc_brl.toFixed(2)}` : item.cpc_usd != null ? `US$ ${item.cpc_usd.toFixed(2)}` : "—";
  return (
    <div style={{ ...card, display: "grid", gridTemplateColumns: "40px 1.4fr repeat(4, 1fr)", gap: 16, alignItems: "center", marginBottom: 12 }}>
      <div style={{ fontSize: 22, fontWeight: 800, color: "#5e72e4" }}>#{rank}</div>
      <div>
        <div style={{ fontWeight: 700, color: "#32325d", fontSize: 15 }}>{item.keyword}</div>
        <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
          {item.audience ? <Chip color="#5e72e4">{AUDIENCE[item.audience]} (inferido)</Chip> : <Chip>Público não identificado</Chip>}
          {comp ? <Chip color={comp.color}>{comp.label} no Google</Chip> : <Chip>Concorrência —</Chip>}
        </div>
      </div>
      <Metric label="CPC" value={cpc} note={item.cpc_brl == null && item.cpc_usd != null ? "sem cotação p/ R$" : undefined} />
      <Metric label="Volume/mês" value={item.monthly_volume != null ? item.monthly_volume.toLocaleString("pt-BR") : "—"} />
      <Metric label="Trends (30 dias)" value={trendLabel(item)} />
      <div>
        <Chip color={up ? "#2dce89" : down ? "#f5365c" : "#8898aa"}>{up ? "Em alta" : down ? "Em baixa" : "Estável"}</Chip>
      </div>
    </div>
  );
}

export default function Opportunities() {
  const [useMock, setUseMock] = useState(false);
  const [input, setInput] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function load(keywords) {
    setLoading(true);
    setError("");
    const q = keywords ? `?keywords=${encodeURIComponent(keywords)}` : "";
    getJSON(`/trends/opportunities${q}`)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!useMock) load(input.trim() || null);
  }, [useMock]); // eslint-disable-line react-hooks/exhaustive-deps

  const view = useMock ? MOCK : data;

  return (
    <div>
      <div style={{ ...card, marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <div style={{ fontSize: 12, color: "#8898aa", maxWidth: 640 }}>
          {useMock
            ? "Dados de exemplo — só para ver o layout completo, com CPC, volume e concorrência."
            : "Tendência real do Google Trends (Brasil, últimos 30 dias contra os 30 anteriores). Público é inferido do texto da palavra-chave."}
        </div>
        <div style={{ display: "flex", borderRadius: 999, background: "#f6f9fc", padding: 3 }}>
          {[["Dados reais", false], ["Dados de exemplo", true]].map(([label, mock]) => (
            <button
              key={label}
              onClick={() => setUseMock(mock)}
              style={{
                border: "none",
                borderRadius: 999,
                padding: "7px 16px",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                background: useMock === mock ? "#5e72e4" : "transparent",
                color: useMock === mock ? "#fff" : "#525f7f",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {!useMock && (
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="palavras-chave separadas por vírgula (vazio = as do Product Hunter)"
            style={{ flex: 1, padding: "8px 12px", border: "1px solid #dee2e6", borderRadius: 8, fontSize: 13 }}
          />
          <button
            onClick={() => load(input.trim() || null)}
            disabled={loading}
            style={{ background: "#5e72e4", color: "#fff", border: "none", borderRadius: 8, padding: "8px 18px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
          >
            {loading ? "Analisando…" : "Analisar"}
          </button>
        </div>
      )}

      {error && <p style={{ color: "#f5365c" }}>{error}</p>}
      {!error && !view && <p style={{ color: "#8898aa" }}>Consultando o Google Trends (pode levar alguns segundos)…</p>}

      {view && (
        <>
          {!useMock && !view.planner_configured && (
            <div style={{ ...card, marginBottom: 16, background: "#fff8e6", fontSize: 12, color: "#8a6d1d" }}>
              <strong>CPC, volume e concorrência não estão ativos.</strong> O Google só entrega esses números pelo
              Planejador de Palavras-chave (Google Ads), sem API gratuita — hoje o ranking considera{" "}
              <em>só o crescimento</em> do Trends, não o custo. Configure <code>DATAFORSEO_LOGIN</code> e{" "}
              <code>DATAFORSEO_PASSWORD</code> (e <code>USD_BRL_RATE</code> para ver em R$) no <code>.env</code> para
              ativar.
            </div>
          )}
          <h6 style={{ color: "#32325d", margin: "0 0 10px" }}>
            Top oportunidades {view.ranking_basis === "cpc_and_growth" ? "— CPC baixo + tráfego crescente" : "— tráfego crescente"}
          </h6>
          {view.top.length === 0 ? (
            <div style={{ ...card, fontSize: 13, color: "#8898aa" }}>
              Nenhuma das palavras-chave analisadas está em alta agora (acima de +5% no mês). Tente outras palavras acima.
            </div>
          ) : (
            view.top.map((item, i) => <OpportunityCard key={item.keyword} item={item} rank={i + 1} />)
          )}

          {!useMock && view.analyzed.length > 0 && (
            <div style={{ ...card, marginTop: 20 }}>
              <h6 style={{ color: "#32325d", marginTop: 0 }}>Todas as palavras analisadas</h6>
              {view.analyzed.map((m) => (
                <div key={m.keyword} style={{ display: "flex", justifyContent: "space-between", padding: "7px 0", borderBottom: "1px solid #f6f9fc", fontSize: 13 }}>
                  <span style={{ color: "#32325d" }}>{m.keyword}</span>
                  <span style={{ color: m.trend_error ? "#f5365c" : "#525f7f" }}>
                    {m.trend_error ? m.trend_error : `${trendLabel(m)} · ${m.trend_direction === "rising" ? "em alta" : m.trend_direction === "falling" ? "em baixa" : "estável"}`}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
