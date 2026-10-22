import React, { useEffect, useState } from "react";
import { getJSON } from "../lib/apiClient";

const brl = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));

const DEMAND = {
  good: { label: "Demanda promissora", color: "#1a7a54", bg: "#e5faf1" },
  uncertain: { label: "Demanda incerta", color: "#8a6d1d", bg: "#fff8e6" },
  weak: { label: "Demanda fraca", color: "#c31e3f", bg: "#fef1f4" },
  insufficient: { label: "Dados insuficientes", color: "#8898aa", bg: "#f6f9fc" },
};
const ADS = {
  good: { label: "Anúncios compensam", color: "#1a7a54", bg: "#e5faf1" },
  uncertain: { label: "Anúncios: incerto", color: "#8a6d1d", bg: "#fff8e6" },
  weak: { label: "Anúncios não compensam", color: "#c31e3f", bg: "#fef1f4" },
  insufficient: { label: "Anúncios: sem dado", color: "#8898aa", bg: "#f6f9fc" },
};
const COMPETITION = { LOW: "baixa", MEDIUM: "média", HIGH: "alta" };
const MARK = { pass: ["✓", "#2dce89"], fail: ["✗", "#f5365c"], unknown: ["?", "#c1c9d6"] };

function Badge({ meta }) {
  return (
    <span style={{ fontSize: 12, fontWeight: 700, color: meta.color, background: meta.bg, borderRadius: 999, padding: "4px 12px" }}>
      {meta.label}
    </span>
  );
}

function Metric({ label, value, hint }) {
  return (
    <div title={hint}>
      <div style={{ fontSize: 10, color: "#8898aa", textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: value === "—" ? "#c1c9d6" : "#32325d" }}>{value}</div>
    </div>
  );
}

