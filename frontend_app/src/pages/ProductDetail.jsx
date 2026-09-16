import React, { useEffect, useState } from "react";
import { getJSON, postJSON } from "../lib/apiClient";
import { CreativeChecklist } from "./Creative";

const SCORE_LABELS = {
  HEAT: "Heat Score",
  OPPORTUNITY: "Opportunity Score",
  PRODUCER_MOMENTUM: "Producer Momentum Score",
  CREATIVE_SATURATION: "Creative Saturation Score",
  PORTFOLIO: "Portfolio Score",
  CREATIVE: "Creative Score",
};
const DIMENSIONS = Object.keys(SCORE_LABELS);

function ScoreBlock({ dimension, explanation, onCompute, busy }) {
  const label = SCORE_LABELS[dimension];
  if (!explanation) {
    return (
      <div style={{ padding: "8px 0", borderBottom: "1px solid #f6f9fc" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "#8898aa" }}>{label}</span>
          <button
            onClick={() => onCompute(dimension)}
            disabled={busy}
            style={{ fontSize: 11, border: "1px solid #5e72e4", color: "#5e72e4", background: "#fff", borderRadius: 6, padding: "2px 8px", cursor: "pointer" }}
          >
            Calcular
          </button>
        </div>
        <div style={{ fontSize: 11, color: "#adb5bd" }}>ainda não calculado</div>
      </div>
    );
  }
  const higherIsBetter = explanation.higher_score_is_better !== false;
  const good = higherIsBetter ? explanation.score >= 70 : explanation.score <= 30;
  const bad = higherIsBetter ? explanation.score < 40 : explanation.score > 60;
  const color = good ? "#2dce89" : bad ? "#f5365c" : "#f6c944";
  return (
    <div style={{ padding: "8px 0", borderBottom: "1px solid #f6f9fc" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12, color: "#525f7f" }}>{label}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: "#32325d" }}>{explanation.score.toFixed(1)}/100</span>
      </div>
      <div style={{ background: "#f0f0f0", borderRadius: 4, height: 6, marginTop: 4 }}>
        <div style={{ width: `${Math.min(100, explanation.score)}%`, background: color, height: 6, borderRadius: 4 }} />
      </div>
      <div style={{ fontSize: 11, color: "#adb5bd", marginTop: 2 }}>
        {explanation.status === "INSUFFICIENT_DATA" ? "dado insuficiente" : "ok"} · confiança{" "}
        {explanation.confidence != null ? `${(explanation.confidence * 100).toFixed(0)}%` : "—"} ·{" "}
        {explanation.algorithm_version}
      </div>
      {explanation.reasons?.length > 0 && (
        <ul style={{ margin: "4px 0 0", paddingLeft: 16, fontSize: 12 }}>
          {explanation.reasons.map((r, i) => (
            <li key={i} style={{ color: r.startsWith("+") ? "#2dce89" : "#f5365c" }}>
              {r}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ProductDetailDrawer({ portfolioItem, onClose, onChanged }) {
  const [product, setProduct] = useState(null);
  const [item, setItem] = useState(portfolioItem);
  const [busyDimension, setBusyDimension] = useState("");
  const [busyTransition, setBusyTransition] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  function load() {
    getJSON(`/catalog/products/${portfolioItem.product_id}`).then(setProduct);
    getJSON(`/portfolio/items/${portfolioItem.id}`).then(setItem);
  }

  useEffect(load, [portfolioItem.id]);

  if (!portfolioItem) return null;

  const explanationsByDim = {};
  (product?.score_explanations || []).forEach((e) => {
    explanationsByDim[e.dimension] = e;
  });

  async function computeScore(dimension) {
    setBusyDimension(dimension);
    setError("");
    try {
      await postJSON("/scoring/compute", { dimension, target_type: "product", target_id: portfolioItem.product_id });
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyDimension("");
    }
  }

  async function doTransition(toState) {
    setBusyTransition(true);
    setError("");
    try {
      await postJSON(`/portfolio/items/${item.id}/transition`, { to_state: toState, actor: "operator", reason });
      setReason("");
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyTransition(false);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        bottom: 0,
        width: 420,
        background: "#fff",
        boxShadow: "-4px 0 24px rgba(0,0,0,0.15)",
        zIndex: 100,
        overflowY: "auto",
        padding: 20,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 11, color: "#8898aa", textTransform: "uppercase" }}>{item.marketplace}</div>
          <h5 style={{ margin: "2px 0 0", color: "#32325d" }}>{product?.title || `Produto #${item.product_id}`}</h5>
        </div>
        <button onClick={onClose} style={{ border: "none", background: "transparent", fontSize: 20, cursor: "pointer" }}>
          ×
        </button>
      </div>

      {product && (
        <div style={{ marginTop: 10, fontSize: 13, color: "#525f7f" }}>
          {product.currency || "R$"} {Number(product.price ?? 0).toFixed(2)} · comissão{" "}
          {product.affiliate_commission_pct != null ? `${product.affiliate_commission_pct}%` : "—"} · rating{" "}
          {product.rating ?? "—"}
        </div>
      )}

      <h6 style={{ color: "#32325d", marginTop: 16 }}>Scores</h6>
      {DIMENSIONS.map((d) => (
        <ScoreBlock
          key={d}
          dimension={d}
          explanation={explanationsByDim[d]}
          onCompute={computeScore}
          busy={busyDimension === d}
        />
      ))}

      <h6 style={{ color: "#32325d", marginTop: 16 }}>Estado do portfólio</h6>
      <div style={{ fontSize: 13, color: "#32325d", fontWeight: 700 }}>{item.state}</div>
      <input
        placeholder="motivo da transição (opcional)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        style={{ width: "100%", marginTop: 8, padding: "6px 8px", border: "1px solid #dee2e6", borderRadius: 6, fontSize: 12, boxSizing: "border-box" }}
      />
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
        {(item.allowed_transitions || []).map((s) => (
          <button
            key={s}
            disabled={busyTransition}
            onClick={() => doTransition(s)}
            style={{ fontSize: 11, border: "1px solid #5e72e4", color: "#5e72e4", background: "#fff", borderRadius: 999, padding: "4px 10px", cursor: "pointer" }}
          >
            → {s}
          </button>
        ))}
        {(item.allowed_transitions || []).length === 0 && (
          <span style={{ fontSize: 12, color: "#8898aa" }}>estado terminal, sem transições disponíveis</span>
        )}
      </div>

      {error && <div style={{ fontSize: 12, color: "#f5365c", marginTop: 8 }}>{error}</div>}

      <CreativeChecklist portfolioItemId={item.id} productId={item.product_id} />
    </div>
  );
}
