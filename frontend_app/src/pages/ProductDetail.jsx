import React, { useEffect, useState } from "react";
import { getJSON, postJSON } from "../lib/intelApi";
import { CreativeChecklist } from "./Creative";

const SCORE_LABELS = {
  heat: "Heat Score",
  opportunity: "Opportunity Score",
  producer_momentum: "Producer Momentum Score",
  creative_saturation: "Creative Saturation Score",
  portfolio: "Portfolio Score",
  creative: "Creative Score",
};

const ALL_SCORE_TYPES = Object.keys(SCORE_LABELS);

function ScoreBar({ scoreType, record }) {
  const label = SCORE_LABELS[scoreType];
  if (!record) {
    return (
      <div style={{ padding: "8px 0", borderBottom: "1px solid #f6f9fc" }}>
        <div style={{ fontSize: 12, color: "#8898aa" }}>{label}</div>
        <div style={{ fontSize: 12, color: "#adb5bd" }}>ainda não calculado — dado insuficiente</div>
      </div>
    );
  }
  return (
    <div style={{ padding: "8px 0", borderBottom: "1px solid #f6f9fc" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12, color: "#525f7f" }}>{label}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: "#32325d" }}>{record.result.toFixed(1)}/100</span>
      </div>
      <div style={{ background: "#f0f0f0", borderRadius: 4, height: 6, marginTop: 4 }}>
        <div
          style={{
            width: `${Math.min(100, record.result)}%`,
            background: record.result >= 70 ? "#2dce89" : record.result >= 40 ? "#f6c944" : "#f5365c",
            height: 6,
            borderRadius: 4,
          }}
        />
      </div>
      <div style={{ fontSize: 11, color: "#adb5bd", marginTop: 2 }}>
        confiabilidade: {record.reliability} · {record.version}
      </div>
    </div>
  );
}

function Explanation({ record }) {
  if (!record || !record.reasons?.length) return null;
  return (
    <ul style={{ margin: "4px 0 10px", paddingLeft: 16, fontSize: 12 }}>
      {record.reasons.map((r, i) => (
        <li key={i} style={{ color: r.polarity === "+" ? "#2dce89" : "#f5365c" }}>
          {r.polarity} {r.text}
        </li>
      ))}
    </ul>
  );
}

export default function ProductDetailDrawer({ portfolioItem, onClose, onChanged }) {
  const [product, setProduct] = useState(null);
  const [scores, setScores] = useState({});
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!portfolioItem) return;
    getJSON(`/products/${portfolioItem.product}/`).then(setProduct);
    getJSON(`/products/${portfolioItem.product}/scores/`).then((list) => {
      const map = {};
      list.forEach((r) => {
        map[r.score_type] = r;
      });
      setScores(map);
    });
  }, [portfolioItem]);

  if (!portfolioItem) return null;

  async function recompute() {
    setBusy(true);
    try {
      const list = await postJSON(`/products/${portfolioItem.product}/recompute-scores/`);
      const map = {};
      list.forEach((r) => {
        map[r.score_type] = r;
      });
      setScores(map);
    } finally {
      setBusy(false);
    }
  }

  async function doTransition(toState) {
    setBusy(true);
    try {
      await postJSON(`/portfolio/${portfolioItem.id}/transition/`, { to_state: toState, reason });
      setReason("");
      onChanged();
    } catch (e) {
      // eslint-disable-next-line no-alert
      alert(`Transição inválida: ${e.message}`);
    } finally {
      setBusy(false);
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
          <div style={{ fontSize: 11, color: "#8898aa", textTransform: "uppercase" }}>{portfolioItem.marketplace}</div>
          <h5 style={{ margin: "2px 0 0", color: "#32325d" }}>{portfolioItem.product_title}</h5>
        </div>
        <button onClick={onClose} style={{ border: "none", background: "transparent", fontSize: 20, cursor: "pointer" }}>
          ×
        </button>
      </div>

      {product && (
        <div style={{ marginTop: 10, fontSize: 13, color: "#525f7f" }}>
          R$ {Number(product.price ?? 0).toFixed(2)} · comissão {product.commission_pct ?? "—"}% · fonte {product.source} (
          {product.reliability})
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16 }}>
        <h6 style={{ color: "#32325d", margin: 0 }}>Scores</h6>
        <button
          onClick={recompute}
          disabled={busy}
          style={{ fontSize: 12, border: "1px solid #5e72e4", color: "#5e72e4", background: "#fff", borderRadius: 6, padding: "4px 8px", cursor: "pointer" }}
        >
          Recalcular
        </button>
      </div>
      {ALL_SCORE_TYPES.map((t) => (
        <React.Fragment key={t}>
          <ScoreBar scoreType={t} record={scores[t]} />
          <Explanation record={scores[t]} />
        </React.Fragment>
      ))}

      <h6 style={{ color: "#32325d", marginTop: 16 }}>Estado do portfólio</h6>
      <div style={{ fontSize: 13, color: "#32325d", fontWeight: 700 }}>{portfolioItem.state}</div>
      <input
        placeholder="motivo da transição (opcional)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        style={{ width: "100%", marginTop: 8, padding: "6px 8px", border: "1px solid #dee2e6", borderRadius: 6, fontSize: 12 }}
      />
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
        {portfolioItem.allowed_next_states.map((s) => (
          <button
            key={s}
            disabled={busy}
            onClick={() => doTransition(s)}
            style={{
              fontSize: 11,
              border: "1px solid #5e72e4",
              color: "#5e72e4",
              background: "#fff",
              borderRadius: 999,
              padding: "4px 10px",
              cursor: "pointer",
            }}
          >
            → {s}
          </button>
        ))}
        {portfolioItem.allowed_next_states.length === 0 && (
          <span style={{ fontSize: 12, color: "#8898aa" }}>estado terminal, sem transições disponíveis</span>
        )}
      </div>

      <CreativeChecklist portfolioItemId={portfolioItem.id} />
    </div>
  );
}
