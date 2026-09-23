import React, { useEffect, useState } from "react";
import { getJSON } from "../lib/apiClient";

const card = {
  background: "#fff",
  borderRadius: 10,
  padding: 16,
  boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)",
};

function fmtMoney(v) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtPct(v) {
  if (v === null || v === undefined) return "—";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function StatCard({ label, value, note, color = "#5e72e4" }) {
  return (
    <div className="col-xl-3 col-lg-6" style={{ marginBottom: 14 }}>
      <div style={{ ...card, borderLeft: `4px solid ${color}` }}>
        <div style={{ fontSize: 12, color: "#8898aa", textTransform: "uppercase", letterSpacing: 1 }}>{label}</div>
        <div style={{ fontSize: 26, fontWeight: 700, color: "#32325d", marginTop: 4 }}>{value}</div>
        {note && <div style={{ fontSize: 12, color: "#525f7f", marginTop: 6 }}>{note}</div>}
      </div>
    </div>
  );
}

function CategoryRow({ label, items }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: "1px solid #f6f9fc" }}>
      <span style={{ fontSize: 13, color: "#525f7f" }}>{label}</span>
      <span
        style={{
          fontSize: 12,
          fontWeight: 700,
          color: "#fff",
          background: items.length ? "#5e72e4" : "#8898aa",
          borderRadius: 999,
          padding: "3px 10px",
        }}
      >
        {items.length}
      </span>
    </div>
  );
}

export default function DailyOps({ marketplace } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    const query = marketplace ? `?marketplace=${encodeURIComponent(marketplace)}` : "";
    getJSON(`/operations/daily${query}`)
      .then((res) => !cancelled && setData(res))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [marketplace]);

  if (error) return <p style={{ color: "#f5365c" }}>Não foi possível carregar o Daily Ops: {error}</p>;
  if (!data) return <p style={{ color: "#8898aa" }}>Carregando...</p>;

  const { kpis } = data;

  return (
    <div>
      <p style={{ color: "#525f7f" }}>
        Estado real da operação (briefing §9) — o que existe hoje é dado real; quando algo não pode ser calculado, a
        nota abaixo explica o porquê em vez de mostrar um número inventado.
      </p>

      <div className="row" style={{ marginTop: 8 }}>
        <StatCard label="Vendas no período" value={kpis.sales_count} color="#2dce89" note={`${kpis.days} dia(s)`} />
        <StatCard label="Receita bruta" value={fmtMoney(kpis.gross_revenue)} color="#5e72e4" />
        <StatCard label="Comissão estimada" value={fmtMoney(kpis.commission_estimated)} color="#11cdef" />
        <StatCard label="Ticket médio" value={fmtMoney(kpis.average_ticket)} color="#fb6340" />
        <StatCard label="Produtos ativos" value={kpis.active_products} color="#5e72e4" />
        <StatCard label="Com venda" value={kpis.products_with_sales} color="#2dce89" />
        <StatCard label="Sem venda" value={kpis.products_without_sales} color="#f5365c" />
        <StatCard label="CTR" value={fmtPct(kpis.ctr)} color="#11cdef" />
        <StatCard label="Conversão" value={fmtPct(kpis.conversion_rate)} color="#11cdef" />
        <StatCard label="ROAS" value={kpis.roas ?? "—"} color="#fb6340" />
      </div>

      <div style={{ ...card, marginTop: 8 }}>
        <h6 style={{ color: "#32325d", marginTop: 0 }}>Categorias de decisão</h6>
        <CategoryRow label="Oportunidades hoje" items={data.opportunities_today} />
        <CategoryRow label="Recomendados" items={data.recommended} />
        <CategoryRow label="Aguardando decisão" items={data.awaiting_decision} />
        <CategoryRow label="Afiliação pendente" items={data.affiliation_pending} />
        <CategoryRow label="Criativos pendentes" items={data.creatives_pending} />
        <CategoryRow label="Criativos prontos" items={data.creatives_ready} />
        <CategoryRow label="Prontos p/ publicar" items={data.ready_to_publish} />
        <CategoryRow label="Publicados" items={data.published} />
        <CategoryRow label="Precisam otimização" items={data.optimization_required} />
      </div>

      {kpis.notes?.length > 0 && (
        <div style={{ ...card, marginTop: 16, background: "#f6f9fc" }}>
          <h6 style={{ color: "#32325d", marginTop: 0 }}>Notas do cálculo</h6>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "#8898aa" }}>
            {kpis.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </div>
      )}

      {data.alerts?.length > 0 && (
        <div style={{ ...card, marginTop: 16 }}>
          <h6 style={{ color: "#32325d", marginTop: 0 }}>Alertas</h6>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "#f5365c" }}>
            {data.alerts.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