function CheckList({ title, checks }) {
  if (!checks.length) return null;
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "#525f7f", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>{title}</div>
      {checks.map((c) => {
        const [mark, color] = MARK[c.status];
        return (
          <div key={c.key} style={{ display: "flex", gap: 8, fontSize: 12, padding: "3px 0", color: "#525f7f" }}>
            <span style={{ color, fontWeight: 900, width: 14, textAlign: "center" }}>{mark}</span>
            <span>
              <span style={{ color: "#32325d" }}>{c.label}</span>
              <span style={{ color: "#8898aa" }}> — {c.detail}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

// Carrega sozinho ao abrir o produto: Trends + Planejador do Google Ads + economia da comissão.
export default function ProductFunnel({ product }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [keywordInput, setKeywordInput] = useState("");
  const [conversion, setConversion] = useState("1.5");

  function load(keyword, conv) {
    setLoading(true);
    setError("");
    const q = new URLSearchParams();
    if (keyword) q.set("keyword", keyword);
    const c = Number(String(conv).replace(",", "."));
    if (c > 0 && c <= 50) q.set("conversion_pct", String(c));
    getJSON(`/catalog/products/${product.id}/funnel?${q.toString()}`)
      .then((d) => {
        setData(d);
        setKeywordInput(d.keyword || "");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    setData(null);
    load("", "1.5");
  }, [product.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const wrap = { marginTop: 4, border: "1px solid #eef0f5", borderRadius: 12, padding: 16, background: "#fcfdff" };

  if (error) {
    return <div style={{ ...wrap, color: "#f5365c", fontSize: 12 }}>Não foi possível calcular o funil: {error}</div>;
  }
  if (!data) {
    return (
      <div style={{ ...wrap, fontSize: 12, color: "#8898aa" }}>
        Consultando Google Trends e Google Ads para este produto (pode levar alguns segundos)…
      </div>
    );
  }

  const m = data.metrics || {};
  const trend = m.trend_direction
    ? `${m.trend_direction === "rising" ? "▲" : m.trend_direction === "falling" ? "▼" : "■"} ${m.growth_pct_30d > 0 ? "+" : ""}${m.growth_pct_30d}%`
    : "—";

  return (
    <div style={{ ...wrap, opacity: loading ? 0.6 : 1 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div style={{ fontWeight: 700, color: "#32325d", fontSize: 14 }}>Funil de venda · Google Trends + Google Ads</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <Badge meta={DEMAND[data.demand_verdict] || DEMAND.insufficient} />
          <Badge meta={ADS[data.ads_verdict] || ADS.insufficient} />
        </div>
      </div>
      <div style={{ fontSize: 12, color: "#525f7f", margin: "8px 0 10px" }}>{data.summary}</div>

      {data.planner_error && (
        <div style={{ fontSize: 11, color: "#c31e3f", background: "#fef1f4", padding: "6px 10px", borderRadius: 8, marginBottom: 8 }}>
          Google Ads falhou: {data.planner_error}
        </div>
      )}
      {!data.planner_provider && !data.planner_error && (
        <div style={{ fontSize: 11, color: "#8a6d1d", background: "#fff8e6", padding: "6px 10px", borderRadius: 8, marginBottom: 8 }}>
          Google Ads não conectado (Integrações → Google Ads): volume, CPC e disputa aparecem como “—”.
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 10, padding: "10px 0", borderTop: "1px solid #f0f2f7", borderBottom: "1px solid #f0f2f7" }}>
        <Metric label="Trends 30 dias" value={trend} hint="Média dos últimos 30 dias contra os 30 anteriores (Google Trends, Brasil)" />
        <Metric label="Buscas/mês" value={m.monthly_volume != null ? m.monthly_volume.toLocaleString("pt-BR") : "—"} />
        <Metric label="CPC" value={m.cpc_brl != null ? brl(m.cpc_brl) : "—"} hint="Estimativa do Planejador do Google Ads" />
        <Metric label="Disputa anúncios" value={m.competition ? COMPETITION[m.competition] : "—"} hint="Mede a disputa por anúncios pagos, não a posição orgânica" />
        <Metric label="Comissão/venda" value={brl(data.commission_per_sale)} hint="Preço × comissão anunciada" />
        <Metric label="Teto de CPC" value={brl(data.breakeven_cpc)} hint="Comissão por venda × taxa de conversão assumida" />
      </div>

      <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: 11, color: "#8898aa" }}>Palavra-chave:</span>
        <input
          value={keywordInput}
          onChange={(e) => setKeywordInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(keywordInput, conversion)}
          style={{ flex: 1, minWidth: 160, padding: "5px 9px", fontSize: 12, border: "1px solid #dee2e6", borderRadius: 8, background: "#fff" }}
        />
        <span style={{ fontSize: 11, color: "#8898aa" }} title="Premissa sua: de cada 100 cliques, quantos viram compra. Nenhuma API informa isso.">
          Conversão assumida:
        </span>
        <input
          value={conversion}
          onChange={(e) => setConversion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(keywordInput, conversion)}
          style={{ width: 52, padding: "5px 7px", fontSize: 12, border: "1px solid #dee2e6", borderRadius: 8, background: "#fff" }}
        />
        <span style={{ fontSize: 11, color: "#8898aa" }}>%</span>
        <button
          onClick={() => load(keywordInput, conversion)}
          disabled={loading}
          style={{ padding: "5px 12px", fontSize: 12, borderRadius: 8, border: "none", background: "#5e72e4", color: "#fff", fontWeight: 600, cursor: "pointer" }}
        >
          {loading ? "Analisando…" : "Analisar"}
        </button>
      </div>

      {data.candidates?.length > 1 && (
        <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", fontSize: 11, color: "#8898aa" }}>
          Outras opções do título:
          {data.candidates.map((c) => (
            <button
              key={c.keyword}
              onClick={() => load(c.keyword, conversion)}
              style={{
                fontSize: 11,
                padding: "3px 9px",
                borderRadius: 999,
                cursor: "pointer",
                border: c.keyword === data.keyword ? "1px solid #5e72e4" : "1px solid #dee2e6",
                background: c.keyword === data.keyword ? "#eef2ff" : "#fff",
                color: "#525f7f",
              }}
            >
              {c.keyword} · {c.monthly_volume != null ? `${c.monthly_volume.toLocaleString("pt-BR")}/mês` : "sem dado"}
            </button>
          ))}
        </div>
      )}

      <CheckList title="Demanda — o produto tem procura?" checks={data.checks.filter((c) => c.group === "demanda")} />
      <CheckList title="Tráfego pago — só vale se você for anunciar" checks={data.checks.filter((c) => c.group === "anuncios")} />

      <div style={{ fontSize: 10.5, color: "#adb5bd", marginTop: 10, lineHeight: 1.5 }}>
        Regras explícitas, não previsão de vendas. A palavra-chave
        {data.keyword_source === "manual" ? " foi informada por você" : " foi escolhida do título (a de maior volume)"} e o
        resultado depende dela. “?” = sem dado, não conta contra o produto. Se você divulga sem pagar clique (vídeo,
        redes), o que decide é a demanda.
      </div>
    </div>
  );
}
