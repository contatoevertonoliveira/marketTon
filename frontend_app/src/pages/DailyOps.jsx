import React, { useEffect, useState } from "react";
import { getJSON } from "../lib/intelApi";

const card = {
  background: "#fff",
  borderRadius: 10,
  padding: 16,
  boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)",
};

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

function UnavailableCard({ label, reason }) {
  return (
    <div className="col-xl-3 col-lg-6" style={{ marginBottom: 14 }}>
      <div style={{ ...card, borderLeft: "4px solid #8898aa", opacity: 0.75 }}>
        <div style={{ fontSize: 12, color: "#8898aa", textTransform: "uppercase", letterSpacing: 1 }}>{label}</div>
        <div style={{ fontSize: 16, fontWeight: 600, color: "#8898aa", marginTop: 4 }}>Sem fonte de dados</div>
        <div style={{ fontSize: 12, color: "#adb5bd", marginTop: 6 }}>{reason}</div>
      </div>
    </div>
  );
}

export default function DailyOps() {
  const [ops, setOps] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getJSON("/dashboard/daily-ops")
      .then((data) => !cancelled && setOps(data))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <p style={{ color: "#f5365c" }}>Não foi possível carregar o Daily Ops: {error}</p>;
  }
  if (!ops) {
    return <p style={{ color: "#8898aa" }}>Carregando...</p>;
  }

  return (
    <div>
      <p style={{ color: "#525f7f" }}>
        Estado real da operação (briefing §9) — o que existe hoje é dado real; o que não tem fonte ainda aparece
        marcado como tal, em vez de mostrar zero.
      </p>
      <div className="row" style={{ marginTop: 8 }}>
        <StatCard label="Oportunidades hoje" value={ops.opportunities_today.count} color="#2dce89" />
        <StatCard label="Em forte crescimento" value={ops.trending_up.count} color="#11cdef" note="heat score ≥ 70" />
        <StatCard label="Esfriando" value={ops.cooling_down.count} color="#fb6340" note="heat score < 30" />
        <StatCard label="Recomendados" value={ops.recommended.count} color="#5e72e4" />
        <StatCard label="Aguardando decisão" value={ops.awaiting_decision.count} color="#f6c944" />
        <StatCard label="Afiliação pendente" value={ops.affiliation_pending.count} color="#f5365c" />
        <StatCard label="Criativos pendentes" value={ops.creative_pending.count} color="#fb6340" />
        <StatCard label="Criativos concluídos" value={ops.creative_ready.count} color="#2dce89" />
        <StatCard label="Prontos p/ publicar" value={ops.ready_to_publish.count} color="#11cdef" />
        <StatCard label="Publicados" value={ops.published.count} color="#2dce89" />
        <UnavailableCard label="Alertas" reason={ops.alerts.reason} />
        <UnavailableCard label="Vendas e comissões" reason={ops.sales_and_commissions.reason} />
      </div>

      <div style={{ ...card, marginTop: 8 }}>
        <h6 style={{ color: "#32325d" }}>Portfólio por estado</h6>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
          {Object.entries(ops.portfolio_performance.by_state).map(([state, count]) => (
            <span
              key={state}
              style={{
                background: "#f6f9fc",
                border: "1px solid #e9ecef",
                borderRadius: 8,
                padding: "6px 10px",
                fontSize: 12,
                color: "#525f7f",
              }}
            >
              {state}: <strong>{count}</strong>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
