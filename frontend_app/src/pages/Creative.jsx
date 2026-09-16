import React, { useEffect, useState } from "react";
import { getJSON, postJSON } from "../lib/apiClient";

const ASSET_TYPES = ["COPY", "IMAGE", "VIDEO", "VOICE", "EDIT", "APPROVAL"];
const LABELS = {
  COPY: "Copy",
  IMAGE: "Imagens",
  VIDEO: "Vídeo",
  VOICE: "Voz / narração",
  EDIT: "Edição",
  APPROVAL: "Aprovação",
};
const STATUSES = ["PENDING", "IN_PROGRESS", "READY", "APPROVED", "REJECTED", "BLOCKED"];
const STATUS_COLOR = {
  PENDING: "#f6c944",
  IN_PROGRESS: "#11cdef",
  READY: "#2dce89",
  APPROVED: "#2dce89",
  REJECTED: "#f5365c",
  BLOCKED: "#8898aa",
};

export function CreativeChecklist({ portfolioItemId, productId }) {
  const [assets, setAssets] = useState([]);
  const [readiness, setReadiness] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  function load() {
    if (!portfolioItemId) return;
    getJSON(`/creatives/assets?portfolio_item_id=${portfolioItemId}`).then((list) => setAssets(list));
    getJSON(`/creatives/publish-readiness/${portfolioItemId}`).then(setReadiness);
  }

  useEffect(load, [portfolioItemId]);

  function assetFor(type) {
    return assets.find((a) => a.asset_type === type);
  }

  async function ensureAsset(type) {
    const existing = assetFor(type);
    if (existing) return existing;
    return postJSON("/creatives/assets", {
      asset_type: type,
      portfolio_item_id: portfolioItemId,
      product_id: productId,
      title: `${LABELS[type]} do produto`,
    });
  }

  async function setStatus(type, status) {
    setBusy(type);
    setError("");
    try {
      const asset = await ensureAsset(type);
      await postJSON(`/creatives/assets/${asset.id}/status`, { status, actor: "operator" });
      load();
    } catch (e) {
      setError(`${LABELS[type]}: ${e.message}`);
    } finally {
      setBusy("");
    }
  }

  if (!portfolioItemId) return null;

  return (
    <div>
      <h6 style={{ color: "#32325d", marginTop: 12 }}>Pipeline de criativos</h6>
      <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
        {ASSET_TYPES.map((type) => {
          const asset = assetFor(type);
          const status = asset?.status || "PENDING";
          return (
            <div
              key={type}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "8px 10px",
                borderRadius: 8,
                background: "#f6f9fc",
                opacity: busy === type ? 0.6 : 1,
              }}
            >
              <span style={{ flex: 1, color: "#32325d", fontSize: 13 }}>{LABELS[type]}</span>
              <select
                value={status}
                disabled={busy === type}
                onChange={(e) => setStatus(type, e.target.value)}
                style={{ fontSize: 12, border: "1px solid #dee2e6", borderRadius: 6, padding: "3px 6px" }}
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <span
                style={{
                  fontSize: 11,
                  color: "#fff",
                  background: STATUS_COLOR[status] || "#8898aa",
                  borderRadius: 999,
                  padding: "2px 8px",
                  minWidth: 70,
                  textAlign: "center",
                }}
              >
                {status}
              </span>
            </div>
          );
        })}
      </div>

      {error && <div style={{ fontSize: 12, color: "#f5365c", marginTop: 8 }}>{error}</div>}

      {readiness && (
        <div
          style={{
            marginTop: 10,
            padding: "8px 10px",
            borderRadius: 8,
            background: readiness.can_publish ? "#e6f9f0" : "#f6f9fc",
            fontSize: 12,
            color: readiness.can_publish ? "#2dce89" : "#8898aa",
          }}
        >
          {readiness.can_publish
            ? "Pronto para publicar."
            : `Falta: ${readiness.missing_assets.join(", ") || "—"}`}
        </div>
      )}
    </div>
  );
}
